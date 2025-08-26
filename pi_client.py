# -*- coding: utf-8 -*-
# Porcupine wake word -> TTS prompt -> record -> flush -> cooldown -> TTS standby -> back to standby -> upload to server
import os
import io
import sys
import time
import wave
import struct
import datetime
import tempfile
import asyncio
import audioop 

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
COOLDOWN_SEC = 0.5          # 冷卻秒數
FLUSH_MS     = 300          # flush 麥克風緩衝，避免回授觸發

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
def upload(frames, sample_rate):
    """將錄好的 frames 直接上傳伺服器，不存檔"""
    try:
        # ✅ 直接寫入記憶體 BytesIO
        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16
            wf.setframerate(sample_rate)
            for block in frames:
                wf.writeframes(struct.pack("<" + "h"*len(block), *block))
        wav_io.seek(0)  # 回到開頭

        # 上傳
        files = {"file": ("audio.wav", wav_io, "audio/wav")}
        print(f"[Client] 上傳錄音 → {SERVER_URL}")
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

            # 控制訊號
            music_url = resp.headers.get("X-Music-URL")
            if music_url:
                play_music_vlc(music_url)

            music_ctrl = resp.headers.get("X-Music-CTRL")
            if music_ctrl == "pause":
                pause_music()
            elif music_ctrl == "resume":
                resume_music()
            elif music_ctrl == "stop":
                stop_music()

            session_ctrl = resp.headers.get("X-Session")
            return session_ctrl
        else:
            print(f"[Client] 上傳失敗: status={resp.status_code}, text={resp.text}")
            return None
    except Exception as e:
        print(f"[Client] 上傳/播放失敗: {e}")
        return None

# --------- 錄音與流程 ---------
def record_until_silence(recorder, porcupine, first_frame,
                         silence_limit=1.2, frame_duration=20, max_duration=120):
    """
    錄音直到偵測到靜音，或達到 max_duration 秒
    - silence_limit: 靜音持續秒數判斷結束
    - frame_duration: 每幀的毫秒數
    - max_duration: 最大錄音長度 (秒) - 保險用
    """
    frames = [first_frame]
    silence_start = None
    max_frames = int((1000 / frame_duration) * max_duration)

    for i in range(max_frames):
        frame = recorder.read()
        frames.append(frame)

        # ✅ 把 list 轉成 bytes 再算音量
        frame_bytes = struct.pack("<" + "h"*len(frame), *frame)
        rms = audioop.rms(frame_bytes, 2)  # 16-bit frame
        if rms < 500:  # 靜音閾值，可調
            if silence_start is None:
                silence_start = time.time()
            elif time.time() - silence_start > silence_limit:
                print("[Client] 偵測到靜音，結束錄音")
                break
        else:
            silence_start = None
    else:
        # 🚨 超過最大錄音長度
        print("[Client] ⚠️ 錄音超過最大長度，可能有問題")
        tts_say_blocking("Famix錄音系統出現異常，請稍後再試")
        return None

    return frames   # ⬅️ 必須和 with 同層縮排

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
                print("[Recording] 開始錄音（靜音檢測中）…")
                first_frame = recorder.read()
                frames = record_until_silence(recorder, porcupine, first_frame)
                if frames:
                    session_ctrl = upload(frames, porcupine.sample_rate)
                
                    # ✅ 如果伺服器要求追問模式
                    while session_ctrl == "followup":
                        print("[Client] 伺服器要求追問模式，再次錄音")
                        first_frame = recorder.read()
                        frames = record_until_silence(recorder, porcupine, first_frame)
                        if frames:
                            session_ctrl = upload(frames, porcupine.sample_rate)
                        else:
                            break


                # 冷卻
                print(f"[Cooldown] {COOLDOWN_SEC}s …")
                time.sleep(COOLDOWN_SEC)

                # 待機播報 (避免和伺服器 idle 重複)
                if session_ctrl != "idle":  
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
