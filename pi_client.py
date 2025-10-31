# -*- coding: utf-8 -*-
import os
import io
import cv2
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
# === 上傳用 ===
import requests
from pydub import AudioSegment

# === VLC 音樂播放 ===
import vlc
#------------------------
import subprocess

def start_rtsp_stream():
    cmd = [
        "v4l2rtspserver",
        "-W", "720", "-H", "480", "-F", "30",
        "/dev/video0"
    ]
    return subprocess.Popen(cmd)


# ========= config =========
ACCESS_KEY   = os.environ.get("PICOVOICE_ACCESS_KEY", "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw==")
KEYWORD_PATH = "/home/admin/Porcupine/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"
DEVICE_INDEX = 2
SENSITIVITY  = 0.75
COOLDOWN_SEC = 0.5
FLUSH_MS     = 300

SERVER_URL   = "http://10.114.195.154:5000/api/audio"
SERVER_FACE  = "http://10.114.195.154:5000/api/face_recog"
SERVER_MSG   = "http://10.114.195.154:5000/api/message"

# TTS 設定
TTS_VOICE    = "zh-TW-YunJheNeural"
TTS_RATE     = "+5%"
TTS_HIT_TEXT = "你好，請問有什麼需要幫助的嗎？"
TTS_IDLE_TEXT= "Famix已進入待機模式"
is_playing_tts = False   # ✅ 播放 TTS 時暫停錄音

def capture_and_upload_face():
    """從 RTSP 串流擷取一張影像並上傳到 server"""
    RTSP_URL = "rtsp://127.0.0.1:8554/unicast"  # Pi 本機的串流來源
    cap = cv2.VideoCapture(RTSP_URL)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        print("[Client] ❌ 無法從 RTSP 取得影像")
        return None

    tmp_path = f"/tmp/face_{timestamp()}.jpg"
    cv2.imwrite(tmp_path, frame)

    try:
        with open(tmp_path, "rb") as f:
            files = {"file": (os.path.basename(tmp_path), f, "image/jpeg")}
            resp = requests.post(SERVER_FACE, files=files, timeout=10)

        print(f"[Client] Server 回覆狀態碼: {resp.status_code}")
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"[Client] 上傳失敗: {resp.text}")
            return None
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def record_message_and_upload(name, recorder, porcupine):
    """錄留言並送到 server"""
    print(f"[Client] 🎤 開始錄 {name} 的留言…")
    first_frame = recorder.read()
    frames = record_until_silence(recorder, porcupine, first_frame,
                                  silence_limit=2.0, max_duration=180)
    if not frames:
        return

    wav_io = io.BytesIO()
    with wave.open(wav_io, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(porcupine.sample_rate)
        for block in frames:
            wf.writeframes(struct.pack("<" + "h"*len(block), *block))
    wav_io.seek(0)

    files = {"file": (f"voice_{name}.wav", wav_io, "audio/wav")}
    data = {"name": name}
    resp = requests.post(SERVER_MSG, files=files, data=data)
    print(f"[Client] 上傳留言結果: {resp.json()}")

def timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


# --------- Edge-TTS 播放 ---------
async def _edge_tts_to_mp3(text: str, out_path: str, voice: str, rate: str):
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(out_path)

def tts_say_blocking(text: str, voice: str = TTS_VOICE, rate: str = TTS_RATE):
    global is_playing_tts
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as fp:
        mp3_path = fp.name
    try:
        asyncio.run(_edge_tts_to_mp3(text, mp3_path, voice, rate))
        pygame.mixer.init()
        pygame.mixer.music.load(mp3_path)

        is_playing_tts = True
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)

    finally:
        is_playing_tts = False
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            pass
        try:
            os.remove(mp3_path)
        except Exception:
            pass


# ---------- VLC 音樂控制 -------------
vlc_instance = vlc.Instance()
player = None

def play_music_vlc(url: str):
    global player
    try:
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
    global player
    if player and player.is_playing():
        player.pause()
        print("[Client] ⏸ 暫停音樂")

def resume_music():
    global player
    if player and player.get_state() == vlc.State.Paused:
        player.pause()  # toggle
        print("[Client] ▶️ 繼續音樂")

def stop_music():
    global player
    if player:
        player.stop()
        print("[Client] ⏹ 停止音樂")


# --------- 上傳到伺服器 ---------
def upload(frames, sample_rate):
    global is_playing_tts
    try:
        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            for block in frames:
                wf.writeframes(struct.pack("<" + "h"*len(block), *block))
        wav_io.seek(0)

        files = {"file": ("audio.wav", wav_io, "audio/wav")}
        print(f"[Client] 上傳錄音 → {SERVER_URL}")
        resp = requests.post(SERVER_URL, files=files)

        if resp.status_code == 200:
            print("[Client] 收到伺服器回覆 MP3，開始播放…")

            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as replyf:
                reply_path = replyf.name
                replyf.write(resp.content)

            pygame.mixer.init()
            is_playing_tts = True
            pygame.mixer.music.load(reply_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)
            pygame.mixer.quit()
            is_playing_tts = False

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

            return resp.headers.get("X-Session")
        else:
            print(f"[Client] 上傳失敗: status={resp.status_code}, text={resp.text}")
            return None
    except Exception as e:
        print(f"[Client] 上傳/播放失敗: {e}")
        is_playing_tts = False
        return None


# --------- 錄音與流程 ---------
def record_until_silence(recorder, porcupine, first_frame,
                         silence_limit=1.2, frame_duration=20, max_duration=120):
    """
    改版：固定錄 6 秒，不再使用靜音偵測。
    """
    frames = [first_frame]
    duration = 6  # 錄音長度（秒）
    sample_rate = 16000  # PvRecorder 輸出取樣率
    total_frames = int(sample_rate / (512 / (sample_rate / 1000)) * duration / 1000)

    print(f"[Client] 🎙️ 固定錄音 {duration} 秒中...")
    start_time = time.time()

    for _ in range(int(duration * (1000 / frame_duration))):
        frame = recorder.read()
        frames.append(frame)
        if time.time() - start_time > duration:
            break

    print("[Client] ⏹ 錄音結束")
    return frames if len(frames) > 5 else None

def flush_buffer(recorder, porcupine, ms: int):
    frames_to_drop = int((ms / 1000.0) * (porcupine.sample_rate / porcupine.frame_length))
    for _ in range(max(0, frames_to_drop)):
        _ = recorder.read()


# --------- 主程式 ---------
def main():
    if not ACCESS_KEY or "YOUR_ACCESS_KEY_HERE" in ACCESS_KEY:
        print("⚠️ 請先填入 Porcupine ACCESS_KEY")
        sys.exit(1)

    porcupine = pvporcupine.create(
        access_key=ACCESS_KEY,
        keyword_paths=[KEYWORD_PATH],
        sensitivities=[SENSITIVITY]
    )
    recorder = PvRecorder(device_index=DEVICE_INDEX, frame_length=porcupine.frame_length)
    recorder.start()

    try:
        recorder.stop()
        tts_say_blocking(TTS_IDLE_TEXT)
    finally:
        recorder.start()
        flush_buffer(recorder, porcupine, FLUSH_MS)

    print("[Standby] 等待喚醒詞…（Ctrl+C 結束）")

    try:
        while True:
            if is_playing_tts:
                time.sleep(0.1)
                continue

            pcm = recorder.read()
            result = porcupine.process(pcm)
            if result >= 0:
                print("[Hit] 偵測到喚醒詞")

                try:
                    if player and player.is_playing():
                        pause_music()
                except Exception as e:
                    print(f"[Client] 音樂暫停失敗: {e}")

                recorder.stop()
                tts_say_blocking(TTS_HIT_TEXT)
                recorder.start()
                flush_buffer(recorder, porcupine, FLUSH_MS)

                print("[Recording] 開始錄音…")
                first_frame = recorder.read()
                frames = record_until_silence(recorder, porcupine, first_frame)
                if frames:
                    session_ctrl = upload(frames, porcupine.sample_rate)
                    # 檢查是否進入留言模式
                    if session_ctrl == "leave_message":
                        face_data = capture_and_upload_face()
                        if face_data and face_data.get("status") == "ok":
                            name = face_data.get("name", "unknown")
                            tts_say_blocking(f"{name}你好，請開始留言")
                            record_message_and_upload(name, recorder, porcupine)
                        else:
                            tts_say_blocking("抱歉，無法確認人臉，留言取消")
                        session_ctrl = "idle"
                else:
                    session_ctrl = None

                while session_ctrl == "followup":
                    print("[Client] 伺服器要求追問模式，再次錄音")
                    first_frame = recorder.read()
                    frames = record_until_silence(recorder, porcupine, first_frame)
                    if frames:
                        session_ctrl = upload(frames, porcupine.sample_rate)
                    else:
                        break

                print(f"[Cooldown] {COOLDOWN_SEC}s …")
                time.sleep(COOLDOWN_SEC)

                if session_ctrl != "shutdown":
                    recorder.stop()
                    tts_say_blocking(TTS_IDLE_TEXT)
                    recorder.start()
                    flush_buffer(recorder, porcupine, FLUSH_MS)
                print("[Standby] 回到待機…")

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

from flask import Flask, request, jsonify
import threading

PI_SERVER = Flask(__name__)

@PI_SERVER.route("/api/say", methods=["POST"])
def api_say():
    data = request.get_json()
    text = data.get("text", "")
    if not text:
        return jsonify({"status": "error", "msg": "缺少 text"}), 400

    print(f"[Pi] ▶️ 播報中：{text}")
    try:
        # ✅ 直接阻塞式播放（edge-tts 完成後才回傳）
        tts_say_blocking(text)
        print("[Pi] ✅ 播放完成")
        return jsonify({"status": "ok", "msg": "播放完成"})
    except Exception as e:
        print(f"[Pi] ❌ 播放失敗：{e}")
        return jsonify({"status": "error", "msg": str(e)}), 500


@PI_SERVER.route("/api/record", methods=["POST"])
def api_record():
    """錄音一段音訊後，送回伺服器 /api/fall_reply 判斷"""
    print("[Pi] /api/record 啟動錄音...")
    recorder = PvRecorder(device_index=DEVICE_INDEX, frame_length=512)
    recorder.start()
    try:
        first_frame = recorder.read()
        frames = record_until_silence(recorder, None, first_frame,
                                      silence_limit=2.0, max_duration=10)
        if not frames:
            print("[Pi] ❌ 錄音失敗或靜音")
            return jsonify({"status": "unknown"})

        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            for block in frames:
                wf.writeframes(struct.pack("<" + "h"*len(block), *block))
        wav_io.seek(0)

        files = {"file": ("reply.wav", wav_io, "audio/wav")}
        resp = requests.post("http://10.114.195.154:5000/api/fall_reply", files=files, timeout=60)
        if resp.status_code == 200:
            jr = resp.json()
            print("[Pi] ✅ 收到伺服器辨識結果:", jr)
            return jsonify(jr)
        else:
            print("[Pi] ⚠️ 上傳失敗:", resp.status_code, resp.text)
            return jsonify({"status": "error", "msg": resp.text}), 500
    except Exception as e:
        print("[Pi] record error:", e)
        return jsonify({"status": "error", "msg": str(e)})
    finally:
        recorder.stop()
        recorder.delete()

def run_flask():
    PI_SERVER.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    rtsp_proc = start_rtsp_stream()
    try:
        threading.Thread(target=run_flask, daemon=True).start()
        main()
    finally:
        if rtsp_proc:
            rtsp_proc.terminate()
            rtsp_proc.wait()
            print("[RTSP] 已關閉串流服務")
