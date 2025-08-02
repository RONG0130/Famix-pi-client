import os
import time
import subprocess
import requests
from pocketsphinx import AudioFile
from playsound import playsound

# === 使用者設定 ===
SERVER = "http://192.168.0.17:5000"
DEVICE = "plughw:1,0"
REC_SECONDS = 6
FS = 44100
WAKEWORD = "hi famix"
MODEL_PATH = "/home/pi/Famix-pi-client/model/en-us"  # 請根據實際模型資料夾改成你的絕對路徑

def wait_for_wake_word():
    print(f"Famix Pi 已啟動，請說出喚醒詞：{WAKEWORD}")
    wav_path = "/tmp/tmp_listen.wav"
    while True:
        # 1. 錄音 2 秒
        cmd = [
            "arecord", "-D", DEVICE,
            "-f", "S16_LE", "-r", str(FS),
            "-c", "1", "-d", "2", wav_path
        ]
        subprocess.run(cmd, check=True)

        # 2. Pocketsphinx 辨識
        config = {
            'audio_file': wav_path,
            'hmm': MODEL_PATH,
            'lm': os.path.join(MODEL_PATH, 'en-us.lm.bin'),
            'dict': os.path.join(MODEL_PATH, 'cmudict-en-us.dict')
        }
        audio = AudioFile(**config)
        detected = False
        for phrase in audio:
            if WAKEWORD in str(phrase).lower():
                detected = True
                break

        os.remove(wav_path)

        if detected:
            print("✅ 偵測到喚醒詞，準備開始錄音！")
            break

        # 降低記憶體佔用，每次 sleep 2 秒
        time.sleep(2)

def record_audio(wav_path="/tmp/famix_input.wav"):
    print(f"🎤 開始錄音（{REC_SECONDS} 秒），請開始說話...")
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
            time.sleep(1)  # 讓主循環不要狂刷，額外休息一秒

    except KeyboardInterrupt:
        print("\n👋 Bye Famix Pi!")

if __name__ == "__main__":
    main()
