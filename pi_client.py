# -*- coding: utf-8 -*-
import pvporcupine
from pvrecorder import PvRecorder
import wave, time, datetime, math, struct, sys
from collections import deque

ACCESS_KEY   = "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw=="  # ⚠️ 建議改成用環境變數
KEYWORD_PATH = "/home/admin/Porcupine/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"

# ---- 更保守的預設（降低誤觸）----
SENSITIVITY     = 0.18      # 原本 0.25 -> 降低靈敏度
CONFIRM_FRAMES  = 4         # 原本 3 -> 需連續命中 4 個 frame
COOLDOWN_SEC    = 2.5
RECORD_SEC      = 3
CALIBRATE_SEC   = 1.0
RMS_MARGIN      = 3.2       # 原本 2.5 -> 拉高能量門檻
PRE_SILENCE_MS  = 300       # 觸發前需連續靜音 300ms
DEVICE_INDEX    = 2         # 依 arecord -l；你的 USB Mic 在卡2

def rms_int16(xs):
    # 計算 RMS（能量），xs 為 int16 list
    s2 = sum(x*x for x in xs) / float(len(xs))
    return math.sqrt(s2)

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

def main():
    if not ACCESS_KEY or "YOUR_ACCESS_KEY_HERE" in ACCESS_KEY:
        print("⚠️ 請先填入 Porcupine ACCESS_KEY。"); sys.exit(1)

    # 建立 Porcupine 偵測器
    porcupine = pvporcupine.create(
        access_key=ACCESS_KEY,
        keyword_paths=[KEYWORD_PATH],
        sensitivities=[SENSITIVITY],
    )

    # 建立錄音器
    rec = PvRecorder(device_index=DEVICE_INDEX, frame_length=porcupine.frame_length)
    rec.start()

    try:
        # --- 啟動時做短暫噪音校正，得到能量門檻 ---
        print("🟢 噪音校正中...")
        calib_frames = int((porcupine.sample_rate / porcupine.frame_length) * CALIBRATE_SEC)
        rms_vals = []
        for _ in range(max(1, calib_frames)):
            rms_vals.append(rms_int16(rec.read()))
        mean = sum(rms_vals)/len(rms_vals)
        var  = sum((x-mean)**2 for x in rms_vals)/max(1, len(rms_vals)-1)
        std  = math.sqrt(var) if var > 0 else 1.0
        rms_gate = mean + RMS_MARGIN * std
        print(f"🧰 噪音均值={mean:.1f} Std={std:.1f} 門檻={rms_gate:.1f}")
        print("🟢 等待喚醒詞...")

        # --- 前置靜音緩衝：最近 PRE_SILENCE_MS 是否完全安靜 ---
        ms_per_frame = 1000.0 * porcupine.frame_length / porcupine.sample_rate
        buf_len = int(max(1, PRE_SILENCE_MS / ms_per_frame))
        recent_loud = deque([False]*buf_len, maxlen=buf_len)

        consecutive_hits = 0
        last_trigger_ts = 0.0

        while True:
            pcm = rec.read()           # list[int16], len=frame_length
            rms = rms_int16(pcm)

            # 更新最近是否大聲（>= 門檻）
            recent_loud.append(rms >= rms_gate)

            # 能量低於門檻：不送入 porcupine，也清空去抖動
            if rms < rms_gate:
                consecutive_hits = 0
                continue

            # 沒有前置靜音就不允許觸發（剛開口爆發的能量會被擋下）
            if any(recent_loud):
                consecutive_hits = 0
                continue

            # === 核心：正確判斷 Porcupine 回傳值 ===
            hit_idx = porcupine.process(pcm)   # >=0: 命中該關鍵詞；-1: 未命中
            if hit_idx >= 0:
                consecutive_hits += 1
            else:
                consecutive_hits = 0

            # 去抖 + 冷卻後才算真正觸發
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

    except KeyboardInterrupt:
        print("\n🛑 偵測已中止（Ctrl+C）")
    finally:
        rec.stop(); rec.delete(); porcupine.delete()
        print("🔒 音訊資源已釋放，程式結束")

if __name__ == "__main__":
    main()
