# -*- coding: utf-8 -*-
import pvporcupine
from pvrecorder import PvRecorder
import sys

ACCESS_KEY   = os.environ.get("PICOVOICE_ACCESS_KEY", "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw==")
KEYWORD_PATH = "/home/admin/Porcupine/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"
DEVICE_INDEX = 2   # 改成你的麥克風 index

def main():
    if not ACCESS_KEY or "YOUR_ACCESS_KEY_HERE" in ACCESS_KEY:
        print("⚠️ 請先填入 Porcupine ACCESS_KEY。")
        sys.exit(1)

    # 建立 Porcupine 偵測器
    porcupine = pvporcupine.create(
        access_key=ACCESS_KEY,
        keyword_paths=[KEYWORD_PATH],
        sensitivities=[0.7]  # 測試先用較高靈敏度
    )

    # 建立錄音器
    recorder = PvRecorder(device_index=DEVICE_INDEX, frame_length=porcupine.frame_length)
    recorder.start()

    print("🟢 開始測試喚醒詞，請說出你的關鍵詞（Ctrl+C 停止）...")

    try:
        while True:
            pcm = recorder.read()  # list[int16]
            result = porcupine.process(pcm)
            if result >= 0:
                print("✅ 偵測到喚醒詞！")
    except KeyboardInterrupt:
        print("\n🛑 測試結束")
    finally:
        recorder.stop()
        recorder.delete()
        porcupine.delete()

if __name__ == "__main__":
    main()
