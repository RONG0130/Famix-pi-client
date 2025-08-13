# -*- coding: utf-8 -*-
import os
import pvporcupine
from pvrecorder import PvRecorder
import wave, time, datetime, math, struct, sys
from collections import deque

# 建議用環境變數傳 KEY： export PICOVOICE_ACCESS_KEY=xxxxx
ACCESS_KEY   = os.environ.get("PICOVOICE_ACCESS_KEY", "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw==")
KEYWORD_PATH = "/home/admin/Porcupine/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"

# ---- 觸發/抗雜訊參數（這組較容易觸發，若誤觸再微調）----
SENSITIVITY     = 0.55      # 0~1，越大越容易觸發
CONFIRM_FRAMES  = 3         # 去抖：需連續命中幾個 frame
COOLDOWN_SEC    = 2.0       # 觸發冷卻
RECORD_SEC      = 3
CALIBRATE_SEC   = 1.0
RMS_MARGIN      = 1.2       # 用於列印的門檻參考，不再擋 Porcupine
PRE_SILENCE_MS  = 150       # 觸發前需連續靜音多少毫秒
DEVICE_INDEX    = 2         # 依 arecord -l；你的 USB Mic 在卡2
DEBUG_PRINT_EVERY = 120     # 每 N 個 frame 列印一次 RMS（0=關閉）

def rms_int16(xs):
    # 計算 RMS（能量），xs 為 int16 list
    s2 = sum(x*x for x in xs) / float(len(xs))
    return math.sqrt(s2)

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def main():
    if not ACCESS_KEY or "YOUR_ACCESS_KEY_HERE" in ACCESS_KEY:
        print("⚠️ 請先填入 Porcupine ACCESS_KEY。"); sys.exit(1)

    # 1) 建立 Porcupine 偵測器
    porcupine = pvporcupine.create(
        access_key=ACCESS_KEY,
        keyword_paths=[KEYWORD_PATH],
        sensitivities=[SENSITIVITY],
    )

    # 2) 建立錄音器
    rec = PvRecorder(device_index=DEVICE_INDEX, frame_length=porcupine.frame_length)
    rec.start()

    try:
        # 3) 噪音校正（估計背景噪音均值/標準差）
        print("🟢 噪音校正中...")
        calib_frames = int((porcupine.sample_rate / porcupine.frame_length) * CALIBRATE_SEC)
        rms_vals = []
        for _ in range(max(1, calib_frames)):
            rms_vals.append(rms_int16(rec.read()))
        mean = sum(rms_vals)/len(rms_vals)
        var  = sum((x-mean)**2 for x in rms_vals)/max(1, len(rms_vals)-1)
        std  = math.sqrt(var) if var > 0 else 1.0

        # 參考門檻（僅列印用，不用來擋 Porcupine）
        rms_gate = mean + RMS_MARGIN * std

        # 用較寬鬆的門檻來判定「前置靜音」
        quiet_gate = mean + 0.6 * std

        print(f"🧰 噪音均值={mean:.1f}  Std={std:.1f}  參考門檻={rms_gate:.1f}  靜音判定≈{quiet_gate:.1f}")
        print("🟢 等待喚醒詞...")

        # 4) 前置靜音緩衝：最近 PRE_SILENCE_MS 是否完全安靜
        ms_per_frame = 1000.0 * porcupine.frame_length / porcupine.sample_rate
        buf_len = int(max(1, PRE_SILENCE_MS / ms_per_frame))
        recent_loud = deque([False]*buf_len, maxlen=buf_len)

        consecutive_hits = 0
        last_trigger_ts  = 0.0
        frame_counter    = 0

        while True:
            pcm = rec.read()           # list[int16], len=frame_length
            rms = rms_int16(pcm)
            frame_counter += 1

            # 更新「最近是否大聲」緩衝（用較低的 quiet_gate 判定）
            recent_loud.append(rms >= quiet_gate)

            # === Porcupine 每幀都要處理（不要被能量門檻擋住）===
            hit_idx = pvporcupine.Porcupine.process(porcupine, pcm)  # >=0 命中；-1 未命中

            # 若最近一段時間不夠安靜，則不算觸發（去掉「剛開口的爆發」）
            if any(recent_loud):
                consecutive_hits = 0
            else:
                if hit_idx >= 0:
                    consecutive_hits += 1
                else:
                    consecutive_hits = 0

            now_ts = time.time()
            if consecutive_hits >= CONFIRM_FRAMES and (now_ts - last_trigger_ts) >= COOLDOWN_SEC:
                last_trigger_ts = now_ts
                ts_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"\n✅ [{ts_str}] 喚醒詞偵測成功！開始錄音 {RECORD_SEC} 秒...")

                # 收集 RECORD_SEC 秒音訊（含當前這個 frame）
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

            # 可選：每隔一段時間印一次目前的 RMS 與判定門檻，方便調參
            if DEBUG_PRINT_EVERY and (frame_counter % DEBUG_PRINT_EVERY == 0):
                print(f"RMS≈{rms:.0f}  靜音門檻≈{quiet_gate:.0f}  參考門檻≈{rms_gate:.0f}")

    except KeyboardInterrupt:
        print("\n🛑 偵測已中止（Ctrl+C）")
    finally:
        rec.stop(); rec.delete(); porcupine.delete()
        print("🔒 音訊資源已釋放，程式結束")

if __name__ == "__main__":
    main()
