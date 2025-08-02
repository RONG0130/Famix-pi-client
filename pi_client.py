import os
import time
import subprocess
import requests

from pocketsphinx import AudioFile
from playsound import playsound

# ========== 使用者可調整參數 ==============
SERVER = "http://192.168.0.17:5000"     # PC 伺服器 API 位址
DEVICE = "plughw:1,0"                   # 依 arecord -l 結果設置
REC_SECONDS = 6                         # 錄音長度（秒）
FS = 44100                              # 錄音採樣率
WAKEWORD = "hi famix"
MODEL_PATH = "/home/pi/Famix-pi-client/model/en-us"  # 改成你實際模型資料夾
# ==========================================

def wait_for_wake_word():
    print(f"Famix Pi 已啟動，請說出喚醒詞：{WAKEWORD}")
    while True:
        # 1. 錄音 2 秒
        wav_path = "/tmp/tmp_listen.wav"
        cmd = [
            "arecord",
            "-D", DEVICE,
            "-f", "S16_LE",
            "-r", str(FS),
            "-c", "1",
            "-d", "2",
            wav_path
        ]
        subprocess.run(cmd, check=True)

        # 2. 用 pocketsphinx 辨識
        config = {
            'audio_file': wav_path,
            'hmm': MODEL_PATH,  # <=== 這裡直接用 model/en-us
            'lm': os.path.join(MODEL_PATH, 'en-us.lm.bin'),
            'dict': os.path.join(MODEL_PATH, 'cmudict-en-us.dict')
        }
        print(f"[DEBUG] config: {config}")  # 可選，debug 用
        audio = AudioFile(**config)
        detected = False
        for phrase in audio:
            print(f"[DEBUG] phrase: {phrase}")
            if WAKEWORD in str(phrase).lower():
                detected = True
                break

        if detected:
            print("✅ 偵測到喚醒詞，準備開始錄音！")
            os.remove(wav_path)
            break
        os.remove(wav_path)

# 其餘 record_audio、wav_to_mp3、send_audio、play_audio、main 全部保留你的寫法！

# ...（其餘程式碼同你原本的）

