import sys, select, subprocess, time, numpy as np, wave
from faster_whisper import WhisperModel

print("Capturing 5s to WAV...")
src = subprocess.check_output(['pactl', 'get-default-sink'], text=True).strip() + '.monitor'
proc = subprocess.Popen(['pw-record', '--target', src, '--format', 's16', '--rate', '16000', '--channels', '1', 'test_cap.wav'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(5)
proc.terminate()

with wave.open('test_cap.wav', 'rb') as wf:
    audio_data = wf.readframes(wf.getnframes())
    audio = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
    print(f"WAV peak: {np.max(np.abs(audio)):.4f}")

print("Loading model...")
model = WhisperModel("base", device="cuda", compute_type="int8")

print("Transcribing WAV...")
try:
    segments, info = model.transcribe("test_cap.wav", beam_size=5, vad_filter=True, no_speech_threshold=0.6)
    text = " ".join([s.text for s in segments]).strip()
    print(f"WAV Text: '{text}'")
except Exception as e:
    print(f"Error: {e}")
