import pvporcupine
from pvrecorder import PvRecorder  # pip install pvrecorder
import wave
import time
import datetime
import math

ACCESS_KEY = "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw=="
KEYWORD_PATH = "/home/admin/Porcupine/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"

SENSITIVITY = 0.25
CONFIRM_FRAMES = 3
COOLDOWN_SEC = 2.5
RECORD_SEC = 3
CALIBRATE_SEC = 1.0
RMS_MARGIN = 2.5
DEVICE_INDEX = -1   # -1 表示預設；用 PvRecorder.get_audio_devices() 列出名稱後自行選擇

def rms_int16(int_samples):
    s2 = sum(s*s for s in int_samples) / float(len(int_samples))
    return math.sqrt(s2)

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def main():
    print("=== 可用輸入裝置 ===")
    for i, name in enumerate(PvRecorder.get_audio_devices()):
        print(f"[{i}] {name}")

    porcupine = pvporcupine.create(
        access_key=ACCESS_KEY,
        keyword_paths=[KEYWORD_PATH],
        sensitivities=[SENSITIVITY],
    )

    rec = PvRecorder(device_index=DEVICE_INDEX, frame_length=porcupine.frame_length)
    rec.start()

    try:
        print("🟢 噪音校正中...")
        calib_frames = int((porcupine.sample_rate / porcupine.frame_length) * CALIBRATE_SEC)
        rms_vals = []
        for _ in range(max(1, calib_frames)):
            pcm = rec.read()  # list[int16]
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
            pcm = rec.read()  # list of int16, 長度=frame_length
            # 先能量門檻
            if rms_int16(pcm) < rms_gate:
                consecutive_hits = 0
                continue

            is_hit = porcupine.process(pcm)
            if is_hit:
                consecutive_hits += 1
            else:
                consecutive_hits = 0

            now_ts = time.time()
            if consecutive_hits >= CONFIRM_FRAMES and (now_ts - last_trigger_ts) >= COOLDOWN_SEC:
                last_trigger_ts = now_ts
                ts_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"\n✅ [{ts_str}] 喚醒詞偵測成功！開始錄音 {RECORD_SEC} 秒...")

                frames = [bytes(bytearray(int(x & 0xFF) for x in pcm))]  # 先占位，下面會用 wave 正確寫入
                # 用 wave 正規寫法
                audio_file = f"wake_audio_{now_str()}.wav"
                with wave.open(audio_file, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)  # int16
                    wf.setframerate(porcupine.sample_rate)
                    # 已有第一個 frame -> 重新寫入更正確的 bytes
                    wf.writeframes(b"")  # 先空寫，下面補足所有 frames

                    # 把剛剛觸發的 frame 也寫入（轉 bytes）
                    import struct
                    wf.writeframes(struct.pack("<" + "h"*len(pcm), *pcm))

                    total_more = int(porcupine.sample_rate / porcupine.frame_length * RECORD_SEC) - 1
                    for _ in range(max(0, total_more)):
                        pcm2 = rec.read()
                        wf.writeframes(struct.pack("<" + "h"*len(pcm2), *pcm2))

                print(f"💾 已儲存：{audio_file}")
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

