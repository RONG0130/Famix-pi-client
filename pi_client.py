import os
import time
import numpy as np
import pvporcupine
import pyaudio
import requests
from playsound import playsound
import subprocess

# --- 基本參數 ---
SERVER = "http://192.168.0.17:5000"       # 你的伺服器 API
WAKEWORD_PATH = "/home/pi/Famix-pi-client/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"   # Porcupine 喚醒詞檔案
REC_SECONDS = 6
DEVICE = "plughw:1,0"                     # 根據 arecord -l 結果設置
FS = 16000                                # 建議與 Porcupine 相同或44100

def wait_for_wake_word():
    print(f"Famix Pi 已啟動，請說出喚醒詞 ...")
    porcupine = pvporcupine.create(keyword_paths=[WAKEWORD_PATH])
    pa = pyaudio.PyAudio()
    audio_stream = pa.open(
        rate=porcupine.sample_rate,
        channels=1,
        format=pyaudio.paInt16,
        input=True,
        frames_per_buffer=porcupine.frame_length
    )
    try:
        while True:
            pcm = audio_stream.read(porcupine.frame_length, exception_on_overflow=False)
            pcm = np.frombuffer(pcm, dtype=np.int16)
            result = porcupine.process(pcm)
            if result >= 0:
                print("✅ 偵測到喚醒詞，準備開始錄音！")
                break
    finally:
        audio_stream.close()
        pa.terminate()
        porcupine.delete()

def record_audio(wav_path="/tmp/famix_input.wav"):
    print(f"🎤 開始錄音（{REC_SECONDS} 秒），請開始說話 ...")
    cmd = [
        "arecord", "-D", DEVICE,
        "-f", "S16_LE", "-r", str(FS),
        "-c", "1", "-d", str(REC_SECONDS), wav_path
    ]
    subprocess.run(cmd, check=True)
    return wav_path

def wav_to_mp3(wav_path, mp3_path="/tmp/famix_input.mp3"):
    cmd = [
        "ffmpeg", "-y", "-i", wav_path,
        "-codec:a", "libmp3lame", "-qscale:a", "5", mp3_path
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
            wait_for_wake_word()
            wav = record_audio()
            mp3 = wav_to_mp3(wav)
            reply = send_audio(mp3)
            play_audio(reply)
            for fn in (wav, mp3):
                try: os.remove(fn)
                except: pass
            print("=== 已回到待機 ===\n")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Bye Famix Pi!")

if __name__ == "__main__":
    main()
