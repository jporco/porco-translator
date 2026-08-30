import sys, select, subprocess, time, numpy as np
from faster_whisper import WhisperModel

print("Loading model...")
model = WhisperModel("base", device="cuda", compute_type="int8")

print("Capturing 5s of audio from default sink monitor...")
src = subprocess.check_output(['pactl', 'get-default-sink'], text=True).strip() + '.monitor'
proc = subprocess.Popen(['pw-record', '--target', src, '--format', 's16', '--rate', '16000', '--channels', '1', '-'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)

start = time.time()
buffer = b''
for _ in range(50):
    ready, _, _ = select.select([proc.stdout], [], [], 0.1)
    if ready:
        chunk = proc.stdout.read(4096)
        if chunk: buffer += chunk
proc.terminate()

if len(buffer) == 0:
    print("No audio captured!")
    sys.exit(1)

audio = np.frombuffer(buffer, dtype=np.int16).astype(np.float32) / 32768.0
print(f"Captured peak: {np.max(np.abs(audio)):.4f}")

print("--- Test 1: Original Failing Params (vad_filter=False, no_speech_threshold=0.5) ---")
try:
    segments, info = model.transcribe(audio, beam_size=3, vad_filter=False, condition_on_previous_text=False, no_speech_threshold=0.5)
    text = " ".join([s.text for s in segments]).strip()
    print(f"Text 1: '{text}'")
except Exception as e:
    print(f"Error: {e}")

print("--- Test 2: Relaxed Params (vad_filter=True, no_speech_threshold=0.9, log_prob_threshold=-1.0) ---")
try:
    segments, info = model.transcribe(audio, beam_size=5, vad_filter=True, condition_on_previous_text=False, no_speech_threshold=0.9, log_prob_threshold=-1.0)
    text = " ".join([s.text for s in segments]).strip()
    print(f"Text 2: '{text}'")
except Exception as e:
    print(f"Error: {e}")
