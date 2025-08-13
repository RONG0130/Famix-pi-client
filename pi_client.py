import os
import sys
import time
import wave
import struct
import datetime

import pvporcupine
from pvrecorder import PvRecorder

# ======== 可調參數 ========
ACCESS_KEY   = os.environ.get("PICOVOICE_ACCESS_KEY", "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw==")
KEYWORD_PATH = "/home/admin/Porcupine/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"
DEVICE_INDEX = 2            # 依 arecord -l；USB Mic 多半是 1 或 2
SENSITIVITY  = 0.7          # 0~1，越大越容易觸發
RECORD_SEC   = 3            # 偵測到後錄音秒數
COOLDOWN_SEC = 1.5          # 錄完後冷卻秒數（避免連續觸發）
OUT_DIR      = "./"         # 錄音輸出資料夾（可改成你要的路徑）

def timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def record_after_hit(recorder, porcupine, first_frame):
    """
    偵測到關鍵詞後，從當前 frame 開始錄 RECORD_SEC 秒，回傳輸出檔名。
    - recorder: PvRecorder
    - porcupine: Porcupine（僅取 sample_rate / frame_length）
    - first_frame: list[int16]，觸發當下那個 frame
    """
    frames = [first_frame]

    # 計算還需要讀幾個 frame 才湊滿 RECORD_SEC 秒
    frames_needed = int(porcupine.sample_rate / porcupine.frame_length * RECORD_SEC) - 1
    for _ in range(max(0, frames_needed)):
        frames.append(recorder.read())

    # 寫 WAV（int16 單聲道）
    out_path = os.path.join(OUT_DIR, f"wake_audio_{timestamp()}.wav")
    with wave.open(out_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(porcupine.sample_rate)
        for block in frames:
            wf.writeframes(struct.pack("<" + "h"*len(block), *block))

    return out_path

def main():
    if not ACCESS_KEY or "YOUR_ACCESS_KEY_HERE" in ACCESS_KEY or ACCESS_KEY == "填你的ACCESS_KEY":
        print("⚠️ 請先填入 Porcupine ACCESS_KEY（建議用環境變數 PICOVOICE_ACCESS_KEY）。")
        sys.exit(1)

    os.makedirs(OUT_DIR, exist_ok=True)

    # 建立 Porcupine 偵測器
    porcupine = pvporcupine.create(
        access_key=ACCESS_KEY,
        keyword_paths=[KEYWORD_PATH],
        sensitivities=[SENSITIVITY]
    )

    # 建立錄音器
    recorder = PvRecorder(device_index=DEVICE_INDEX, frame_length=porcupine.frame_length)
    recorder.start()

    print("🟢 開始偵測喚醒詞，偵測到會自動錄音並存檔（Ctrl+C 結束）...")

    try:
        while True:
            pcm = recorder.read()              # list[int16]
            result = porcupine.process(pcm)    # >=0 代表命中；-1 代表未命中
            if result >= 0:
                print(f"\n✅ 偵測到喚醒詞！開始錄音 {RECORD_SEC} 秒…")
                out_path = record_after_hit(recorder, porcupine, pcm)
                print(f"💾 已儲存：{out_path}")
                time.sleep(COOLDOWN_SEC)       # 簡單冷卻，避免連續觸發
    except KeyboardInterrupt:
        print("\n🛑 測試結束")
    finally:
        recorder.stop()
        recorder.delete()
        porcupine.delete()

if __name__ == "__main__":
    main()

