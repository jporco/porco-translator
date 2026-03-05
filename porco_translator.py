#!/home/porco/.local/share/porco_translator/venv/bin/python
"""
Porco Lingua v12.0 - Tradutor Ultra-Rápido (Paralelismo Real-Time)
"""
import sys, os, subprocess, threading, select, time, queue
import numpy as np
import argostranslate.translate
import argostranslate.package
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QPushButton, QFrame, QPlainTextEdit, QComboBox, QSizeGrip)
from PyQt6.QtCore import Qt, QPoint, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor, QGuiApplication
from faster_whisper import WhisperModel

# Configurações Globais
WHISPER_MODEL = "base.en"
DEVICE = "cuda"
COMPUTE = "int8"
RATE = 16000
COLLECT_SECS = 1  # Captura a cada 1 segundo para latência mínima

def get_installed_langs():
    try:
        langs = argostranslate.translate.get_installed_languages()
        found = []
        for l in langs:
            name = l.name
            if l.code == "pb": name = "Português (Brasil) 🇧🇷"
            if l.code == "pt": name = "Português (Portugal) 🇵🇹"
            found.append((name, l.code))
        return found
    except:
        return [("English", "en"), ("Português (Brasil)", "pb")]

def get_best_audio_source():
    try:
        res = subprocess.check_output(["pactl", "get-default-source"], text=True).strip()
        if not res:
            res = subprocess.check_output(["pactl", "list", "short", "sources"], text=True).split('\n')[0].split('\t')[1]
        return res
    except: return "auto"

def list_pw_sources():
    try:
        out = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
        found = []
        for line in out.strip().split('\n'):
            parts = line.split('\t')
            if len(parts) >= 2:
                name = parts[1]
                label = name.replace("alsa_input.", "🎙 ").replace("alsa_output.", "🔊 ").replace(".analog-stereo", "").replace(".monitor", " (Monitor)")
                found.append((label, name))
        return found
    except:
        return [("Padrão", get_best_audio_source())]

class AudioWorker(QThread):
    """
    Capturador de áudio puro. 
    Apenas captura e joga na fila para não bloquear o tempo real.
    """
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

    def run(self):
        CHUNK_BYTES = RATE * 2 * COLLECT_SECS
        while self.running:
            self.status.emit("Ouvindo...")
            with self._lock:
                try:
                    self._proc = subprocess.Popen(
                        ["pw-record", "--target", self.source,
                         "--format", "s16", "--rate", str(RATE), "--channels", "1", "-"],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
                    )
                except:
                    time.sleep(2); continue

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
                        # Overlap de 0.3s para contexto
                        overlap = int(RATE * 2 * 0.3)
                        buffer = buffer[CHUNK_BYTES-overlap:]
                        
                        # Adiciona na fila. Se a fila estiver grande, descarta o áudio velho.
                        if self.audio_queue.qsize() > 3:
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
    """
    Processador de IA (Whisper + Argos).
    Roda em paralelo ao capturador.
    """
    new_segment = pyqtSignal(str)

    def __init__(self, audio_queue, model):
        super().__init__()
        self.audio_queue = audio_queue
        self.model = model
        self.lang_from = "en"
        self.lang_to = "pb"
        self.running = True

    def run(self):
        while self.running:
            try:
                # Espera por áudio na fila
                raw = self.audio_queue.get(timeout=0.5)
                
                audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                peak = np.max(np.abs(audio))
                
                # VAD e Filtros de Sensibilidade
                if peak < 0.015: continue
                
                # Normalização suave
                if peak < 0.7: audio = audio * (0.7 / (peak + 1e-6))
                
                # Transcrição com Whisper
                segments, _ = self.model.transcribe(
                    audio, 
                    beam_size=3, # Menor beam para maior velocidade
                    language=self.lang_from, 
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=400),
                    no_speech_threshold=0.6,
                    compression_ratio_threshold=2.4
                )
                
                for seg in segments:
                    if seg.no_speech_prob < 0.5:
                        txt = seg.text.strip()
                        if txt and len(txt) > 2:
                            # Tradução Imediata com Argos
                            try:
                                translated = argostranslate.translate.translate(txt, self.lang_from, self.lang_to)
                                self.new_segment.emit(translated if translated else txt)
                            except:
                                self.new_segment.emit(txt)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Erro no Processador: {e}")

class OverlayWindow(QWidget):
    def __init__(self, audio_worker, proc_worker):
        super().__init__()
        self.audio_worker = audio_worker
        self.proc_worker = proc_worker
        self._dragging = False
        self._drag_pos = QPoint()
        self.font_size = 18
        self.tts_vol = 1.0
        self.initUI()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_modifiers)
        self.timer.start(100)

    def initUI(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.Tool)
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

        # Barra Superior
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
        for name, code in langs:
            self.from_box.addItem(name, userData=code)
            self.to_box.addItem(name, userData=code)
            if code == "en": self.from_box.setCurrentIndex(self.from_box.count()-1)
            if code == "pb": self.to_box.setCurrentIndex(self.to_box.count()-1)

        self.from_box.currentIndexChanged.connect(self.update_langs)
        self.to_box.currentIndexChanged.connect(self.update_langs)
        
        l1.addWidget(self.from_box)
        l1.addWidget(QLabel("→"))
        l1.addWidget(self.to_box)

        self.status_lbl = QLabel("Aguardando...")
        self.status_lbl.setStyleSheet("color: rgba(255,255,255,120); font-size: 10px; padding-left: 8px;")
        l1.addWidget(self.status_lbl)
        
        l1.addStretch()

        self.xbtn = QPushButton("✕")
        self.xbtn.setFixedSize(22, 22)
        self.xbtn.setStyleSheet("background: rgba(220,60,60,180); color: white; border-radius:11px; font-weight:bold;")
        self.xbtn.clicked.connect(self.close)
        l1.addWidget(self.xbtn)
        self.ctrl_bar.addLayout(l1)

        l2 = QHBoxLayout()
        btn_s = "QPushButton { background: rgba(70,90,110,180); color: #fff; font-size: 10px; border-radius:4px; padding: 4px 8px; border:none; }"
        
        self.src_btn = QComboBox()
        self.src_btn.setStyleSheet(combo_s)
        for label, name in list_pw_sources():
            self.src_btn.addItem(label, userData=name)
            if name == self.audio_worker.source: self.src_btn.setCurrentIndex(self.src_btn.count()-1)
        self.src_btn.currentIndexChanged.connect(lambda i: self.audio_worker.change_source(self.src_btn.itemData(i)))
        l2.addWidget(self.src_btn)

        l2.addWidget(QLabel("Fonte:"))
        self.fplus = QPushButton("A+")
        self.fplus.setStyleSheet(btn_s)
        self.fplus.clicked.connect(lambda: self.change_font(2))
        l2.addWidget(self.fplus)
        self.fminus = QPushButton("A-")
        self.fminus.setStyleSheet(btn_s)
        self.fminus.clicked.connect(lambda: self.change_font(-2))
        l2.addWidget(self.fminus)

        l2.addWidget(QLabel("Voz:"))
        self.vplus = QPushButton("V+")
        self.vplus.setStyleSheet(btn_s)
        self.vplus.clicked.connect(lambda: self.change_vol(0.2))
        l2.addWidget(self.vplus)
        self.vminus = QPushButton("V-")
        self.vminus.setStyleSheet(btn_s)
        self.vminus.clicked.connect(lambda: self.change_vol(-0.2))
        l2.addWidget(self.vminus)

        self.wbtn = QPushButton("Ouvir Última")
        self.wbtn.setStyleSheet(btn_s)
        self.wbtn.clicked.connect(self.read_last)
        l2.addWidget(self.wbtn)

        self.cbtn = QPushButton("Limpar")
        self.cbtn.setStyleSheet(btn_s)
        self.cbtn.clicked.connect(self.clear_hist)
        l2.addWidget(self.cbtn)

        self.ctrl_bar.addLayout(l2)
        self.inner.addWidget(self.ctrl_widget)
        self.ctrl_widget.hide()

        # Histórico
        self.hist = QPlainTextEdit()
        self.hist.setReadOnly(True)
        self.hist.setStyleSheet("background: transparent; border: none; color: white;")
        self.hist.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.hist.setFont(QFont("Inter", self.font_size, QFont.Weight.Bold))
        self.inner.addWidget(self.hist)

        self.update_style(False)
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(12, 12)

    def update_style(self, active):
        bg = 160 if active else 50
        border = "rgba(255,255,255,30)" if active else "rgba(255,255,255,10)"
        self.box.setStyleSheet(f"#Box {{ background: rgba(10,10,15,{bg}); border: 1px solid {border}; border-radius:10px; }}")
        if active: self.ctrl_widget.show()
        else: self.ctrl_widget.hide()

    def check_modifiers(self):
        shift = QGuiApplication.queryKeyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        if shift:
            if self.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents):
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
                self.update_style(True)
        else:
            if not self.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents):
                self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                self.update_style(False)

    def update_langs(self):
        self.proc_worker.lang_from = self.from_box.itemData(self.from_box.currentIndex())
        self.proc_worker.lang_to = self.to_box.itemData(self.to_box.currentIndex())

    def change_font(self, d):
        self.font_size = max(10, min(80, self.font_size + d))
        self.hist.setFont(QFont("Inter", self.font_size, QFont.Weight.Bold))

    def change_vol(self, d):
        self.tts_vol = max(0.1, min(2.0, self.tts_vol + d))
        self.status_lbl.setText(f"Vol Voz: {self.tts_vol:.1f}")

    def clear_hist(self): 
        self.hist.clear()
        # Limpa a fila de áudio
        while not self.proc_worker.audio_queue.empty():
            try: self.proc_worker.audio_queue.get_nowait()
            except: break
        self.status_lbl.setText("Limpo!")

    def on_new_text(self, text):
        self.hist.appendPlainText(text)
        self.hist.moveCursor(QTextCursor.MoveOperation.End)

    def read_last(self):
        txt = self.hist.toPlainText().split('\n')[-1]
        if txt and len(txt) > 2:
            subprocess.Popen(["/home/porco/.local/bin/piper_read.sh", "1.3", txt, str(self.tts_vol)])

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(e.position().toPoint())
            if child is self.handle or (child is not None and child.parent() is self.handle):
                self._dragging = True
                self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
    def mouseMoveEvent(self, e):
        if self._dragging: self.move(e.globalPosition().toPoint() - self._drag_pos)
    def mouseReleaseEvent(self, e): self._dragging = False

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    splash = QLabel("Carregando Porco Lingua v12 (High Speed)...")
    splash.setWindowFlags(Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
    splash.setStyleSheet("background:#05050a; color:#fff; padding:30px; border-radius:15px; border:1px solid #333; font-weight:bold;")
    splash.show()
    app.processEvents()

    model = WhisperModel(WHISPER_MODEL, device=DEVICE, compute_type=COMPUTE)
    splash.close()

    audio_queue = queue.Queue()
    
    audio_worker = AudioWorker(audio_queue, get_best_audio_source())
    proc_worker = ProcessorWorker(audio_queue, model)
    
    win = OverlayWindow(audio_worker, proc_worker)
    
    proc_worker.new_segment.connect(win.on_new_text)
    audio_worker.status.connect(win.status_lbl.setText)
    
    audio_worker.start()
    proc_worker.start()
    
    win.show()
    sys.exit(app.exec())
