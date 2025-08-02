# Famix-pi-client/pi_client.py

import os
import time
import subprocess
import requests

from pocketsphinx import LiveSpeech
from playsound import playsound

# 使用者設定
SERVER = "http://192.168.0.17:5000"     # PC 伺服器 API
DEVICE = "plughw:1,0"                   # 根據 arecord -l 結果
REC_SECONDS = 6                         # 錄音長度
FS = 44100                              # 實際錄音用44100, 但LiveSpeech不指定samplerate
WAKEWORD = "hi famix"

def wait_for_wake_word():
    print(f"Famix Pi 已啟動，請對麥克風說出喚醒詞：{WAKEWORD}")
    # 嘗試僅指定 device，不設 samplerate（部分設備一定要設，請視情況加）
    for phrase in LiveSpeech(keyphrase=WAKEWORD, kws_threshold=1e-20, device=DEVICE):
        print("✅ 偵測到喚醒詞，準備開始錄音！")
        break

def record_audio(wav_path="/tmp/famix_input.wav"):
    print(f"🎤 開始錄音（{REC_SECONDS} 秒），請開始說話...")
    cmd = [
        "arecord",
        "-D", DEVICE,
        "-f", "S16_LE",
        "-r", str(FS),
        "-c", "1",
        "-d", str(REC_SECONDS),
        wav_path
    ]
    subprocess.run(cmd, check=True)
    return wav_path

def wav_to_mp3(wav_path, mp3_path="/tmp/famix_input.mp3"):
    cmd = [
        "ffmpeg", "-y", "-i", wav_path,
        "-codec:a", "libmp3lame", "-qscale:a", "5",
        mp3_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return mp3_path

def send_audio(mp3_path):
    url = f"{SERVER}/api/audio"
    print(f"⬆️  上傳 MP3 至伺服器 {url}")
    with open(mp3_path, "rb") as f:
        files = {"file": ("voice.mp3", f, "audio/mpeg")}
        resp = requests.post(url, files=files, timeout=30)
    resp.raise_for_status()
    return resp.content

def play_audio(mp3_bytes, out_path="/tmp/famix_reply.mp3"):
    with open(out_path, "wb") as fo:
        fo.write(mp3_bytes)
    print("🔊 播放伺服器回應 ...")
    playsound(out_path)
    os.remove(out_path)

def main():
    try:
        while True:
            # 1️⃣ 等待喚醒詞
            wait_for_wake_word()

            # 2️⃣ 錄音
            wav = record_audio()

            # 3️⃣ wav 轉 mp3
            mp3 = wav_to_mp3(wav)

            # 4️⃣ 上傳 mp3 並取得回應
            reply = send_audio(mp3)

            # 5️⃣ 播放回應
            play_audio(reply)

            # 6️⃣ 清理檔案
            for fn in (wav, mp3):
                try: os.remove(fn)
                except: pass

            print("=== 已回到待機 ===\n")
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n👋 Bye Famix Pi!")

if __name__ == "__main__":
    main()
