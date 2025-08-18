# -*- coding: utf-8 -*-
# Porcupine wake word -> TTS prompt -> record -> flush -> cooldown -> TTS standby -> back to standby -> upload to server
import os, sys, time, wave, struct, datetime, tempfile, asyncio, requests
import pvporcupine
from pvrecorder import PvRecorder
import pygame, edge_tts
from pydub import AudioSegment

# ========= config =========
ACCESS_KEY   = os.environ.get("PICOVOICE_ACCESS_KEY", "xxxx")  # 你的 Key
KEYWORD_PATH = "/home/admin/Porcupine/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"
DEVICE_INDEX = 2
SENSITIVITY  = 0.75
RECORD_SEC   = 3
COOLDOWN_SEC = 1.2
FLUSH_MS     = 300
OUT_DIR      = "./"

SERVER_BASE  = "http://192.168.0.18:5000"
AUDIO_API    = f"{SERVER_BASE}/api/audio"
MUSIC_API    = f"{SERVER_BASE}/api/music"
WEATHER_API  = f"{SERVER_BASE}/api/weather"

# TTS 設定
TTS_VOICE    = "zh-TW-YunJheNeural"
TTS_RATE     = "+5%"
TTS_HIT_TEXT = "你好，請問有什麼需要幫助的嗎？"
TTS_IDLE_TEXT= "Famix已進入待機模式"

def timestamp(): return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# --------- Edge-TTS ---------
async def _edge_tts_to_mp3(text, out_path, voice, rate):
    await edge_tts.Communicate(text=text, voice=voice, rate=rate).save(out_path)

def tts_say_blocking(text, voice=TTS_VOICE, rate=TTS_RATE):
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
        try: pygame.mixer.quit()
        except: pass
        try: os.remove(mp3_path)
        except: pass

# --------- 上傳/呼叫伺服器 ---------
def upload_audio(path):
    """上傳錄音給伺服器，伺服器回傳 mp3 回覆"""
    try:
        sound = AudioSegment.from_wav(path)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmpf:
            mp3_path = tmpf.name
            sound.export(mp3_path, format="mp3")
        with open(mp3_path, "rb") as f:
            resp = requests.post(AUDIO_API, files={"file": f})
        if resp.status_code == 200:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as replyf:
                replyf.write(resp.content)
                reply_path = replyf.name
            pygame.mixer.init()
            pygame.mixer.music.load(reply_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy(): time.sleep(0.05)
            pygame.mixer.quit()
        else:
            print(f"[Client] 音訊上傳失敗 {resp.status_code}: {resp.text}")
    except Exception as e: print(f"[Client] 音訊流程錯誤: {e}")

def request_music(song: str):
    """請伺服器播放音樂"""
    try:
        resp = requests.post(MUSIC_API, json={"song": song})
        print(f"[Client] 音樂請求 {song} → {resp.text}")
    except Exception as e: print(f"[Client] 音樂錯誤: {e}")

def request_weather(city: str = "Taipei"):
    """請伺服器回覆天氣"""
    try:
        resp = requests.get(WEATHER_API, params={"city": city})
        if resp.status_code == 200:
            tts_say_blocking(resp.text)
        else:
            print(f"[Client] 天氣失敗 {resp.status_code}")
    except Exception as e: print(f"[Client] 天氣錯誤: {e}")

# --------- 錄音與流程 ---------
def record_after_hit(recorder, porcupine, first_frame):
    frames = [first_frame]
    frames_needed = int(porcupine.sample_rate / porcupine.frame_length * RECORD_SEC) - 1
    for _ in range(max(0, frames_needed)): frames.append(recorder.read())
    out_path = os.path.join(OUT_DIR, f"wake_audio_{timestamp()}.wav")
    with wave.open(out_path, 'wb') as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(porcupine.sample_rate)
        for block in frames: wf.writeframes(struct.pack("<" + "h"*len(block), *block))
    return out_path

def flush_buffer(recorder, porcupine, ms):
    for _ in range(int(porcupine.sample_rate/porcupine.frame_length * (ms/1000.0))): _ = recorder.read()

def main():
    porcupine = pvporcupine.create(access_key=ACCESS_KEY, keyword_paths=[KEYWORD_PATH], sensitivities=[SENSITIVITY])
    recorder = PvRecorder(device_index=DEVICE_INDEX, frame_length=porcupine.frame_length); recorder.start()

    # 開始時先播報待機
    recorder.stop(); tts_say_blocking(TTS_IDLE_TEXT); recorder.start(); flush_buffer(recorder, porcupine, FLUSH_MS)

    try:
        while True:
            pcm = recorder.read()
            if porcupine.process(pcm) >= 0:
                recorder.stop(); tts_say_blocking(TTS_HIT_TEXT); recorder.start(); flush_buffer(recorder, porcupine, FLUSH_MS)
                first_frame = recorder.read()
                out_path = record_after_hit(recorder, porcupine, first_frame)
                upload_audio(out_path)   # 這裡伺服器可根據內容判斷 music / weather / chat

                time.sleep(COOLDOWN_SEC)
                recorder.stop(); tts_say_blocking(TTS_IDLE_TEXT); recorder.start(); flush_buffer(recorder, porcupine, FLUSH_MS)

    except KeyboardInterrupt: pass
    finally:
        recorder.stop(); recorder.delete(); porcupine.delete(); 
        try: pygame.mixer.quit()
        except: pass

if __name__ == "__main__": main()
