import pvporcupine
import pyaudio
import wave
import struct
import time
import datetime

ACCESS_KEY = "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw=="
KEYWORD_PATH = "/home/admin/Porcupine/hi-fe-mix_en_raspberry-pi_v3_0_0.ppn"
AUDIO_FILE = "wake_audio.wav"

# === 建立 Porcupine 偵測器 ===
porcupine = pvporcupine.create(
    access_key=ACCESS_KEY,
    keyword_paths=[KEYWORD_PATH],
    sensitivities=[0.3]  # 降低靈敏度避免誤判
)

# === 初始化音訊輸入裝置 ===
pa = pyaudio.PyAudio()
stream = pa.open(
    rate=porcupine.sample_rate,
    channels=1,
    format=pyaudio.paInt16,
    input=True,
    frames_per_buffer=porcupine.frame_length
)

print("🟢 系統啟動，等待喚醒詞...")

try:
    while True:
        pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
        pcm = struct.unpack_from("h" * porcupine.frame_length, pcm)

        if porcupine.process(pcm):
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n✅ [{now}] 喚醒詞偵測成功！開始錄音...")

            frames = []
            for _ in range(0, int(porcupine.sample_rate / porcupine.frame_length * 3)):  # 錄音 3 秒
                pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
                frames.append(pcm)

            # 儲存為 WAV 檔
            wf = wave.open(AUDIO_FILE, 'wb')
            wf.setnchannels(1)
            wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
            wf.setframerate(porcupine.sample_rate)
            wf.writeframes(b''.join(frames))
            wf.close()

            print(f"💾 錄音儲存至：{AUDIO_FILE}，可傳送給伺服器")

            # 避免連續誤觸，暫停 3 秒
            time.sleep(3)

except KeyboardInterrupt:
    print("\n🛑 偵測已中止（Ctrl+C）")

finally:
    stream.stop_stream()
    stream.close()
    pa.terminate()
    porcupine.delete()
    print("🔒 音訊資源已釋放，程式結束")
