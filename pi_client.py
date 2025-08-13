import pvporcupine
import pyaudio
import wave
import struct

# 設定參數
ACCESS_KEY = "lFgwg3geIsAy15neS3EIMCa1+QrXmlxcbtUyW7GdTjyFl+5TDcrkQw=="
KEYWORD_PATH = "Hey-Famix_en_raspberry-pi.ppn"
AUDIO_FILE = "wake_audio.wav"

# 建立 Porcupine 物件
porcupine = pvporcupine.create(
    access_key=ACCESS_KEY,
    keyword_paths=[KEYWORD_PATH]
)

pa = pyaudio.PyAudio()
stream = pa.open(
    rate=porcupine.sample_rate,
    channels=1,
    format=pyaudio.paInt16,
    input=True,
    frames_per_buffer=porcupine.frame_length
)

print("🟢 等待喚醒詞...")

try:
    while True:
        pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
        pcm = struct.unpack_from("h" * porcupine.frame_length, pcm)

        if porcupine.process(pcm):
            print("✅ 喚醒詞偵測成功！開始錄音...")

            frames = []
            for _ in range(0, int(porcupine.sample_rate / porcupine.frame_length * 3)):  # 錄 3 秒
                pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
                frames.append(pcm)

            # 存成 wav 檔
            wf = wave.open(AUDIO_FILE, 'wb')
            wf.setnchannels(1)
            wf.setsampwidth(pa.get_sample_size(pyaudio.paInt16))
            wf.setframerate(porcupine.sample_rate)
            wf.writeframes(b''.join(frames))
            wf.close()

            print(f"🎙️ 錄音儲存至 {AUDIO_FILE}，可傳送給伺服器")

except KeyboardInterrupt:
    print("🛑 停止程式")

finally:
    stream.stop_stream()
    stream.close()
    pa.terminate()
    porcupine.delete()
