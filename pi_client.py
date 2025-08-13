# -*- coding: utf-8 -*-
# Porcupine wake word -> record -> back to standby (with cooldown & buffer flush)
import os
import sys
import time
import wave
import struct
import datetime

import pvporcupine
from pvrecorder import PvRecorder

# ======== config ========
ACCESS_KEY   = os.environ.get("PICOVOICE_ACCESS_KEY", "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw==")
KEYWORD_PATH = "/home/admin/Porcupine/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"
DEVICE_INDEX = 2          # 改成你的 USB Mic index
SENSITIVITY  = 0.75       # 0~1 越大越敏感；成功後可微調
RECORD_SEC   = 3          # 偵測到後錄音秒數
COOLDOWN_SEC = 1.2        # 錄完後冷卻，避免連續觸發
FLUSH_MS     = 300        # 錄完後丟掉這麼長的殘留緩衝（避免尾音回觸發）
OUT_DIR      = "./"       # 錄音輸出資料夾

def timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def upload(path: str):
    """錄完要上傳就實作這裡。例：
    import requests; requests.post('http://server/upload', files={'file': open(path,'rb')})
    """
    pass

def record_after_hit(recorder, porcupine, first_frame):
    """偵測到後，從 first_frame 開始錄 RECORD_SEC 秒並回傳檔名。"""
    frames = [first_frame]
    frames_needed = int(porcupine.sample_rate / porcupine.frame_length * RECORD_SEC) - 1
    for _ in range(max(0, frames_needed)):
        frames.append(recorder.read())

    out_path = os.path.join(OUT_DIR, f"wake_audio_{timestamp()}.wav")
    with wave.open(out_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(porcupine.sample_rate)
        for block in frames:
            wf.writeframes(struct.pack("<" + "h"*len(block), *block))
    return out_path

def flush_buffer(recorder, porcupine, ms: int):
    """丟掉一小段殘留緩衝，避免尾音/回授立即再觸發。"""
    frames_to_drop = int(porcupine.sample_rate / porcupine.frame_length * (ms / 1000.0))
    for _ in range(max(0, frames_to_drop)):
        _ = recorder.read()

def main():
    if not ACCESS_KEY or "YOUR_ACCESS_KEY_HERE" in ACCESS_KEY or ACCESS_KEY == "填你的ACCESS_KEY":
        print("⚠️ 請先填入 Porcupine ACCESS_KEY（建議用環境變數 PICOVOICE_ACCESS_KEY）。")
        sys.exit(1)
    os.makedirs(OUT_DIR, exist_ok=True)

    porcupine = pvporcupine.create(
        access_key=ACCESS_KEY,
        keyword_paths=[KEYWORD_PATH],
        sensitivities=[SENSITIVITY]
    )
    recorder = PvRecorder(device_index=DEVICE_INDEX, frame_length=porcupine.frame_length)
    recorder.start()

    print("[Standby] 等待喚醒詞…（Ctrl+C 結束）")

    try:
        while True:
            pcm = recorder.read()           # list[int16]
            result = porcupine.process(pcm) # >=0 命中；-1 未命中
            if result >= 0:
                print("[Hit] 偵測到喚醒詞 → 開始錄音")
                print(f"[Recording] {RECORD_SEC} 秒…")
                out_path = record_after_hit(recorder, porcupine, pcm)
                print(f"[Saved] {out_path}")

                # (可選) 上傳
                upload(out_path)

                # 冷卻前先 flush 一點緩衝，避免尾音連續觸發
                flush_buffer(recorder, porcupine, FLUSH_MS)
                print(f"[Cooldown] {COOLDOWN_SEC}s …")
                time.sleep(COOLDOWN_SEC)

                print("[Standby] 回到待機，繼續偵測…")
    except KeyboardInterrupt:
        print("\n[Exit] 測試結束")
    finally:
        recorder.stop()
        recorder.delete()
        porcupine.delete()

if __name__ == "__main__":
    main()
