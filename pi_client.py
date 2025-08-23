# -*- coding: utf-8 -*-
# Porcupine wake word -> TTS prompt -> record -> flush -> cooldown -> TTS standby -> back to standby -> upload to server
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

# === 播放 TTS：edge_tts + pygame ===
import pygame
import edge_tts
import subprocess
# === 上傳用 ===
import requests
from pydub import AudioSegment


# ========= config =========
ACCESS_KEY   = os.environ.get("PICOVOICE_ACCESS_KEY", "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw==")
KEYWORD_PATH = "/home/admin/Porcupine/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"
DEVICE_INDEX = 2            # 改成你的 USB Mic index
SENSITIVITY  = 0.75
RECORD_SEC   = 3            # 錄音長度
COOLDOWN_SEC = 1.2          # 冷卻秒數
FLUSH_MS     = 300          # flush 麥克風緩衝，避免回授觸發
OUT_DIR      = "./"         # 錄音檔輸出資料夾

SERVER_URL   = "http://192.168.0.18:5000/api/audio"

# TTS 設定
TTS_VOICE    = "zh-TW-YunJheNeural"
TTS_RATE     = "+5%"
TTS_HIT_TEXT = "你好，請問有什麼需要幫助的嗎？"
TTS_IDLE_TEXT= "Famix已進入待機模式"

def timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# --------- Edge-TTS 播放 ---------
async def _edge_tts_to_mp3(text: str, out_path: str, voice: str, rate: str):
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(out_path)

def tts_say_blocking(text: str, voice: str = TTS_VOICE, rate: str = TTS_RATE):
    """產生並播放一段 TTS 語音（同步阻塞直到播完）"""
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
# ----------play_vlc-------------
import vlc

vlc_instance = vlc.Instance()
player = None

def play_music_vlc(url: str):
    """播放 YouTube 音樂串流"""
    global player
    try:
        # 如果已有播放，先停止
        if player and player.is_playing():
            player.stop()

        media = vlc_instance.media_new(url)
        player = vlc_instance.media_player_new()
        player.set_media(media)
        player.play()
        print(f"[Client] 🎵 播放音樂: {url}")
    except Exception as e:
        print(f"[Client] 播放音樂失敗: {e}")

def pause_music():
    """暫停音樂"""
    global player
    if player and player.is_playing():
        player.pause()
        print("[Client] ⏸ 暫停音樂")

def resume_music():
    """繼續音樂"""
    global player
    if player and not player.is_playing():
        player.pause()  # VLC 的 pause() 是 toggle，非播放狀態下呼叫即繼續
        print("[Client] ▶️ 繼續音樂")

def stop_music():
    """停止音樂"""
    global player
    if player:
        player.stop()
        print("[Client] ⏹ 停止音樂")


# --------- 上傳到伺服器 ---------
def upload(path: str):
    """將錄好的 WAV 上傳伺服器，接收回覆 MP3 並播放"""
    try:
        # 轉 mp3
        sound = AudioSegment.from_wav(path)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmpf:
            mp3_path = tmpf.name
            sound.export(mp3_path, format="mp3")

        # 上傳
        with open(mp3_path, "rb") as f:
            files = {"file": f}
            print(f"[Client] 上傳 {mp3_path} → {SERVER_URL}")
            resp = requests.post(SERVER_URL, files=files)

        if resp.status_code == 200:
            print("[Client] 收到伺服器回覆 MP3，開始播放…")
            # 存回覆 mp3
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as replyf:
                reply_path = replyf.name
                replyf.write(resp.content)

            # 播放伺服器回覆
            pygame.mixer.init()
            pygame.mixer.music.load(reply_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            pygame.mixer.quit()

            # 如果有音樂 URL，就在 Pi 播放
            music_url = resp.headers.get("X-Music-URL")
            if music_url:
                play_music_vlc(music_url)

            # 如果有控制指令
            music_ctrl = resp.headers.get("X-Music-CTRL")
            if music_ctrl == "pause":
                pause_music()
            elif music_ctrl == "resume":
                resume_music()
            elif music_ctrl == "stop":
                stop_music()
        else:
            print(f"[Client] 上傳失敗: status={resp.status_code}, text={resp.text}")
    except Exception as e:
        print(f"[Client] 上傳/播放失敗: {e}")

# --------- 錄音與流程 ---------
def record_after_hit(recorder, porcupine, first_frame):
    """偵測到後，從 first_frame 開始錄 RECORD_SEC 秒並回傳檔名"""
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

    # 啟動時播報待機語
    try:
        recorder.stop()
        tts_say_blocking(TTS_IDLE_TEXT)
    finally:
        recorder.start()
        flush_buffer(recorder, porcupine, FLUSH_MS)

    print("[Standby] 等待喚醒詞…（Ctrl+C 結束）")

    try:
        while True:
            pcm = recorder.read()
            result = porcupine.process(pcm)
            if result >= 0:
                print("[Hit] 偵測到喚醒詞")
            
                # 🚨 自動暫停音樂，避免干擾錄音
                try:
                    if player and player.is_playing():
                        pause_music()
                except Exception as e:
                    print(f"[Client] 音樂暫停失敗: {e}")
            
                recorder.stop()
                tts_say_blocking(TTS_HIT_TEXT)
                recorder.start()
                flush_buffer(recorder, porcupine, FLUSH_MS)

                # 錄音
                print(f"[Recording] {RECORD_SEC} 秒…")
                first_frame = recorder.read()
                out_path = record_after_hit(recorder, porcupine, first_frame)
                print(f"[Saved] {out_path}")

                # 上傳給伺服器
                upload(out_path)

                # 冷卻
                print(f"[Cooldown] {COOLDOWN_SEC}s …")
                time.sleep(COOLDOWN_SEC)

                # 待機播報
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
