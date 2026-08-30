import sys, time, subprocess, threading, queue, os
import numpy as np
from faster_whisper import WhisperModel

# Params
RATE = 16000
CHUNK_SECS = 0.5
WINDOW_SECS = 4.0
MODEL_SIZE = "base" # User has 'base' in cache

print(f"Loading {MODEL_SIZE} on CUDA...")
model = WhisperModel(MODEL_SIZE, device="cuda", compute_type="int8")

audio_queue = queue.Queue()

def capture_audio():
    src = subprocess.check_output(['pactl', 'get-default-sink'], text=True).strip() + '.monitor'
    # Use parecord for better reliability
    proc = subprocess.Popen(['parecord', '--device', src, '--format', 's16le', '--rate', str(RATE), '--channels', '1', '--raw'], 
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    
    chunk_bytes = int(RATE * 2 * CHUNK_SECS)
    while True:
        data = proc.stdout.read(chunk_bytes)
        if not data: break
        audio_queue.put(data)

threading.Thread(target=capture_audio, daemon=True).start()

print("Streaming... Press Ctrl+C to stop.")
audio_buffer = np.zeros(int(RATE * WINDOW_SECS), dtype=np.float32)

last_text = ""

try:
    while True:
        # Wait for new chunk
        raw_chunk = audio_queue.get()
        new_audio = np.frombuffer(raw_chunk, dtype=np.int16).astype(np.float32) / 32768.0
        
        # Shift buffer and add new audio
        audio_buffer = np.roll(audio_buffer, -len(new_audio))
        audio_buffer[-len(new_audio):] = new_audio
        
        # Check if enough sound (VAD)
        if np.max(np.abs(audio_buffer)) < 0.005:
            continue
            
        # Transcribe window
        t0 = time.time()
        # We use a very small beam_size and no VAD filter (manual VAD above) for max speed
        segments, _ = model.transcribe(audio_buffer, beam_size=1, best_of=1, language="en")
        
        text = ""
        for s in segments:
            text += s.text
        text = text.strip()
        
        latency = (time.time() - t0) * 1000
        
        if text and text != last_text:
            print(f"[{latency:4.0f}ms] {text}")
            last_text = text

except KeyboardInterrupt:
    print("\nStopped.")
