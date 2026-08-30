import json
import os
import queue
import re
import signal
import socket
import subprocess
import threading
import time
from collections import deque

import numpy as np
from faster_whisper import WhisperModel

UDP_IP   = "127.0.0.1"
UDP_TO   = 50134    # porta da UI
UDP_FROM = 50135    # porta de config
CONFIG_PATH = os.path.expanduser("~/.config/porco-translator/config.json")

# ── áudio PCM: 0,5 s @ 16 kHz, 16-bit mono ──────────────────────────────────
SAMPLE_RATE  = 16000
CHUNK_SECONDS = 0.5
CHUNK_BYTES  = int(SAMPLE_RATE * CHUNK_SECONDS * 2)
MIN_CHUNKS   = 3                  # mínimo de áudio para transcrever (~1,5 s)
INFER_EVERY  = 2                  # reavalia a janela a cada ~1 s
SILENCE_FLUSH = 3                 # finaliza após ~1,5 s de silêncio
MAX_AUDIO_QUEUE = 16               # margem para o processamento sem perder áudio
MAX_WINDOW_SECONDS = 4             # janela sobreposta para estabilizar palavras
STABILITY_DELAY = 0.8              # confirma mais perto da fala atual
COMMIT_WORDS = 5                    # entrega blocos menores sem reescrever o histórico
COMPUTE_TYPE = os.environ.get("PORCO_WHISPER_COMPUTE", "int8_float32")
BEAM_SIZE = max(1, int(os.environ.get("PORCO_WHISPER_BEAM_SIZE", "3")))

def load_c():
    if os.path.exists(CONFIG_PATH):
        try: return json.load(open(CONFIG_PATH, 'r'))
        except: pass
    return {}

def resolve_audio_source(source):
    """Converte 'default' no monitor da saída padrão do sistema."""
    if source not in (None, "", "default"):
        return source
    try:
        sink = subprocess.check_output(
            ["pactl", "get-default-sink"], text=True, timeout=2
        ).strip()
        if sink:
            return f"{sink}.monitor"
    except (OSError, subprocess.SubprocessError):
        pass
    # O PulseAudio compatível aceita este alias; não cai no microfone padrão.
    return "@DEFAULT_MONITOR@"

class Broadcaster:
    def __init__(self): self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    def send(self, d):
        try: self.s.sendto(json.dumps(d).encode('utf-8'), (UDP_IP, UDP_TO))
        except: pass

class Proc:
    def __init__(self, q, b, lf):
        self.q, self.b, self.lf, self.running = q, b, lf, True
        self.m = None
        preferred_model = os.environ.get(
            "PORCO_WHISPER_MODEL",
            "base.en" if lf == "en" else "base",
        )
        if lf == "en":
            fallback_models = ["tiny.en"]
        else:
            fallback_models = ["tiny"]
        candidates = list(dict.fromkeys([preferred_model] + fallback_models))
        compute_types = list(dict.fromkeys((COMPUTE_TYPE, "int8_float32", "float32")))
        for model_name in candidates:
            for compute_type in compute_types:
                if compute_type == "float32" and COMPUTE_TYPE != "float32":
                    continue
                try:
                    self.m = WhisperModel(
                        model_name, device="cuda", compute_type=compute_type
                    )
                    print(
                        f"[listener] Modelo GPU: {model_name} ({compute_type})",
                        flush=True,
                    )
                    break
                except Exception as ex:
                    print(
                        f"[listener] Falha GPU {model_name}/{compute_type}: {ex}",
                        flush=True,
                    )
            if self.m is not None:
                break

        if self.m is None:
            try:
                self.m = WhisperModel(candidates[0], device="cpu", compute_type="int8")
                print(f"[listener] Fallback CPU: {candidates[0]} (int8)", flush=True)
            except Exception as ex:
                print(f"[listener] Não foi possível carregar o Whisper: {ex}", flush=True)

    def transcribe(self, audio):
        """Transcreve e devolve palavras com timestamps relativos à janela."""
        if self.m is None: return []
        try:
            segs, info = self.m.transcribe(
                audio,
                language=self.lf if self.lf != "auto" else None,
                beam_size=BEAM_SIZE,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=300,
                    speech_pad_ms=200,
                    threshold=0.3,
                ),
                word_timestamps=True,
                condition_on_previous_text=False,
                no_speech_threshold=0.6,
                compression_ratio_threshold=2.4,
            )
            words = []
            for segment in segs:
                if segment.words:
                    for word in segment.words:
                        if word.start is not None and word.end is not None:
                            words.append((word.start, word.end, word.word))
            return words
        except Exception as ex:
            print(f"[listener] Erro transcrição: {ex}", flush=True)
            return []

    @staticmethod
    def _word_key(text):
        return re.sub(r"[^\w]+", "", text.casefold(), flags=re.UNICODE)

    @staticmethod
    def _format_words(words):
        text = " ".join(word[2].strip() for word in words).strip()
        return re.sub(r"\s+([,.!?;:%])", r"\1", text)

    def _stable_words(self, current, previous, window_start, stream_end, force=False):
        """Retorna somente palavras confirmadas em duas janelas consecutivas."""
        current_abs = [
            (window_start + start, window_start + end, text)
            for start, end, text in current
        ]
        if force:
            return current_abs

        safe_end = stream_end - STABILITY_DELAY
        stable = []
        used = set()
        for start, end, text in current_abs:
            if end > safe_end:
                continue
            key = self._word_key(text)
            if not key:
                continue
            best = None
            for index, (p_start, p_end, p_text) in enumerate(previous):
                if index in used or self._word_key(p_text) != key:
                    continue
                if abs(p_start - start) <= 0.8 or min(p_end, end) > max(p_start, start):
                    distance = abs(p_start - start)
                    if best is None or distance < best[0]:
                        best = (distance, index)
            if best is not None:
                used.add(best[1])
                stable.append((start, end, text))
        return stable

    def run(self):
        buf = deque()
        buffered_samples = 0
        stream_samples = 0
        silence_count = 0  # chunks consecutivos sem pico
        utterance_id = 0
        chunks_since_inference = 0
        previous_words = []
        committed_end = 0.0
        pending_words = []
        speech_seen = False
        max_window_samples = SAMPLE_RATE * MAX_WINDOW_SECONDS

        while self.running:
            try:
                raw = self.q.get(timeout=0.2)
            except queue.Empty:
                continue

            data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            peak = float(np.max(np.abs(data)))
            self.b.send({"type": "peak", "value": peak})

            buf.append(data)
            buffered_samples += len(data)
            stream_samples += len(data)
            chunks_since_inference += 1

            if peak < 0.005:
                silence_count += 1
            else:
                silence_count = 0
                speech_seen = True

            while buffered_samples > max_window_samples:
                buffered_samples -= len(buf.popleft())

            if len(buf) < MIN_CHUNKS:
                continue

            enough_silence = silence_count >= SILENCE_FLUSH
            enough_time = chunks_since_inference >= INFER_EVERY
            if not enough_silence and not enough_time:
                continue

            audio = np.concatenate(buf)
            window_start = (stream_samples - buffered_samples) / SAMPLE_RATE
            current_words = self.transcribe(audio)
            force = enough_silence and speech_seen
            stable = self._stable_words(
                current_words,
                previous_words,
                window_start,
                stream_samples / SAMPLE_RATE,
                force=force,
            )
            new_words = [word for word in stable if word[1] > committed_end + 0.05]
            if new_words:
                pending_words.extend(new_words)
                committed_end = max(word[1] for word in new_words)

            if pending_words:
                last_word = pending_words[-1][2].strip()
                complete_block = (
                    force
                    or len(pending_words) >= COMMIT_WORDS
                    or bool(re.search(r"[.!?…]$", last_word))
                )
                if complete_block:
                    text = self._format_words(pending_words)
                    utterance_id += 1
                    self.b.send({
                        "type": "text",
                        "text": text,
                        "is_final": True,
                        "utterance_id": utterance_id,
                    })
                    print(f"[listener] [{self.lf}] confirmado: {text}", flush=True)
                    pending_words = []

            previous_words = [
                (window_start + start, window_start + end, text)
                for start, end, text in current_words
            ]
            chunks_since_inference = 0

            if force:
                buf.clear()
                buffered_samples = 0
                previous_words = []
                committed_end = stream_samples / SAMPLE_RATE
                pending_words = []
                silence_count = 0
                speech_seen = False

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
        capture_source = resolve_audio_source(self.source)
        if capture_source:
            cmd += ["--device", capture_source]
        print(
            f"[listener] Capturando de: {capture_source} (configurado: {self.source})",
            flush=True,
        )
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        threading.Thread(target=self._read_pipe, daemon=True).start()

    def _read_pipe(self):
        proc = self.proc
        while self.running and self.proc is proc:
            d = proc.stdout.read(CHUNK_BYTES)
            if d:
                try:
                    self.q.put_nowait(d)
                except queue.Full:
                    # Sempre prioriza áudio recente para limitar a latência.
                    try:
                        self.q.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self.q.put_nowait(d)
                    except queue.Full:
                        pass
            else:
                break

    def update_source(self, n):
        if self.source != n:
            self.source = n
            self.start_capture()

    def stop(self):
        self.running = False
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()

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
    q  = queue.Queue(maxsize=MAX_AUDIO_QUEUE)
    b  = Broadcaster()
    p  = Proc(q, b, c.get("lang_from", "en"))
    l  = Listener(q)

    def stop(signum, _frame):
        p.running = False
        l.stop()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    l.start_capture()
    threading.Thread(target=udp_cfg, args=(p, l), daemon=True).start()
    p.run()

if __name__ == "__main__":
    main()
