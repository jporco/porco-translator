import sys, os, subprocess, threading, time, queue, json, socket, signal, numpy as np
from faster_whisper import WhisperModel

UDP_IP   = "127.0.0.1"
UDP_TO   = 50134    # porta da UI
UDP_FROM = 50135    # porta de config
CONFIG_PATH = os.path.expanduser("~/.config/porco-translator/config.json")

# ── tamanho de chunk: 0.5 s @ 16 kHz, 16-bit mono ──────────────────────────
SAMPLE_RATE  = 16000
CHUNK_BYTES  = SAMPLE_RATE * 2   # 32 000 bytes = 1 s por leitura do pipe
MIN_CHUNKS   = 2                  # mínimo de chunks para transcrever (~2 s)
FINAL_CHUNKS = 10                 # chunks suficientes para finalizar linha (~10 s)

def load_c():
    if os.path.exists(CONFIG_PATH):
        try: return json.load(open(CONFIG_PATH, 'r'))
        except: pass
    return {}

class Broadcaster:
    def __init__(self): self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    def send(self, d):
        try: self.s.sendto(json.dumps(d).encode('utf-8'), (UDP_IP, UDP_TO))
        except: pass

class Proc:
    def __init__(self, q, b, lf):
        self.q, self.b, self.lf, self.running = q, b, lf, True
        # Tenta 'small', cai para 'base' se falhar (memória)
        # Tenta 'base', cai para 'tiny' se falhar
        for model_name in ("base", "tiny"):
            try:
                self.m = WhisperModel(model_name, device="cuda", compute_type="float32")
                print(f"[listener] Modelo carregado na GPU (float32): {model_name}", flush=True)
                break
            except Exception as ex:
                print(f"[listener] Falha ao carregar {model_name} na GPU: {ex}", flush=True)
                # Fallback para base em CPU se CUDA falhar totalmente
                if model_name == "tiny":
                    try:
                        self.m = WhisperModel("base", device="cpu", compute_type="int8")
                        print("[listener] Fallback: Modelo 'base' carregado na CPU", flush=True)
                    except:
                        self.m = None

    def transcribe(self, audio):
        """Transcreve array float32. Retorna string."""
        if self.m is None: return ""
        try:
            segs, info = self.m.transcribe(
                audio,
                language=self.lf if self.lf != "auto" else None,
                beam_size=3,
                best_of=3,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=400,
                    speech_pad_ms=300,
                    threshold=0.3,
                ),
                without_timestamps=True,
                condition_on_previous_text=False,
            )
            return " ".join(s.text for s in segs).strip()
        except Exception as ex:
            print(f"[listener] Erro transcrição: {ex}", flush=True)
            return ""

    def run(self):
        buf = []           # chunks acumulados
        silence_count = 0  # chunks consecutivos sem pico
        SILENCE_FLUSH = 4  # nº de chunks silenciosos para forçar finalização

        while self.running:
            try:
                raw = self.q.get(timeout=0.2)
            except queue.Empty:
                continue

            data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            peak = float(np.max(np.abs(data)))
            self.b.send({"type": "peak", "value": peak})

            buf.append(data)

            if peak < 0.005:
                silence_count += 1
            else:
                silence_count = 0

            # Nada suficiente para transcrever ainda
            if len(buf) < MIN_CHUNKS:
                continue

            # Decide se transcreve agora
            enough_silence = (silence_count >= SILENCE_FLUSH and len(buf) >= MIN_CHUNKS)
            enough_length  = (len(buf) >= FINAL_CHUNKS)

            if enough_silence or enough_length:
                audio = np.concatenate(buf)
                text  = self.transcribe(audio)
                is_final = True
                if text:
                    self.b.send({"type": "text", "text": text, "is_final": is_final})
                    print(f"[listener] [{self.lf}] final={is_final}: {text}", flush=True)
                buf = []
                silence_count = 0
            else:
                # Transcrição parcial a cada chunk (enquanto tem voz)
                audio = np.concatenate(buf)
                text  = self.transcribe(audio)
                if text:
                    self.b.send({"type": "text", "text": text, "is_final": False})

class Listener:
    def __init__(self, q):
        self.q = q
        self.proc = None
        self.running = True
        self.source = load_c().get("audio_source", "default")

    def start_capture(self):
        # Encerra captura anterior
        if self.proc:
            try:
                self.proc.send_signal(signal.SIGTERM)
                self.proc.wait(timeout=2)
            except: pass
        cmd = ["parecord", "--format", "s16le", "--rate", str(SAMPLE_RATE),
               "--channels", "1", "--raw", "--latency-msec=50"]
        if self.source and self.source != "default":
            cmd += ["--device", self.source]
        print(f"[listener] Capturando de: {self.source}", flush=True)
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        threading.Thread(target=self._read_pipe, daemon=True).start()

    def _read_pipe(self):
        proc = self.proc
        while self.running and self.proc is proc:
            d = proc.stdout.read(CHUNK_BYTES)
            if d:
                self.q.put(d)
            else:
                break

    def update_source(self, n):
        if self.source != n:
            self.source = n
            self.start_capture()

def udp_cfg(proc, listener):
    """Recebe config da UI via UDP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((UDP_IP, UDP_FROM))
    while True:
        try:
            data, _ = sock.recvfrom(1024)
            msg = json.loads(data.decode('utf-8'))
            if msg.get("type") == "config":
                proc.lf = msg.get("lang_from", proc.lf)
                listener.update_source(msg.get("audio_source", listener.source))
        except: continue

def main():
    c = load_c()
    q  = queue.Queue()
    b  = Broadcaster()
    p  = Proc(q, b, c.get("lang_from", "en"))
    l  = Listener(q)
    l.start_capture()
    threading.Thread(target=udp_cfg, args=(p, l), daemon=True).start()
    p.run()

if __name__ == "__main__":
    main()
