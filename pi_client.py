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
import math
import numpy as np
import threading
import requests
import pygame
import edge_tts
import vlc
import pvporcupine
from pvrecorder import PvRecorder
from ultralytics import YOLO
from datetime import datetime
import speech_recognition as sr
from flask import Flask, request, jsonify
# === 上傳用 ===
from pydub import AudioSegment



# ========= config =========
ACCESS_KEY   = os.environ.get("PICOVOICE_ACCESS_KEY", "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw==")
KEYWORD_PATH = "/home/admin/Porcupine/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"
DEVICE_INDEX = 2
SENSITIVITY  = 0.75
COOLDOWN_SEC = 0.5
FLUSH_MS     = 300


SERVER_URL   = "http://10.23.222.154:5000/api/audio"
SERVER_FACE  = "http://10.23.222.154:5000/api/face_recog"
SERVER_MSG   = "http://10.23.222.154:5000/api/message"

# ========= LINE 推播設定 =========
LINE_TOKEN = "你的_LINE_TOKEN"
LINE_TO_ID = "你的_LINE_USER_ID"
CLOUDINARY_CLOUD_NAME = "dx3ix8qmq"
CLOUDINARY_UPLOAD_PRESET = "linebot"

# TTS 設定
TTS_VOICE    = "zh-TW-YunJheNeural"
TTS_RATE     = "+5%"
TTS_HIT_TEXT = "你好，請問有什麼需要幫助的嗎？"
TTS_IDLE_TEXT= "Famix已進入待機模式"
is_playing_tts = False   # ✅ 播放 TTS 時暫停錄音

# ========= LINE 功能 =========
def line_push_text(msg):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"}
    data = {"to": LINE_TO_ID, "messages": [{"type": "text", "text": msg[:5000]}]}
    try:
        requests.post(url, headers=headers, json=data, timeout=10)
    except Exception as e:
        print("[LINE] 傳送文字失敗:", e)

def line_push_image(path, caption=""):
    try:
        with open(path, "rb") as f:
            files = {"file": f}
            data = {"upload_preset": CLOUDINARY_UPLOAD_PRESET}
            r = requests.post(
                f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload",
                files=files, data=data, timeout=20
            )
        if r.status_code == 200:
            url = r.json().get("secure_url")
            msgs = [{"type": "image", "originalContentUrl": url, "previewImageUrl": url}]
            if caption:
                msgs.append({"type": "text", "text": caption})
            requests.post(
                "https://api.line.me/v2/bot/message/push",
                headers={"Authorization": f"Bearer {LINE_TOKEN}",
                         "Content-Type": "application/json"},
                json={"to": LINE_TO_ID, "messages": msgs}
            )
        else:
            print("[LINE] 上傳失敗:", r.text[:200])
    except Exception as e:
        print("[LINE] 圖片推播錯誤:", e)


def capture_and_upload_face():
    """打開攝影機，拍一張照片送到 server"""
    cap = cv2.VideoCapture("rtsp://127.0.0.1:8554/unicast", cv2.CAP_FFMPEG)
    ret, frame = cap.read()
    cap.release()

    if not ret:
        print("[Client] 拍照失敗")
        return None

    tmp_path = f"/tmp/face_{timestamp()}.jpg"
    cv2.imwrite(tmp_path, frame)

    try:
        with open(tmp_path, "rb") as f:
            files = {"file": (os.path.basename(tmp_path), f, "image/jpeg")}
            resp = requests.post(SERVER_FACE, files=files)
        
            print(f"[Client] Server 回覆狀態碼: {resp.status_code}")
            print(f"[Client] Server 回覆原始內容: {resp.text[:200]}")  # 印前 200 字
        
            ctype = resp.headers.get("Content-Type", "")
            if "application/json" in ctype:
                return resp.json()
            else:
                print("[Client] Server 回傳不是 JSON，內容前200字:", resp.text[:200])
                return None

        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception as e:
                print(f"[Client] JSON 解析失敗: {e}")
                return None
        else:
            print(f"[Client] 人臉上傳失敗 {resp.status_code}")
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
def record_until_fixed(recorder, sample_rate=16000, duration=7):
    """固定錄音 N 秒"""
    frames = []
    total_frames = int(sample_rate / recorder.frame_length * duration)

    for i in range(total_frames):
        frame = recorder.read()
        frames.append(frame)

    print(f"[Client] ✅ 固定錄音 {duration} 秒完成")
    return frames


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
                frames = record_until_fixed(recorder, porcupine.sample_rate, duration=7)
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
                    frames = record_until_fixed(recorder, porcupine.sample_rate, duration=7)

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
    print(f"[Pi] 播報：{text}")
    tts_say_blocking(text)
    return jsonify({"status": "ok"})

@PI_SERVER.route("/api/record", methods=["POST"])
def api_record():
    """錄音一段音訊，送回 server /api/fall_reply 判斷"""
    recorder = PvRecorder(device_index=DEVICE_INDEX, frame_length=512)
    recorder.start()
    try:
        first_frame = recorder.read()
        frames = record_until_fixed(recorder, sample_rate=16000, duration=7)

        if not frames:
            return jsonify({"status": "unknown"})

        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)  # ✅ 固定取樣率
            for block in frames:
                wf.writeframes(struct.pack("<" + "h"*len(block), *block))
        wav_io.seek(0)

        files = {"file": ("reply.wav", wav_io, "audio/wav")}
        resp = requests.post("http://192.168.0.15:5000/api/fall_reply", files=files, timeout=20)
        if resp.status_code == 200:
            return jsonify(resp.json())
        else:
            return jsonify({"status": "error", "msg": resp.text}), 500
    finally:
        recorder.stop()
        recorder.delete()


def run_flask():
    PI_SERVER.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

# ========= 跌倒偵測功能 =========
def fall_detection_loop():
    print("[Fall] 啟動跌倒偵測中...")
    model = YOLO("yolov8n-pose.pt")
    cap = cv2.VideoCapture(0)
    last_alert = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.5)
            continue

        results = model.predict(frame, conf=0.3, iou=0.45, verbose=False)
        res = results[0]
        if res.keypoints is None:
            continue

        boxes = res.boxes.xyxy.cpu().numpy()
        kps = res.keypoints.xy.cpu().numpy()

        for i in range(len(boxes)):
            x1, y1, x2, y2 = boxes[i]
            bh = y2 - y1
            if bh < 80:
                continue

            SH_L, SH_R, HP_L, HP_R = 5, 6, 11, 12
            shoulder = ((kps[i][SH_L][0] + kps[i][SH_R][0]) / 2,
                        (kps[i][SH_L][1] + kps[i][SH_R][1]) / 2)
            hip = ((kps[i][HP_L][0] + kps[i][HP_R][0]) / 2,
                   (kps[i][HP_L][1] + kps[i][HP_R][1]) / 2)

            vec = np.array([shoulder[0]-hip[0], shoulder[1]-hip[1]], dtype=np.float32)
            vec /= np.linalg.norm(vec) + 1e-6
            angle = math.degrees(math.acos(np.clip(np.dot(vec, [0, -1]), -1, 1)))

            if angle > 70 and (time.time() - last_alert) > 30:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = f"/tmp/fall_{ts}.jpg"
                cv2.imwrite(path, frame)
                print(f"[Fall] 偵測到跌倒 (角度={angle:.1f})")
                tts_say_blocking("感知到有人跌倒，您是否需要通知他人？")

                r = sr.Recognizer()
                try:
                    with sr.Microphone() as source:
                        print("[Fall] 等待語音回覆...")
                        audio = r.listen(source, timeout=6, phrase_time_limit=6)
                    text = r.recognize_google(audio, language="zh-TW")
                    print("[Fall] 回覆內容:", text)
                except Exception:
                    text = ""

                if any(k in text for k in ["是", "要", "幫忙", "救命", "yes", "ok"]):
                    print("[Fall] 回覆需要協助 → 傳送 LINE 通知")
                    line_push_text("⚠️ Famix 偵測到跌倒且需要協助！")
                    line_push_image(path, caption="Famix 偵測到跌倒事件")
                else:
                    print("[Fall] 無回應，等待 60 秒後自動通報")
                    time.sleep(60)
                    line_push_text("⚠️ Famix 偵測到跌倒，未收到回覆，自動通報！")
                    line_push_image(path, caption="Famix 偵測到跌倒事件")

                last_alert = time.time()
        time.sleep(0.5)



if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=fall_detection_loop, daemon=True).start()
    main()


