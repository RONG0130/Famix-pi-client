# -*- coding: utf-8 -*-
# Porcupine wake word -> TTS prompt -> record -> flush -> cooldown -> TTS standby -> back to standby -> upload to server
import os, sys, time, wave, struct, datetime, tempfile, asyncio, requests
import pvporcupine
from pvrecorder import PvRecorder
import pygame, edge_tts
from pydub import AudioSegment

# ========= config =========
ACCESS_KEY   = os.environ.get("PICOVOICE_ACCESS_KEY", "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw==")
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

def timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# --------- Edge-TTS 播放 ---------
async def _edge_tts_to_mp3(text: str, out_path: str, voice: str, rate: str):
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(out_path)

def tts_say_blocking(text: str, voice: str = TTS_VOICE, rate: str = TTS_RATE):
    """產生並播放一段 TTS 語音（轉成乾淨 MP3 再播放）"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
        raw_mp3 = fp.name
    try:
        # 先存 edge-tts 輸出的原始 mp3
        asyncio.run(_edge_tts_to_mp3(text, raw_mp3, voice, rate))

        # 用 pydub 重新轉一份乾淨的 CBR mp3
        sound = AudioSegment.from_file(raw_mp3, format="mp3")
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as clean_fp:
            clean_mp3 = clean_fp.name
            sound.export(clean_mp3, format="mp3", bitrate="128k")  # 強制轉成 CBR 128k

        # 播放
        pygame.mixer.init()
        pygame.mixer.music.load(clean_mp3)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)

    finally:
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except: pass
        for f in [raw_mp3, clean_mp3]:
            try: os.remove(f)
            except: pass


# --------- 上傳到伺服器 ---------
def upload(path: str):
    """將錄好的 WAV 上傳伺服器，接收回覆 MP3 並播放"""
    try:
        sound = AudioSegment.from_wav(path)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmpf:
            mp3_path = tmpf.name
            sound.export(mp3_path, format="mp3")

        with open(mp3_path, "rb") as f:
            files = {"file": f}
            print(f"[Client] 上傳 {mp3_path} → {AUDIO_API}")
            resp = requests.post(AUDIO_API, files=files)

        if resp.status_code == 200:
            print("[Client] 收到伺服器回覆 MP3，開始播放…")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as replyf:
                reply_path = replyf.name
                replyf.write(resp.content)

            pygame.mixer.init()
            pygame.mixer.music.load(reply_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy(): time.sleep(0.05)
            pygame.mixer.quit()
        else:
            print(f"[Client] 上傳失敗: status={resp.status_code}, text={resp.text}")
    except Exception as e:
        print(f"[Client] 上傳/播放失敗: {e}")

# --------- 新功能：音樂與天氣 ---------
def request_music(song: str):
    try:
        resp = requests.post(MUSIC_API, json={"song": song})
        print(f"[Client] 音樂請求 {song} → {resp.text}")
    except Exception as e:
        print(f"[Client] 音樂錯誤: {e}")

def request_weather(city: str = "Taipei"):
    try:
        resp = requests.get(WEATHER_API, params={"city": city})
        if resp.status_code == 200:
            tts_say_blocking(resp.text)
        else:
            print(f"[Client] 天氣失敗 {resp.status_code}")
    except Exception as e:
        print(f"[Client] 天氣錯誤: {e}")

# --------- 錄音與流程 ---------
def record_after_hit(recorder, porcupine, first_frame):
    frames = [first_frame]
    frames_needed = int(porcupine.sample_rate / porcupine.frame_length * RECORD_SEC) - 1
    for _ in range(max(0, frames_needed)):
        frames.append(recorder.read())

    out_path = os.path.join(OUT_DIR, f"wake_audio_{timestamp()}.wav")
    with wave.open(out_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(porcupine.sample_rate)
        for block in frames:
            wf.writeframes(struct.pack("<" + "h"*len(block), *block))
    return out_path

def flush_buffer(recorder, porcupine, ms: int):
    frames_to_drop = int(porcupine.sample_rate / porcupine.frame_length * (ms / 1000.0))
    for _ in range(max(0, frames_to_drop)): _ = recorder.read()

def main():
    if not ACCESS_KEY or "YOUR_ACCESS_KEY_HERE" in ACCESS_KEY:
        print("⚠️ 請先填入 Porcupine ACCESS_KEY（建議用環境變數 PICOVOICE_ACCESS_KEY）。")
        sys.exit(1)
    os.makedirs(OUT_DIR, exist_ok=True)

    porcupine = pvporcupine.create(access_key=ACCESS_KEY, keyword_paths=[KEYWORD_PATH], sensitivities=[SENSITIVITY])
    recorder = PvRecorder(device_index=DEVICE_INDEX, frame_length=porcupine.frame_length)
    recorder.start()

    try:
        recorder.stop(); tts_say_blocking(TTS_IDLE_TEXT)
    finally:
        recorder.start(); flush_buffer(recorder, porcupine, FLUSH_MS)

    print("[Standby] 等待喚醒詞…（Ctrl+C 結束）")

    try:
        while True:
            pcm = recorder.read()
            result = porcupine.process(pcm)
            if result >= 0:
                print("[Hit] 偵測到喚醒詞")
                recorder.stop(); tts_say_blocking(TTS_HIT_TEXT)
                recorder.start(); flush_buffer(recorder, porcupine, FLUSH_MS)

                print(f"[Recording] {RECORD_SEC} 秒…")
                first_frame = recorder.read()
                out_path = record_after_hit(recorder, porcupine, first_frame)
                print(f"[Saved] {out_path}")

                # ---- 上傳給伺服器（伺服器判斷 chat/music/weather） ----
                upload(out_path)

                print(f"[Cooldown] {COOLDOWN_SEC}s …")
                time.sleep(COOLDOWN_SEC)

                recorder.stop(); tts_say_blocking(TTS_IDLE_TEXT)
                recorder.start(); flush_buffer(recorder, porcupine, FLUSH_MS)
                print("[Standby] 回到待機，繼續偵測…")

    except KeyboardInterrupt:
        print("\n[Exit] 結束")
    finally:
        try: recorder.stop(); recorder.delete()
        finally: porcupine.delete()
        try: pygame.mixer.quit()
        except: pass

if __name__ == "__main__":
    main()
