# -*- coding: utf-8 -*-
# Porcupine wake word -> TTS prompt -> record -> flush -> cooldown -> TTS standby -> back to standby
import os
import sys
import time
import wave
import struct
import datetime
import tempfile
import asyncio

import pvporcupine
from pvrecorder import PvRecorder

# === TTS 播放：edge_tts + pygame ===
import pygame
import edge_tts

# ========= config =========
ACCESS_KEY   = os.environ.get("PICOVOICE_ACCESS_KEY", "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw==")
KEYWORD_PATH = "/home/admin/Porcupine/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"
DEVICE_INDEX = 2            # 改成你的 USB Mic index
SENSITIVITY  = 0.75         # 0~1 越大越敏感；成功後可微調
RECORD_SEC   = 3            # 偵測到後錄音秒數（使用者回答時間）
COOLDOWN_SEC = 1.2          # 錄完後冷卻，避免連續觸發
FLUSH_MS     = 300          # 播放/錄完後丟掉這麼長的殘留緩衝（避免尾音回觸發）
OUT_DIR      = "./"         # 錄音輸出資料夾

# TTS 設定
TTS_VOICE    = "zh-TW-YunJheNeural"
TTS_RATE     = "+5%"        # 語速
TTS_HIT_TEXT = "你好，請問有什麼需要幫助的嗎？"
TTS_IDLE_TEXT= "Famix已進入待機模式"

def timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

async def _edge_tts_to_mp3(text: str, out_path: str, voice: str, rate: str):
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(out_path)

def tts_say_blocking(text: str, voice: str = TTS_VOICE, rate: str = TTS_RATE):
    """
    同步播放一段 TTS。使用 edge_tts 生成 MP3，pygame 播放（阻塞至播放完畢）。
    """
    # 生成臨時 mp3
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
        mp3_path = fp.name

    try:
        asyncio.run(_edge_tts_to_mp3(text, mp3_path, voice, rate))
        pygame.mixer.init()
        pygame.mixer.music.load(mp3_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
    finally:
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            pass
        try:
            os.remove(mp3_path)
        except Exception:
            pass

def upload(path: str):
    """錄完要上傳就實作這裡。
    例：
        import requests
        with open(path, 'rb') as f:
            requests.post('http://server/upload', files={'file': ('file.wav', f, 'audio/wav')})
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
    if not ACCESS_KEY or "YOUR_ACCESS_KEY_HERE" in ACCESS_KEY:
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

    # 啟動時播報一次待機語
    try:
        recorder.stop()
        tts_say_blocking(TTS_IDLE_TEXT)
    finally:
        recorder.start()
        flush_buffer(recorder, porcupine, FLUSH_MS)

    print("[Standby] 等待喚醒詞…（Ctrl+C 結束）")

    try:
        while True:
            pcm = recorder.read()            # list[int16]
            result = porcupine.process(pcm)  # >=0 命中；-1 未命中
            if result >= 0:
                print("[Hit] 偵測到喚醒詞")
                # 停止收音，先說打招呼以免把 TTS 錄進去
                recorder.stop()
                tts_say_blocking(TTS_HIT_TEXT)
                # 播放後重新開始收音並 flush 一下緩衝
                recorder.start()
                flush_buffer(recorder, porcupine, FLUSH_MS)

                # 開始錄使用者的語音
                print(f"[Recording] {RECORD_SEC} 秒…")
                # 立刻讀一個 frame 當 first_frame（剛啟動時麥克風新鮮資料）
                first_frame = recorder.read()
                out_path = record_after_hit(recorder, porcupine, first_frame)
                print(f"[Saved] {out_path}")

                # (可選) 上傳
                upload(out_path)

                # 冷卻避免連續觸發
                print(f"[Cooldown] {COOLDOWN_SEC}s …")
                time.sleep(COOLDOWN_SEC)

                # 回到待機並播報
                recorder.stop()
                tts_say_blocking(TTS_IDLE_TEXT)
                recorder.start()
                flush_buffer(recorder, porcupine, FLUSH_MS)

                print("[Standby] 回到待機，繼續偵測…")

    except KeyboardInterrupt:
        print("\n[Exit] 結束")
    finally:
        try:
            recorder.stop()
            recorder.delete()
        finally:
            porcupine.delete()
        try:
            pygame.mixer.quit()
        except Exception:
            pass

if __name__ == "__main__":
    main()
