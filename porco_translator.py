#!/home/porco/.local/share/porco_translator/venv/bin/python
"""
Porco Lingua v13.0 - Ultra Stable & Anti-Flicker
"""
import sys, os, subprocess, threading, select, time, queue, json, signal
import concurrent.futures
import numpy as np
from deep_translator import GoogleTranslator
from faster_whisper import WhisperModel
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QFrame, QPlainTextEdit, QComboBox, QSizeGrip)
from PyQt6.QtCore import Qt, QPoint, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor, QGuiApplication, QIcon
# Configurações Globais
RATE = 16000
COLLECT_SECS = 0.25 
MAX_HIST_CHARS = 5000 
CONFIG_PATH = os.path.expanduser("~/.config/porco-translator/config.json")

class ConfigManager:
    @staticmethod
    def load():
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r') as f:
                    return json.load(f)
            except: pass
        return {}

    @staticmethod
    def save(config):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        try:
            with open(CONFIG_PATH, 'w') as f:
                json.dump(config, f)
        except: pass

def get_installed_langs():
    return [
        ("English 🇺🇸", "en"), ("Português (Brasil) 🇧🇷", "pt"),
        ("Español 🇪🇸", "es"), ("Français 🇫🇷", "fr"),
        ("Deutsch 🇩🇪", "de"), ("Italiano 🇮🇹", "it"),
        ("日本語 🇯🇵", "ja"), ("한국어 🇰🇷", "ko"),
        ("中文 🇨🇳", "zh-CN"), ("Русский 🇷🇺", "ru")
    ]

def get_best_audio_source():
    try:
        default_sink = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
        if default_sink:
            monitor_source = default_sink + ".monitor"
            sources = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
            if monitor_source in sources:
                return monitor_source
        
        out = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
        running_monitor = None
        for line in out.strip().split('\n'):
            parts = line.split('\t')
            if len(parts) >= 2:
                name = parts[1]
                status = parts[-1] if len(parts) > 5 else ""
                if ".monitor" in name and "RUNNING" in status:
                    return name
                if ".monitor" in name and not running_monitor:
                    running_monitor = name
        
        if running_monitor: return running_monitor
        res = subprocess.check_output(["pactl", "get-default-source"], text=True).strip()
        return res
    except: return "@DEFAULT_MONITOR@"

def list_pw_sources():
    try:
        out = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
        try:
            default_sink = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
            default_monitor = default_sink + ".monitor"
        except:
            default_monitor = None

        found = []
        for line in out.strip().split('\n'):
            parts = line.split('\t')
            if len(parts) >= 2:
                name = parts[1]
                label = name.replace("alsa_input.", "").replace("alsa_output.", "").replace(".analog-stereo", "").replace(".monitor", "")
                if name == default_monitor: label = "🔊 Áudio do Sistema (Padrão)"
                elif ".monitor" in name: label = f"🖥️ Monitor: {label}"
                else: label = f"🎙️ Microfone: {label}"
                found.append((label, name))
        return found
    except: return [("Padrão", get_best_audio_source())]

class AudioWorker(QThread):
    status = pyqtSignal(str)
    def __init__(self, audio_queue, source):
        super().__init__()
        self.audio_queue = audio_queue
        self.source = source
        self.running = True
        self._proc = None
        self._lock = threading.Lock()

    def change_source(self, new_source):
        with self._lock:
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
        CHUNK_BYTES = int(RATE * 2 * 0.25)
        while self.running:
            self.status.emit("Ouvindo...")
            with self._lock:
                try:
                    self._proc = subprocess.Popen(
                        ["parecord", "--device", self.source,
                         "--format", "s16le", "--rate", str(RATE), "--channels", "1", "--raw"],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
                    )
                except: time.sleep(2); continue

            buffer = b""
            try:
                while self.running:
                    with self._lock: p = self._proc
                    if not p or p.poll() is not None: break
                    if p.stdout:
                        ready, _, _ = select.select([p.stdout], [], [], 0.05)
                        if ready:
                            chunk = p.stdout.read(4096)
                            if chunk: buffer += chunk
                    if len(buffer) >= CHUNK_BYTES:
                        raw = buffer[:CHUNK_BYTES]
                        buffer = buffer[CHUNK_BYTES:]
                        if self.audio_queue.qsize() > 20:
                            try: self.audio_queue.get_nowait()
                            except: pass
                        self.audio_queue.put(raw)
            except: pass
            with self._lock:
                if self._proc:
                    try: self._proc.terminate()
                    except: pass
                    self._proc = None
            time.sleep(0.1)

class ProcessorWorker(QThread):
    new_segment = pyqtSignal(str)
    api_result = pyqtSignal(str, bool)

    def __init__(self, audio_queue):
        super().__init__()
        self.audio_queue = audio_queue
        self.lang_from = "en"
        self.lang_to = "pt"
        self.running = True
        self.model = None
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        
        # Lógica de Estabilidade & Cobertura (Anti-Eating)
        self.audio_buffer = [] 
        self.prompt_text = "Fantasy video game dialogue. Rytlock, Jormag, Braham, Crecia, Tyria, Charr, Norn." 
        self.last_transcript = "" 
        self.tail_audio = None # Cauda de áudio para evitar cortes de palavras
        
        self.api_result.connect(self.handle_api_result)

    def handle_api_result(self, text, is_fin):
        self.new_segment.emit(f"__IS_FINAL__:{is_fin}|{text}")

    def _do_translate(self, text, l_from, l_to, is_fin):
        try:
            translated = GoogleTranslator(source=l_from, target=l_to).translate(text)
            self.api_result.emit(translated if translated else text, is_fin)
        except Exception as e:
            print(f"Erro tradução: {e}")
            self.api_result.emit(text, is_fin)

    def run(self):
        print("[ProcessorWorker] Carregando Whisper com VAD na GPU...")
        try:
            self.model = WhisperModel("base", device="cuda", compute_type="float16")
        except Exception as e:
            print(f"Erro CUDA: {e}. Tentando CPU...")
            self.model = WhisperModel("base", device="cpu", compute_type="int8")
        
        print("[ProcessorWorker] Pronto!")
        last_transcribe_time = time.time()
        silence_counter = 0

        while self.running:
            try:
                raw = self.audio_queue.get(timeout=0.1)
                new_audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                
                self.audio_buffer.append(new_audio)
                peak = np.max(np.abs(new_audio))
                self.new_segment.emit(f"__PEAK__:{peak:.4f}")

                # Se o pico for muito baixo por muito tempo (silêncio total real)
                if peak < 0.004: 
                    silence_counter += 1
                else: 
                    silence_counter = 0

                now = time.time()
                if now - last_transcribe_time > 0.5: # Mais frequente
                    last_transcribe_time = now
                    if not self.audio_buffer: continue
                    
                    # Concatena com a "cauda" do áudio anterior para não cortar o início da fala
                    if self.tail_audio is not None:
                        audio_to_process = np.concatenate([self.tail_audio, np.concatenate(self.audio_buffer)])
                    else:
                        audio_to_process = np.concatenate(self.audio_buffer)
                        
                    if np.max(np.abs(audio_to_process)) < 0.005: continue

                    # Transcrição com VAD relaxado para captar interjeições e sussurros
                    segments, info = self.model.transcribe(
                        audio_to_process, 
                        beam_size=2, # Pequeno aumento para precisão de nomes
                        best_of=2, 
                        language=self.lang_from,
                        initial_prompt=self.prompt_text,
                        repetition_penalty=1.3,
                        condition_on_previous_text=True, # Melhorar fluxo de nomes próprios
                        vad_filter=True,
                        vad_parameters=dict(
                            threshold=0.3, # Mais sensível ao som baixo
                            min_silence_duration_ms=1000, # Não corta no meio de pausas dramáticas
                            speech_pad_ms=300 # Adiciona folga no áudio
                        )
                    )
                    
                    segments_list = list(segments)
                    # Relaxamos no_speech_prob para 0.85 (ou seja, só descarta se tiver 85% de certeza que é lixo)
                    actual_text = " ".join([s.text.strip() for s in segments_list if s.no_speech_prob < 0.85]).strip()
                    
                    if not actual_text:
                        if silence_counter > 12: # Mais tolerância antes de desistir
                            self.audio_buffer = []
                            self.tail_audio = None
                        continue

                    # LÓGICA DE ESTABILIDADE
                    is_final = (silence_counter > 6) or (len(audio_to_process) > RATE * 28)
                    
                    if actual_text != self.last_transcript or is_final:
                        self.last_transcript = actual_text
                        self.executor.submit(self._do_translate, actual_text, self.lang_from, self.lang_to, is_final)
                        
                        if is_final:
                            # Finalizou a frase: 
                            # Mantemos 500ms de áudio como cauda para a próxima frase não começar cortada
                            samples_to_keep = int(RATE * 0.5)
                            if len(audio_to_process) > samples_to_keep:
                                self.tail_audio = audio_to_process[-samples_to_keep:]
                            
                            self.prompt_text = "Fantasy game: " + " ".join(actual_text.split()[-12:])
                            self.audio_buffer = []
                            self.last_transcript = ""
                            silence_counter = 0

            except queue.Empty: continue
            except Exception as e:
                print(f"Erro: {e}")
                self.new_segment.emit(f"[Erro Fatal]: {e}")

class OverlayWindow(QWidget):
    def __init__(self, audio_worker, proc_worker):
        super().__init__()
        self.audio_worker = audio_worker
        self.proc_worker = proc_worker
        self._dragging = False
        self._drag_pos = QPoint()
        self.config = ConfigManager.load()
        self.font_size = self.config.get("font_size", 18)
        self.tts_vol = self.config.get("tts_vol", 1.0)
        self.is_listening = False
        
        self.initUI()
        self.setWindowIcon(QIcon("/home/porco/.local/share/icons/porco_translator.png"))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.on_timer)
        self.timer.start(100)

    def initUI(self):
        # Flags para ficar sempre no topo e ignorar janelas
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                           Qt.WindowType.WindowStaysOnTopHint | 
                           Qt.WindowType.X11BypassWindowManagerHint)
        
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setGeometry(100, 100, 800, 250)
        self.setMinimumSize(400, 100)

        self.box = QFrame(self)
        self.box.setObjectName("Box")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.box)
        self.inner = QVBoxLayout(self.box)
        self.inner.setContentsMargins(10, 10, 10, 10)
        self.inner.setSpacing(8)

        self.ctrl_widget = QWidget()
        self.ctrl_bar = QVBoxLayout(self.ctrl_widget)
        self.ctrl_bar.setContentsMargins(0, 0, 0, 0)
        self.ctrl_bar.setSpacing(4)
        l1 = QHBoxLayout()
        self.handle = QFrame()
        self.handle.setFixedSize(18, 18)
        self.handle.setStyleSheet("background: rgba(220,180,60,150); border-radius:4px;")
        l1.addWidget(self.handle)

        combo_s = "QComboBox { background: rgba(30,40,60,180); color: #fff; font-size: 11px; border:none; border-radius:4px; padding: 3px; }"
        self.from_box = QComboBox()
        self.from_box.setStyleSheet(combo_s)
        self.to_box = QComboBox()
        self.to_box.setStyleSheet(combo_s)
        langs = get_installed_langs()
        default_from = self.config.get("lang_from", "en")
        default_to = self.config.get("lang_to", "pt")
        for name, code in langs:
            self.from_box.addItem(name, userData=code)
            self.to_box.addItem(name, userData=code)
            if code == default_from: self.from_box.setCurrentIndex(self.from_box.count()-1)
            if code == default_to: self.to_box.setCurrentIndex(self.to_box.count()-1)
        self.from_box.currentIndexChanged.connect(self.update_langs)
        self.to_box.currentIndexChanged.connect(self.update_langs)
        l1.addWidget(self.from_box); l1.addWidget(QLabel("→")); l1.addWidget(self.to_box)

        self.status_lbl = QLabel("Aguardando...")
        self.status_lbl.setStyleSheet("color: rgba(255,255,255,120); font-size: 10px; padding-left: 8px;")
        l1.addWidget(self.status_lbl)
        self.peak_lbl = QLabel("🔈 -")
        self.peak_lbl.setStyleSheet("color: rgba(100,200,100,150); font-size: 10px; padding-left: 8px;")
        l1.addWidget(self.peak_lbl)
        l1.addStretch()
        self.xbtn = QPushButton("✕")
        self.xbtn.setFixedSize(22, 22)
        self.xbtn.setStyleSheet("background: rgba(220,60,60,180); color: white; border-radius:11px; font-weight:bold;")
        self.xbtn.clicked.connect(self.close_app)
        l1.addWidget(self.xbtn)
        self.ctrl_bar.addLayout(l1)

        l2 = QHBoxLayout()
        btn_s = "QPushButton { background: rgba(70,90,110,180); color: #fff; font-size: 10px; border-radius:4px; padding: 4px 8px; border:none; }"
        self.src_btn = QComboBox()
        self.src_btn.setStyleSheet(combo_s)
        self.populate_sources()
        self.src_btn.currentIndexChanged.connect(self.on_src_change)
        l2.addWidget(self.src_btn)
        self.auto_btn = QPushButton("Auto")
        self.auto_btn.setStyleSheet("background: rgba(100,150,220,180); color: #fff; font-size: 10px; border-radius:4px; padding: 4px; border:none;")
        self.auto_btn.clicked.connect(self.do_auto_detect)
        l2.addWidget(self.auto_btn)
        self.fplus = QPushButton("A+"); self.fplus.setStyleSheet(btn_s); self.fplus.clicked.connect(lambda: self.change_font(2)); l2.addWidget(self.fplus)
        self.fminus = QPushButton("A-"); self.fminus.setStyleSheet(btn_s); self.fminus.clicked.connect(lambda: self.change_font(-2)); l2.addWidget(self.fminus)
        l2.addWidget(QLabel("Voz:"))
        self.vplus = QPushButton("V+"); self.vplus.setStyleSheet(btn_s); self.vplus.clicked.connect(lambda: self.change_vol(0.2)); l2.addWidget(self.vplus)
        self.vminus = QPushButton("V-"); self.vminus.setStyleSheet(btn_s); self.vminus.clicked.connect(lambda: self.change_vol(-0.2)); l2.addWidget(self.vminus)
        self.listen_btn = QPushButton("Ler Texto Agora"); self.listen_btn.setStyleSheet(btn_s); self.listen_btn.clicked.connect(self.read_current_text); l2.addWidget(self.listen_btn)
        self.auto_listen_btn = QPushButton("Auto-Leitura: OFF"); self.auto_listen_btn.setStyleSheet("background: rgba(100,150,220,180); color: #fff; font-size: 10px; border-radius:4px; padding: 4px; border:none;"); self.auto_listen_btn.clicked.connect(self.toggle_listening); l2.addWidget(self.auto_listen_btn)
        self.cbtn = QPushButton("Limpar"); self.cbtn.setStyleSheet(btn_s); self.cbtn.clicked.connect(self.clear_hist); l2.addWidget(self.cbtn)
        
        self.ctrl_bar.addLayout(l2)
        self.inner.addWidget(self.ctrl_widget)
        self.ctrl_widget.hide()

        self.hist = QPlainTextEdit()
        self.hist.setReadOnly(True)
        self.hist.setStyleSheet("background: transparent; border: none; color: white;")
        self.hist.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.hist.setFont(QFont("Inter", self.font_size, QFont.Weight.Bold))
        self.hist.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.inner.addWidget(self.hist)
        self.update_style(False)
        self.grip = QSizeGrip(self); self.grip.setFixedSize(12, 12)

    def update_style(self, active):
        bg = 160 if active else 50
        border = "rgba(255,255,255,30)" if active else "rgba(255,255,255,10)"
        self.box.setStyleSheet(f"#Box {{ background: rgba(10,10,15,{bg}); border: 1px solid {border}; border-radius:10px; }}")
        if active: self.ctrl_widget.show()
        else: self.ctrl_widget.hide()

    def on_timer(self):
        # Sempre no topo
        self.raise_()
        
        # Interatividade Ghost Mode (SHIFT)
        shift = QGuiApplication.queryKeyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        if shift:
            if self.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents):
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                self.hist.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                self.update_style(True); self.show()
        else:
            if not self.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents):
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                self.hist.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                self.update_style(False); self.show()

    def populate_sources(self):
        self.src_btn.blockSignals(True); self.src_btn.clear()
        save_src = self.config.get("audio_source", self.audio_worker.source)
        found = False; idx = 0
        for label, name in list_pw_sources():
            self.src_btn.addItem(label, userData=name)
            if name == save_src: self.src_btn.setCurrentIndex(idx); found = True
            idx += 1
        if found and save_src != self.audio_worker.source: self.audio_worker.change_source(save_src)
        self.src_btn.blockSignals(False)

    def on_src_change(self, i):
        if i < 0: return
        src = self.src_btn.itemData(i)
        self.audio_worker.change_source(src)
        self.config["audio_source"] = src
        ConfigManager.save(self.config)

    def do_auto_detect(self):
        active_source = self.audio_worker.auto_detect_active_source()
        self.config["audio_source"] = active_source
        ConfigManager.save(self.config); self.populate_sources()

    def update_langs(self):
        self.proc_worker.lang_from = self.from_box.itemData(self.from_box.currentIndex())
        self.proc_worker.lang_to = self.to_box.itemData(self.to_box.currentIndex())
        self.config["lang_from"] = self.proc_worker.lang_from
        self.config["lang_to"] = self.proc_worker.lang_to
        ConfigManager.save(self.config)

    def change_font(self, d):
        self.font_size = max(10, min(80, self.font_size + d))
        self.hist.setFont(QFont("Inter", self.font_size, QFont.Weight.Bold))
        self.config["font_size"] = self.font_size
        ConfigManager.save(self.config)

    def change_vol(self, d):
        self.tts_vol = max(0.1, min(2.0, self.tts_vol + d))
        self.config["tts_vol"] = self.tts_vol
        ConfigManager.save(self.config)

    def clear_hist(self): 
        self.hist.clear()
        while not self.proc_worker.audio_queue.empty():
            try: self.proc_worker.audio_queue.get_nowait()
            except: break

    def on_new_text(self, text):
        if text.startswith("__PEAK__:"):
            val = text.split(":")[1]
            try:
                fval = float(val)
                if fval < 0.001: self.peak_lbl.setText(f"🔈 {fval:.4f}"); self.peak_lbl.setStyleSheet("color: rgba(100,200,100,100); font-size: 10px; padding-left: 8px;")
                else: self.peak_lbl.setText(f"🔊 {fval:.4f}"); self.peak_lbl.setStyleSheet("color: rgba(50,255,50,255); font-weight: bold; font-size: 10px; padding-left: 8px;")
            except: pass
            return
            
        if text.startswith("__IS_FINAL__:"):
            msg_parts = text.split(":", 1)[1].split("|", 1)
            is_fin = msg_parts[0] == "True"
            content = msg_parts[1]
            
            # Se já tínhamos um texto parcial na tela, removemos para colocar o novo
            if getattr(self, "_has_partial", False):
                cursor = self.hist.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                self._has_partial = False

            # Adiciona o novo texto
            self.hist.appendPlainText(content)
            self._has_partial = not is_fin
            
            # Controle de histórico
            full_text = self.hist.toPlainText()
            if len(full_text) > MAX_HIST_CHARS:
                truncated = full_text[-MAX_HIST_CHARS:]
                idx = truncated.find("\n")
                if idx != -1: truncated = truncated[idx+1:]
                self.hist.setPlainText(truncated)

            self.hist.moveCursor(QTextCursor.MoveOperation.End)
            if is_fin and self.is_listening:
                subprocess.Popen(["/home/porco/.local/bin/piper_read.sh", "1.3", content, str(self.tts_vol)])
            return

    def close_app(self):
        self.audio_worker.running = False
        self.proc_worker.running = False
        if self.audio_worker._proc:
            try: self.audio_worker._proc.terminate()
            except: pass
        QApplication.quit()
        os._exit(0)

    def toggle_listening(self):
        self.is_listening = not self.is_listening
        if self.is_listening:
            self.auto_listen_btn.setText("Auto-Leitura: ON")
            self.auto_listen_btn.setStyleSheet("background: rgba(220,60,60,180); color: #fff; font-size: 10px; border-radius:4px; padding: 4px; border:none;")
        else:
            self.auto_listen_btn.setText("Auto-Leitura: OFF")
            self.auto_listen_btn.setStyleSheet("background: rgba(100,150,220,180); color: #fff; font-size: 10px; border-radius:4px; padding: 4px; border:none;")
            subprocess.Popen(["pkill", "-f", "piper-tts"])
            subprocess.Popen(["pkill", "-u", os.environ.get("USER", "porco"), "-x", "aplay"])

    def read_current_text(self):
        text = self.hist.toPlainText().strip()
        if text:
            subprocess.Popen(["pkill", "-f", "piper-tts"])
            subprocess.Popen(["/home/porco/.local/bin/piper_read.sh", "1.3", text, str(self.tts_vol)])

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(e.position().toPoint())
            if child is self.handle or (child is not None and child.parent() is self.handle):
                self._dragging = True
                self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if self._dragging: self.move(e.globalPosition().toPoint() - self._drag_pos)
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
    audio_queue = queue.Queue()
    audio_worker = AudioWorker(audio_queue, get_best_audio_source())
    proc_worker = ProcessorWorker(audio_queue)
    win = OverlayWindow(audio_worker, proc_worker)
    proc_worker.new_segment.connect(win.on_new_text)
    audio_worker.status.connect(win.status_lbl.setText)
    audio_worker.start()
    proc_worker.start()
    win.show()
    sys.exit(app.exec())
