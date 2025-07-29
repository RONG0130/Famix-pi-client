#!/usr/bin/env python3
import os
import subprocess
import time
import requests
import webrtcvad
import sounddevice as sd
import numpy as np
from playsound import playsound

# █ 配置 █
SERVER = "http://192.168.0.17ㄎ:5000"  # 要调用的 PC 端 Flask Server
DEVICE = "plughw:1,0"                # `arecord -l` 列出的录音设备

# ─── VAD 等待喚醒 ───────────────────────────────────────────────────────
def listen_for_wake(
    fs: int = 16000,
    frame_ms: int = 30,
    aggressiveness: int = 1,
    silence_limit: float = 1.0,
    max_duration: float = 3.0
) -> None:
    """
    使用 webrtcvad 靜默錄音偵測語音片段，
    只要偵測到一次人聲，就結束偵測並返回。
    """
    vad = webrtcvad.Vad(aggressiveness)
    frame_len = int(fs * frame_ms / 1000)
    silence_frames = int(silence_limit * 1000 / frame_ms)
    max_frames = int(max_duration * 1000 / frame_ms)

    stream = sd.RawInputStream(
        samplerate=fs,
        channels=1,
        dtype='int16',
        blocksize=frame_len
    )
    stream.start()

    voiced = False
    silent_count = 0
    for _ in range(max_frames):
        data, _ = stream.read(frame_len)
        if vad.is_speech(data, fs):
            voiced = True
            silent_count = 0
        else:
            if voiced:
                silent_count += 1
                if silent_count > silence_frames:
                    break
    stream.stop()
    stream.close()

# ─── WAV/MP3 處理 ───────────────────────────────────────────────────────
def record_wav(duration: int = 3, wav: str = "/tmp/tmp.wav") -> str:
    cmd = [
        "arecord", "-D", DEVICE,
        "-f", "S16_LE", "-r", "44100", "-c", "1", "-d", str(duration),
        wav
    ]
    subprocess.run(cmd, check=True)
    return wav


def wav2mp3(wav: str, mp3: str = "/tmp/tmp.mp3") -> str:
    cmd = [
        "ffmpeg", "-y", "-i", wav,
        "-codec:a", "libmp3lame", "-qscale:a", "5",
        mp3
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return mp3

# ─── 上傳並拿回回覆 ────────────────────────────────────────────────────
def send_audio(mp3_path: str) -> bytes:
    url = f"{SERVER}/api/audio"
    print(f"POST → {url}")
    with open(mp3_path, "rb") as f:
        files = {"file": ("voice.mp3", f, "audio/mpeg")}
        resp = requests.post(url, files=files, timeout=30)
    resp.raise_for_status()
    return resp.content

# ─── 播放 & 清理 ─────────────────────────────────────────────────────
def play_mp3(path: str) -> None:
    playsound(path)


def cleanup(*files: str) -> None:
    for fn in files:
        try:
            if fn and os.path.exists(fn):
                os.remove(fn)
        except:
            pass

# ─── 主流程 ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Famix Pi 啟動，進入待機喚醒中…")
    while True:
        # 等待語音喚醒
        listen_for_wake()
        print("偵測到語音，開始錄音…")

        # 錄制正式語音
        wav = record_wav(duration=3)
        mp3 = wav2mp3(wav)

        # 上傳並獲取回覆
        print("上傳音訊，等待 Famix 回覆…")
        reply_bytes = send_audio(mp3)

        # 保存並播放回覆
        out = "/tmp/famix_reply.mp3"
        with open(out, "wb") as f:
            f.write(reply_bytes)
        print("播放 Famix 回覆…")
        play_mp3(out)

        # 清理暫存 & 回到待機
        cleanup(wav, mp3, out)
        print("回到待機…\n")
        time.sleep(0.2)
