#!/home/porco/.local/share/porco_translator/venv/bin/python
"""
Porco Lingua v22.0 - Real-Time YouTube Subtitles Edition
"""
import sys, os, subprocess, threading, select, time, queue, json, signal
import concurrent.futures
import numpy as np
from deep_translator import GoogleTranslator
from faster_whisper import WhisperModel
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QFrame, QTextEdit, QComboBox, QSizeGrip)
from PyQt6.QtCore import Qt, QPoint, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor, QGuiApplication, QIcon

RATE = 16000
CONFIG_PATH = os.path.expanduser("~/.config/porco-translator/config.json")
DB_PATH = os.path.expanduser("~/.local/share/porco_translator/db/history.txt")

class ConfigManager:
    @staticmethod
    def load():
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r') as f: return json.load(f)
            except: pass
        return {}
    @staticmethod
    def save(config):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        try:
            with open(CONFIG_PATH, 'w') as f: json.dump(config, f)
        except: pass

def get_installed_langs():
    return [
        ("English 🇺🇸", "en"), ("Português (Brasil) 🇧🇷", "pt"),
        ("Español 🇪🇸", "es"), ("Français 🇫🇷", "fr"),
        ("Deutsch 🇩🇪", "de"), ("Italiano 🇮🇹", "it"),
        ("日本語 🇯🇵", "ja"), ("한국어 🇰🇷", "ko"),
        ("中文 🇨🇳", "zh-CN"), ("Русский 🇷🇺", "ru")
    ]

def list_pw_sources():
    try:
        out = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
        found = []
        for line in out.strip().split('\n'):
            parts = line.split('\t')
            if len(parts) >= 2:
                name = parts[1]
                label = name.replace("alsa_input.", "").replace("alsa_output.", "").replace(".analog-stereo", "").replace(".monitor", "")
                if "easyeffects" in name.lower(): label = f"✨ EasyEffects: {label}"
                elif ".monitor" in name: label = f"🖥️ Monitor: {label}"
                else: label = f"🎙️ Microfone: {label}"
                found.append((label, name))
        return found
    except: return [("Padrão", "default")]

def get_best_audio_source():
    srcs = list_pw_sources()
    for l, n in srcs:
        if "easyeffects_sink.monitor" in n.lower(): return n
    for l, n in srcs:
        if "monitor" in n.lower(): return n
    return srcs[0][1] if srcs else "default"

class AudioWorker(QThread):
    status = pyqtSignal(str)
    def __init__(self, audio_queue, source):
        super().__init__()
        self.audio_queue = audio_queue
        self.source = source
        self.running = True
        self._proc = None

    def change_source(self, new_source):
        self.source = new_source
        if self._proc:
            try: self._proc.terminate()
            except: pass
            self._proc = None

    def auto_detect_active_source(self):
        try:
            out = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
            for line in out.strip().split('\n'):
                parts = line.split('\t')
                if len(parts) >= 2:
                    name = parts[1]
                    status = parts[-1] if len(parts) > 5 else ""
                    if ".monitor" in name and "RUNNING" in status and "easyeffects" not in name.lower():
                        return name
            return get_best_audio_source()
        except: return get_best_audio_source()

    def run(self):
        CHUNK_BYTES = int(RATE * 2 * 0.2)
        while self.running:
            self.status.emit(f"Ouvindo: {self.source[:15]}")
            try:
                self._proc = subprocess.Popen(
                    ["parecord", "--device", self.source, "--latency-msec=100", 
                     "--format=s16le", "--channels=1", "--rate=16000", "--raw"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
                )
                buffer = b""
                while self.running and self._proc.poll() is None:
                    ready, _, _ = select.select([self._proc.stdout], [], [], 0.05)
                    if ready:
                        chunk = self._proc.stdout.read(4096)
                        if chunk: buffer += chunk
                    
                    if len(buffer) >= CHUNK_BYTES:
                        raw = buffer[:CHUNK_BYTES]
                        buffer = buffer[CHUNK_BYTES:]
                        if self.audio_queue.qsize() > 50: 
                            try: self.audio_queue.get_nowait()
                            except: pass
                        self.audio_queue.put(raw)
            except: pass
            
            if self._proc:
                try: self._proc.terminate()
                except: pass
            time.sleep(1)

class TTSWorker(QThread):
    def __init__(self, tts_queue, vol_getter):
        super().__init__()
        self.tts_queue = tts_queue
        self.vol_getter = vol_getter
        self.running = True

    def run(self):
        while self.running:
            try:
                text = self.tts_queue.get(timeout=0.5)
                subprocess.call(["/home/porco/.local/bin/piper_read.sh", "1.3", text, str(self.vol_getter())])
            except queue.Empty:
                pass
            except Exception as e:
                print("TTS Error:", e)

class ProcessorWorker(QThread):
    new_segment = pyqtSignal(str)
    
    def __init__(self, audio_queue):
        super().__init__()
        self.audio_queue = audio_queue
        self.lang_from = "en"
        self.lang_to = "pt"
        self.running = True
        self.model = None
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        self.audio_buffer = [] 
        self._BASE_PROMPT = "Simple text transcription."
        self.prompt_text = self._BASE_PROMPT
        self.last_transcript = "" 
        self.tail_audio = None
        self.last_translation_request_time = 0

    def _do_translate(self, text, is_fin):
        if not text.strip(): return
        try:
            translated = GoogleTranslator(source=self.lang_from, target=self.lang_to).translate(text)
            self.new_segment.emit(f"__UPDATE__|{is_fin}|{text}|{translated if translated else text}")
        except:
            self.new_segment.emit(f"__UPDATE__|{is_fin}|{text}|{text} (API OFF)")

    def run(self):
        self.new_segment.emit("__LOG__:IA: Carregando Whisper...")
        try:
            self.model = WhisperModel("base", device="cuda", compute_type="float16")
            mode = "GPU"
        except:
            self.model = WhisperModel("base", device="cpu", compute_type="int8")
            mode = "CPU"
        
        self.new_segment.emit(f"__LOG__:IA: Pronta ({mode})")
        last_transcribe_time = time.time()
        silence_counter = 0

        while self.running:
            try:
                raw = self.audio_queue.get(timeout=0.1)
                audio_np = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                self.audio_buffer.append(audio_np)
                
                peak = np.max(np.abs(audio_np))
                self.new_segment.emit(f"__PEAK__:{peak:.4f}")
                
                if peak < 0.005: silence_counter += 1
                else: silence_counter = 0

                now = time.time()
                # Transcrição a cada 0.4s para legendas fluídas em tempo real
                if now - last_transcribe_time > 0.4:
                    last_transcribe_time = now
                    if len(self.audio_buffer) < 2: continue
                    
                    audio_raw = np.concatenate(self.audio_buffer)
                    audio_to_process = np.concatenate([self.tail_audio, audio_raw]) if self.tail_audio is not None else audio_raw
                    
                    if np.max(np.abs(audio_to_process)) < 0.006: continue

                    # Transcrição mais rápida com beam_size menor para tempo real
                    segments, _ = self.model.transcribe(
                        audio_to_process, beam_size=2,
                        language=self.lang_from, initial_prompt=self.prompt_text,
                        vad_filter=True, vad_parameters=dict(threshold=0.2, min_silence_duration_ms=500)
                    )
                    
                    actual_text = " ".join([s.text.strip() for s in list(segments) if s.no_speech_prob < 0.85]).strip()
                    
                    if not actual_text:
                        if silence_counter > 10:
                            self.audio_buffer = []; self.tail_audio = None; self.prompt_text = self._BASE_PROMPT
                        continue

                    is_final = (silence_counter > 5) or (len(audio_to_process) > RATE * 20)
                    
                    if actual_text != self.last_transcript or is_final:
                        self.last_transcript = actual_text
                        
                        # Debounce de tradução (para evitar ratelimit agressivo do Google)
                        if is_final or (now - self.last_translation_request_time > 0.8):
                            self.last_translation_request_time = now
                            self.executor.submit(self._do_translate, actual_text, is_final)
                        else:
                            # Envia só a atualização original imediatamente, mantém a última tradução
                            self.new_segment.emit(f"__UPDATE_ORIG__|{actual_text}")
                        
                        if is_final:
                            self.tail_audio = audio_to_process[-int(RATE*0.5):] if len(audio_to_process) > RATE*0.5 else None
                            self.prompt_text = f"{self._BASE_PROMPT} {actual_text[-40:]}"
                            self.audio_buffer = []; self.last_transcript = ""; silence_counter = 0
            except: continue

class OverlayWindow(QWidget):
    def __init__(self, audio_worker, proc_worker, tts_queue):
        super().__init__()
        self.audio_worker = audio_worker
        self.proc_worker = proc_worker
        self.tts_queue = tts_queue
        self.config = ConfigManager.load()
        self.font_size = self.config.get("font_size", 22)
        self.tts_vol = self.config.get("tts_vol", 1.0)
        self._last_activity = time.time()
        self._startup_time = time.time()
        self.is_listening = False
        self.last_translated = "..."
        self.history_html = []
        
        self.initUI()
        self.setWindowIcon(QIcon("/home/porco/.local/share/icons/porco_translator.png"))
        
        self.setMinimumSize(250, 150)
        geom = self.config.get("geometry")
        if geom and len(geom) == 4 and geom[2] > 100: self.setGeometry(geom[0], geom[1], geom[2], geom[3])
        else: self.setGeometry(100, 100, 350, 300)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_timer)
        self.timer.start(100)

    def initUI(self):
        # Ultra-light flags for gaming: No frame, Always on top, don't steal focus, ignore X11 manager rules
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                            Qt.WindowType.WindowStaysOnTopHint | 
                            Qt.WindowType.WindowDoesNotAcceptFocus |
                            Qt.WindowType.X11BypassWindowManagerHint)
        
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.box = QFrame(); self.box.setObjectName("Box")
        layout.addWidget(self.box)
        self.inner = QVBoxLayout(self.box); self.inner.setContentsMargins(15, 12, 15, 15)

        self.ctrl_widget = QWidget()
        ctrl_l = QVBoxLayout(self.ctrl_widget); ctrl_l.setContentsMargins(0,0,0,0)
        
        css_cb = "QComboBox { background: rgba(50,60,80,240); color: #fff; border-radius:3px; padding: 2px; border: 1px solid #777; font-size: 10px; }"
        css_bt = "QPushButton { background: #337ab7; color: white; border-radius:3px; padding: 3px; font-size: 10px; }"
        
        l0 = QHBoxLayout()
        self.handle = QFrame(); self.handle.setFixedSize(14, 14); self.handle.setStyleSheet("background: #f0ad4e; border-radius:7px;")
        l0.addWidget(self.handle)
        
        xbtn = QPushButton("✕"); xbtn.setFixedSize(18, 18)
        xbtn.setStyleSheet("background: #d9534f; color: white; border-radius:9px; font-weight:bold; font-size: 10px; padding: 0;")
        xbtn.clicked.connect(self.close_app)
        
        self.status_lbl = QLabel("..."); self.status_lbl.setStyleSheet("color: white; font-weight: bold; font-size: 10px;")
        self.peak_lbl = QLabel("🔈 -"); self.peak_lbl.setStyleSheet("color: #5f5; font-weight:bold; font-size: 10px;")
        
        l0.addStretch(); l0.addWidget(self.peak_lbl); l0.addWidget(self.status_lbl); l0.addStretch(); l0.addWidget(xbtn)
        ctrl_l.addLayout(l0)

        l1 = QHBoxLayout()
        self.from_box = QComboBox(); self.from_box.setStyleSheet(css_cb)
        self.to_box = QComboBox(); self.to_box.setStyleSheet(css_cb)
        for n, c in get_installed_langs():
            self.from_box.addItem(n.split(" ")[0], userData=c); self.to_box.addItem(n.split(" ")[0], userData=c)
        
        f_idx = self.from_box.findData(self.config.get("lang_from", "en"))
        if f_idx >= 0: self.from_box.setCurrentIndex(f_idx)
        t_idx = self.to_box.findData(self.config.get("lang_to", "pt"))
        if t_idx >= 0: self.to_box.setCurrentIndex(t_idx)
        
        self.from_box.currentIndexChanged.connect(self.update_langs)
        self.to_box.currentIndexChanged.connect(self.update_langs)
        
        l1.addWidget(self.from_box); l1.addWidget(QLabel("→")); l1.addWidget(self.to_box); l1.addStretch()
        ctrl_l.addLayout(l1)

        l2 = QHBoxLayout()
        self.src_btn = QComboBox(); self.src_btn.setStyleSheet(css_cb)
        srcs = list_pw_sources()
        for idx, (l, n) in enumerate(srcs):
            self.src_btn.addItem(l[:15]+"...", userData=n)
            if n == self.config.get("audio_source"): self.src_btn.setCurrentIndex(idx)
        self.src_btn.currentIndexChanged.connect(self.on_src_change); l2.addWidget(self.src_btn)
        
        bt_auto = QPushButton("Auto Scan"); bt_auto.setStyleSheet(css_bt); bt_auto.clicked.connect(self.do_auto_detect); l2.addWidget(bt_auto)
        ctrl_l.addLayout(l2)

        l3 = QHBoxLayout()
        bt_fup = QPushButton("A+"); bt_fup.setStyleSheet(css_bt); bt_fup.clicked.connect(lambda: self.change_font(2)); l3.addWidget(bt_fup)
        bt_fdn = QPushButton("A-"); bt_fdn.setStyleSheet(css_bt); bt_fdn.clicked.connect(lambda: self.change_font(-2)); l3.addWidget(bt_fdn)
        
        self.auto_read_btn = QPushButton("Auto-Leitura: OFF")
        self.auto_read_btn.setStyleSheet("background: #5bc0de; color: white; border-radius:3px; padding: 3px; font-size: 10px;")
        self.auto_read_btn.clicked.connect(self.toggle_listening); l3.addWidget(self.auto_read_btn)
        
        bt_clear = QPushButton("Limpar"); bt_clear.setStyleSheet(css_bt); bt_clear.clicked.connect(self.clear_hist); l3.addWidget(bt_clear)
        l3.addStretch(); ctrl_l.addLayout(l3)
        self.inner.addWidget(self.ctrl_widget)

        self.hist = QTextEdit(); self.hist.setReadOnly(True)
        self.hist.setStyleSheet("background: transparent; border: none; color: white; padding: 0;")
        self.hist.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inner.addWidget(self.hist)

        self.log_lbl = QLabel("Iniciando..."); self.log_lbl.setStyleSheet("color: #999; font-size: 10px;")
        self.inner.addWidget(self.log_lbl)
        
        self.grip = QSizeGrip(self); self.grip.setFixedSize(15, 15)
        self.update_style(True)

    def update_style(self, active):
        alpha = 240 if active else 0
        border = "#aaa" if active else "transparent"
        self.box.setStyleSheet(f"#Box {{ background: rgba(15,15,20,{alpha}); border: 2px solid {border}; border-radius:12px; }}")

    def on_timer(self):
        self.raise_()
        shift = QGuiApplication.queryKeyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        
        if shift:
            # Allow click-through while configuring
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.hist.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
            self.update_style(True); self.ctrl_widget.show(); self.grip.show()
            self.log_lbl.show()
        else:
            # Ghost Mode: Ghosted for mouse, no frame, no lag.
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.hist.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.update_style(False); self.ctrl_widget.hide(); self.grip.hide()
            self.log_lbl.hide()

    def on_src_change(self, i):
        s = self.src_btn.itemData(i); self.audio_worker.change_source(s)
        self.config["audio_source"] = s; ConfigManager.save(self.config)

    def do_auto_detect(self):
        act = self.audio_worker.auto_detect_active_source()
        idx = self.src_btn.findData(act)
        if idx >= 0: self.src_btn.setCurrentIndex(idx)

    def update_langs(self):
        self.proc_worker.lang_from = self.from_box.itemData(self.from_box.currentIndex())
        self.proc_worker.lang_to = self.to_box.itemData(self.to_box.currentIndex())
        self.config["lang_from"] = self.proc_worker.lang_from; self.config["lang_to"] = self.proc_worker.lang_to
        ConfigManager.save(self.config)

    def change_font(self, d):
        self.font_size = max(10, min(80, self.font_size + d))
        self.config["font_size"] = self.font_size; ConfigManager.save(self.config)
        if hasattr(self, "last_translated"):
            self.hist.setHtml("".join(self.history_html))

    def clear_hist(self): 
        self.hist.clear(); self.proc_worker.audio_buffer = []; self.history_html = []
        self.last_translated = "..."

    def on_new_text(self, text):
        if text.startswith("__PEAK__:"):
            v = float(text.split(":")[1]); self.peak_lbl.setText(f"{'🔊' if v > 0.01 else '🔈'} {v:.4f}")
            return
        if text.startswith("__LOG__:"): self.log_lbl.setText(text.split(":", 1)[1]); return
            
        if text.startswith("__UPDATE__|"):
            parts = text.split("|", 3)
            is_fin = (parts[1] == "True")
            original = parts[2]
            translated = parts[3]
            self.last_translated = translated
            self.update_subtitle(original, translated, is_fin)
            return
            
        if text.startswith("__UPDATE_ORIG__|"):
            original = text.split("|", 1)[1]
            translated = getattr(self, "last_translated", "...")
            self.update_subtitle(original, translated, False)
            return

    def update_subtitle(self, original, translated, is_fin):
        self._last_activity = time.time()
        
        font_family = "Inter, sans-serif"
        html_text = f'<div style="font-family: {font_family}; background: rgba(0,0,0,0.6); padding: 8px; border-radius: 8px; margin-bottom: 8px;">'
        html_text += f'<div style="color: #dddddd; font-size: {int(self.font_size*0.75)}px; font-weight: 500; margin-bottom: 2px;">{original}</div>'
        html_text += f'<div style="color: #f1c40f; font-size: {self.font_size}px; font-weight: bold; text-shadow: 1px 1px 2px #000;">{translated}</div>'
        html_text += '</div>'
        
        display_html = "".join(self.history_html) + html_text
        self.hist.setHtml(display_html)
        self.hist.moveCursor(QTextCursor.MoveOperation.End)
        
        if is_fin:
            self.history_html.append(html_text)
            if len(self.history_html) > 10:
                self.history_html = self.history_html[-10:]
            
            # Save to DB for intelligence building
            try:
                os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
                with open(DB_PATH, "a") as db:
                    db.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {original} | {translated}\n")
            except: pass

            if self.is_listening:
                 self.tts_queue.put(translated)

    def close_app(self):
        g = self.geometry(); self.config["geometry"] = [g.x(), g.y(), g.width(), g.height()]; ConfigManager.save(self.config)
        os._exit(0)

    def toggle_listening(self):
        self.is_listening = not self.is_listening
        self.auto_read_btn.setText(f"Auto-Leitura: {'ON' if self.is_listening else 'OFF'}")
        self.auto_read_btn.setStyleSheet(f"background: {'#d9534f' if self.is_listening else '#5bc0de'}; color: white; border-radius:4px; padding: 5px;")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        g = self.geometry(); self.config["geometry"] = [g.x(), g.y(), g.width(), g.height()]; ConfigManager.save(self.config)

    def moveEvent(self, e):
        super().moveEvent(e)
        g = self.geometry(); self.config["geometry"] = [g.x(), g.y(), g.width(), g.height()]; ConfigManager.save(self.config)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            it = self.childAt(e.position().toPoint())
            if it is self.handle or (it and it.parent() is self.handle):
                self._dragging = True; self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if hasattr(self, "_dragging") and self._dragging: self.move(e.globalPosition().toPoint() - self._drag_pos)
    def mouseReleaseEvent(self, e): self._dragging = False

def kill_previous_instances():
    current_pid = os.getpid()
    try:
        out = subprocess.check_output(["pgrep", "-f", "porco_translator.py"], text=True)
        for pid_str in out.strip().split('\n'):
            if pid_str.isdigit():
                pid = int(pid_str)
                if pid != current_pid: os.kill(pid, 9)
    except: pass

if __name__ == "__main__":
    kill_previous_instances()
    app = QApplication(sys.argv)
    q = queue.Queue()
    tq = queue.Queue()
    aw = AudioWorker(q, get_best_audio_source())
    pw = ProcessorWorker(q)
    win = OverlayWindow(aw, pw, tq)
    tw = TTSWorker(tq, lambda: win.tts_vol)
    pw.new_segment.connect(win.on_new_text); aw.status.connect(win.status_lbl.setText)
    aw.start(); pw.start(); tw.start(); win.show()
    sys.exit(app.exec())
