import sys, time, subprocess, threading, queue, json
import numpy as np
from vosk import Model, KaldiRecognizer

# Note: Model(lang="en-us") downloads automatically if not found
print("Loading Vosk Model (Small EN)...")
try:
    model = Model(lang="en-us")
except Exception as e:
    print(f"Error loading model: {e}")
    sys.exit(1)

rec = KaldiRecognizer(model, 16000)

audio_queue = queue.Queue()

def capture_audio():
    # Attempt to find the best source automatically
    try:
        out = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
        source = "@DEFAULT_MONITOR@"
        for line in out.strip().split("\n"):
            if "RUNNING" in line and ".monitor" in line:
                source = line.split("\t")[1]
                break
    except:
        source = "@DEFAULT_MONITOR@"
        
    print(f"DEBUG: Selected source: {source}")
    proc = subprocess.Popen(['parecord', '--device', source, '--format', 's16le', '--rate', '16000', '--channels', '1', '--raw'], 
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    
    while True:
        data = proc.stdout.read(4000)
        if not data: break
        
        # Peak debug
        audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        p = np.max(np.abs(audio))
        if p > 0.05:
            # Silently update queue, only print if needed
            pass
            
        audio_queue.put(data)

threading.Thread(target=capture_audio, daemon=True).start()

print("Streaming... (Partial results will show below)")
try:
    while True:
        data = audio_queue.get()
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            if result.get('text'):
                print(f"[FINAL] {result['text']}")
        else:
            partial = json.loads(rec.PartialResult())
            if partial.get('partial'):
                print(f"[PARTIAL] {partial['partial']}")
except KeyboardInterrupt:
    print("\nStopped.")
