#!/usr/bin/env python3
import os
import subprocess
import time

import numpy as np
import requests
import sounddevice as sd
import webrtcvad
from playsound import playsound

# ── Config ─────────────────────────────────────────────────
SERVER = "http://192.168.0.17:5000"   # 改成你的 PC IP
DEVICE = "plughw:1,0"                 # 从 arecord -l 查到
FS = 48000                            # VAD 采样率
FRAME_MS = 30                         # VAD 帧长 30ms
VAD_AGGR = 1                          # 勇气等级 0~3
SILENCE_THRESHOLD = 500               # PCM 振幅阈值（可调）

# ── 待机阶段录短音，只有“有声音”才返回 ───────────────────
def silent_record(max_duration=3.0, silence_limit=1.0):
    vad = webrtcvad.Vad(VAD_AGGR)
    frame_len = int(FS * FRAME_MS / 1000)
    max_frames = int(max_duration * 1000 / FRAME_MS)
    silence_frames = int(silence_limit * 1000 / FRAME_MS)

    stream = sd.RawInputStream(
        samplerate=FS, channels=1, dtype="int16",
        blocksize=frame_len, device=DEVICE
    )
    stream.start()

    voiced = []
    silent_count = 0
    frames = 0
    try:
        while frames < max_frames and silent_count < silence_frames:
            data, _ = stream.read(frame_len)
            frames += 1
            if vad.is_speech(data, FS):
                voiced.append(data)
                silent_count = 0
            else:
                if voiced:
                    silent_count += 1
    finally:
        stream.stop()
        stream.close()

    return b"".join(voiced)


# ── 用 VAD 来“唤醒”──检测到任何语音就返回──
def listen_for_wake():
    print("Famix Pi 启动，进入待机喚醒中…")
    while True:
        pcm = silent_record()
        # 如果确实录到了一点语音，就唤醒
        if pcm and np.frombuffer(pcm, np.int16).max() > SILENCE_THRESHOLD:
            print("[Wake] 检测到声音，进入对话流程")
            return


# ── 唤醒后录对话 WAV ───────────────────────────────────────
def record_dialog(duration=5, wav="/tmp/tmp.wav"):
    print("开始录音…")
    cmd = [
        "arecord", "-D", DEVICE,
        "-f", "S16_LE", "-r", "48000",
        "-c", "1", "-d", str(duration),
        wav
    ]
    subprocess.run(cmd, check=True)
    return wav


def wav2mp3(wav, mp3="/tmp/tmp.mp3"):
    cmd = [
        "ffmpeg", "-y", "-i", wav,
        "-codec:a", "libmp3lame", "-qscale:a", "5",
        mp3
    ]
    subprocess.run(cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True
    )
    return mp3


def send_audio(mp3_path):
    url = f"{SERVER}/api/audio"
    print(f"POST → {url}")
    with open(mp3_path, "rb") as f:
        files = {"file": ("voice.mp3", f, "audio/mpeg")}
        resp = requests.post(url, files=files, timeout=30)
    resp.raise_for_status()
    return resp.content


# ── 主循环 ─────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        while True:
            # 1️⃣ wait wake
            listen_for_wake()

            # 2️⃣ record dialog
            wav = record_dialog(duration=5)
            mp3 = wav2mp3(wav)

            # 3️⃣ upload & get reply
            reply = send_audio(mp3)
            out = "/tmp/famix_reply.mp3"
            with open(out, "wb") as fo:
                fo.write(reply)

            # 4️⃣ play
            print("Playing reply…")
            playsound(out)

            # 5️⃣ clean up
            for fn in (wav, mp3, out):
                try: os.remove(fn)
                except: pass

    except KeyboardInterrupt:
        print("Bye!")
