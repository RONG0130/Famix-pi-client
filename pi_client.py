# -*- coding: utf-8 -*-
import pvporcupine
from pvrecorder import PvRecorder
import wave
import time
import datetime
import math
import struct
import sys

ACCESS_KEY = "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw=="
KEYWORD_PATH = "/home/admin/Porcupine/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"

SENSITIVITY = 0.25
CONFIRM_FRAMES = 3
COOLDOWN_SEC = 2.5
RECORD_SEC = 3
CALIBRATE_SEC = 1.0
RMS_MARGIN = 2.5
DEVICE_INDEX = 2  # -1=預設輸入裝置；若你知道 index 可改數字

def list_devices_compat():
    """相容不同版本 pvrecorder 的裝置列舉。"""
    names = []
    # 方案1：class 靜態方法（有些版本有）
    try:
        names = PvRecorder.get_audio_devices()
        return names
    except Exception:
        pass
    # 方案2：模組層函式（有些版本只有這個）
    try:
        from pvrecorder import get_audio_devices  # type: ignore
        names = get_audio_devices()
        return names
    except Exception:
        pass
    # 方案3：取不到就回空清單（讓程式繼續跑）
    return []

def rms_int16(int_samples):
    s2 = sum(s*s for s in int_samples) / float(len(int_samples))
    return math.sqrt(s2)

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def main():
    if "YOUR_ACCESS_KEY_HERE" in ACCESS_KEY:
        print("⚠️ 請先填入 Porcupine ACCESS_KEY。")
        sys.exit(1)

    # Porcupine 偵測器
    porcupine = pvporcupine.create(
        access_key=ACCESS_KEY,
        keyword_paths=[KEYWORD_PATH],
        sensitivities=[SENSITIVITY],
    )

    # 裝置列舉（相容各版）
    names = list_devices_compat()
    if names:
        print("=== 可用輸入裝置 ===")
        for i, name in enumerate(names):
            print(f"[{i}] {name}")
    else:
        print("⚠️ 無法由 pvrecorder 取得裝置清單。將使用預設輸入裝置（device_index=-1）。")
        print("   你也可用 `arecord -l` 取得卡號，再設定 DEVICE_INDEX。")

    # 錄音器
    rec = PvRecorder(device_index=DEVICE_INDEX, frame_length=porcupine.frame_length)
    rec.start()

    try:
        print("🟢 噪音校正中...")
        calib_frames = int((porcupine.sample_rate / porcupine.frame_length) * CALIBRATE_SEC)
        rms_vals = []
        for _ in range(max(1, calib_frames)):
            pcm = rec.read()  # list[int]
            rms_vals.append(rms_int16(pcm))
        noise_mean = sum(rms_vals) / len(rms_vals)
        noise_var = sum((x - noise_mean) ** 2 for x in rms_vals) / max(1, len(rms_vals) - 1)
        noise_std = math.sqrt(noise_var) if noise_var > 0 else 1.0
        rms_gate = noise_mean + RMS_MARGIN * noise_std
        print(f"🧰 噪音均值={noise_mean:.1f}、Std={noise_std:.1f}、門檻={rms_gate:.1f}")
        print("🟢 等待喚醒詞...")

        consecutive_hits = 0
        last_trigger_ts = 0.0

        while True:
            pcm = rec.read()  # list[int16], 長度=frame_length

            # 先做能量門檻（降低底噪誤觸）
            if rms_int16(pcm) < rms_gate:
                consecutive_hits = 0
                continue

            is_hit = porcupine.process(pcm)
            consecutive_hits = consecutive_hits + 1 if is_hit else 0

            now_ts = time.time()
            if consecutive_hits >= CONFIRM_FRAMES and (now_ts - last_trigger_ts) >= COOLDOWN_SEC:
                last_trigger_ts = now_ts
                ts_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"\n✅ [{ts_str}] 喚醒詞偵測成功！開始錄音 {RECORD_SEC} 秒...")

                # 收集 RECORD_SEC 秒音訊
                frames = [pcm]
                total_more = int(porcupine.sample_rate / porcupine.frame_length * RECORD_SEC) - 1
                for _ in range(max(0, total_more)):
                    frames.append(rec.read())

                # 寫成 WAV
                out = f"wake_audio_{now_str()}.wav"
                with wave.open(out, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)  # int16
                    wf.setframerate(porcupine.sample_rate)
                    for block in frames:
                        wf.writeframes(struct.pack("<" + "h"*len(block), *block))

                print(f"💾 已儲存：{out}")
                consecutive_hits = 0
                time.sleep(COOLDOWN_SEC)

    except KeyboardInterrupt:
        print("\n🛑 偵測已中止（Ctrl+C）")
    finally:
        rec.stop()
        rec.delete()
        porcupine.delete()
        print("🔒 音訊資源已釋放，程式結束")

if __name__ == "__main__":
    main()
