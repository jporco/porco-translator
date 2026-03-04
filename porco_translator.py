#!/home/porco/.local/share/porco_translator/venv/bin/python
"""
Porco Lingua v11.0 - Tradutor Conversacional (Streaming + Histórico + Controles)
"""
import sys, os, subprocess, threading, select, time
import numpy as np

# IA Safety & Performance
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

from PyQt6.QtWidgets import (QApplication, QLabel, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QFrame, QSizeGrip,
                             QComboBox, QPlainTextEdit)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QPoint, QTimer
from PyQt6.QtGui import QFont, QColor, QGuiApplication, QTextCursor
from faster_whisper import WhisperModel
import argostranslate.translate

# Configurações Globais
WHISPER_MODEL = "base.en"
DEVICE = "cuda"
COMPUTE = "int8"
RATE = 16000
COLLECT_SECS = 2  # Menor tempo para streaming mais rápido

# Mapeamento de Idiomas Instalados
def get_installed_langs():
    try:
        langs = argostranslate.translate.get_installed_languages()
        return [(l.name, l.code) for l in langs]
    except:
        return [("English", "en"), ("Portuguese", "pt")]

def get_best_audio_source():
    try:
        info = subprocess.check_output(["pactl", "info"], text=True)
        default_sink = ""
        for line in info.splitlines():
            if "Default Sink:" in line:
                default_sink = line.split(":")[1].strip()
        
        sources = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
        for line in sources.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                name = parts[1]
                if default_sink and name == f"{default_sink}.monitor":
                    return name
        for line in sources.splitlines():
            name = line.split()[1]
            if "easyeffects_sink.monitor" in name: return name
            if ".monitor" in name: return name
    except: pass
    return "easyeffects_sink.monitor"

def list_pw_sources():
    try:
        out = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
        found = []
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                name = parts[1]
                label = name.replace("alsa_input.", "🎙 ").replace("alsa_output.", "🔊 ").replace(".analog-stereo", "").replace(".monitor", " (Monitor)")
                found.append((label, name))
        return found
    except:
        return [("Padrão", get_best_audio_source())]

class AudioWorker(QThread):
    new_segment = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, model, source, lang_from="en"):
        super().__init__()
        self.model = model
        self.source = source
        self.lang_from = lang_from
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
                        ready, _, _ = select.select([p.stdout], [], [], 0.1)
                        if ready:
                            chunk = p.stdout.read(4096)
                            if chunk: buffer += chunk
                    
                    if len(buffer) >= CHUNK_BYTES:
                        raw = buffer[:CHUNK_BYTES]
                        # Mantemos 0.5s de overlap para contexto
                        overlap = int(RATE * 2 * 0.5)
                        buffer = buffer[CHUNK_BYTES-overlap:]
                        
                        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                        peak = np.max(np.abs(audio))
                        
                        if peak < 0.005: continue
                        
                        # Normalização suave
                        if peak < 0.8: audio = audio * (0.8 / (peak + 1e-6))
                        
                        segments, _ = self.model.transcribe(
                            audio, beam_size=5, language=self.lang_from, vad_filter=False
                        )
                        for seg in segments:
                            txt = seg.text.strip()
                            if txt and len(txt) > 2:
                                self.new_segment.emit(txt)
            except: pass
            with self._lock:
                if self._proc:
                    try: self._proc.terminate()
                    except: pass
                    self._proc = None
            time.sleep(0.3)

class OverlayWindow(QWidget):
    def __init__(self, worker):
        super().__init__()
        self.worker = worker
        self._dragging = False
        self._drag_pos = QPoint()
        self.font_size = 18
        self.tts_vol = 1.0
        self.lang_to = "pt"
        self.initUI()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_modifiers)
        self.timer.start(100)

    def initUI(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        
        self.setGeometry(100, 100, 800, 200) # Janela maior para histórico
        self.setMinimumSize(300, 100)

        self.box = QFrame(self)
        self.box.setObjectName("Box")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.box)

        self.inner = QVBoxLayout(self.box)
        self.inner.setContentsMargins(8, 8, 8, 8)
        self.inner.setSpacing(5)

        # Barra Superior (Controles)
        self.ctrl_widget = QWidget()
        self.ctrl_bar = QVBoxLayout(self.ctrl_widget)
        self.ctrl_bar.setContentsMargins(0, 0, 0, 0)
        self.ctrl_bar.setSpacing(4)

        # Linha 1: Arrastar, Linguagens, Sair
        l1 = QHBoxLayout()
        self.handle = QFrame()
        self.handle.setFixedSize(16, 16)
        self.handle.setStyleSheet("background: rgba(220,180,60,120); border-radius:3px;")
        l1.addWidget(self.handle)

        combo_s = "QComboBox { background: rgba(30,40,60,150); color: #ccc; font-size: 10px; border:none; border-radius:3px; padding: 2px; }"
        
        self.from_box = QComboBox()
        self.from_box.setStyleSheet(combo_s)
        self.to_box = QComboBox()
        self.to_box.setStyleSheet(combo_s)
        
        langs = get_installed_langs()
        for name, code in langs:
            self.from_box.addItem(name, userData=code)
            self.to_box.addItem(name, userData=code)
            if code == "en": self.from_box.setCurrentIndex(self.from_box.count()-1)
            if code == "pt": self.to_box.setCurrentIndex(self.to_box.count()-1)

        self.from_box.currentIndexChanged.connect(self.update_langs)
        self.to_box.currentIndexChanged.connect(self.update_langs)
        l1.addWidget(QLabel("De:"))
        l1.addWidget(self.from_box)
        l1.addWidget(QLabel("Para:"))
        l1.addWidget(self.to_box)
        
        l1.addStretch()

        self.xbtn = QPushButton("✕")
        self.xbtn.setFixedSize(20, 20)
        self.xbtn.setStyleSheet("background: rgba(200,50,50,150); color: white; border-radius:10px; font-weight:bold;")
        self.xbtn.clicked.connect(self.close)
        l1.addWidget(self.xbtn)
        self.ctrl_bar.addLayout(l1)

        # Linha 2: Fonte, Volume, Scroll, Áudio
        l2 = QHBoxLayout()
        btn_s = "QPushButton { background: rgba(60,80,100,150); color: #fff; font-size: 9px; border-radius:3px; padding: 3px 6px; border:none; }"
        
        # Audio Source
        self.src_btn = QComboBox()
        self.src_btn.setStyleSheet(combo_s)
        for label, name in list_pw_sources():
            self.src_btn.addItem(label, userData=name)
            if name == self.worker.source: self.src_btn.setCurrentIndex(self.src_btn.count()-1)
        self.src_btn.currentIndexChanged.connect(lambda i: self.worker.change_source(self.src_btn.itemData(i)))
        l2.addWidget(self.src_btn)

        # Font
        l2.addWidget(QLabel("Fonte:"))
        self.fplus = QPushButton("A+")
        self.fplus.setStyleSheet(btn_s)
        self.fplus.clicked.connect(lambda: self.change_font(2))
        l2.addWidget(self.fplus)
        self.fminus = QPushButton("A-")
        self.fminus.setStyleSheet(btn_s)
        self.fminus.clicked.connect(lambda: self.change_font(-2))
        l2.addWidget(self.fminus)

        # TTS Volume
        l2.addWidget(QLabel("Voz:"))
        self.vplus = QPushButton("V+")
        self.vplus.setStyleSheet(btn_s)
        self.vplus.clicked.connect(lambda: self.change_vol(0.1))
        l2.addWidget(self.vplus)
        self.vminus = QPushButton("V-")
        self.vminus.setStyleSheet(btn_s)
        self.vminus.clicked.connect(lambda: self.change_vol(-0.1))
        l2.addWidget(self.vminus)

        # Scroll
        l2.addWidget(QLabel("Rolar:"))
        self.s_up = QPushButton("▲")
        self.s_up.setStyleSheet(btn_s)
        self.s_up.clicked.connect(lambda: self.hist.verticalScrollBar().setValue(self.hist.verticalScrollBar().value() - 30))
        l2.addWidget(self.s_up)
        self.s_down = QPushButton("▼")
        self.s_down.setStyleSheet(btn_s)
        self.s_down.clicked.connect(lambda: self.hist.verticalScrollBar().setValue(self.hist.verticalScrollBar().value() + 30))
        l2.addWidget(self.s_down)

        l2.addStretch()
        
        self.wbtn = QPushButton("Ouvir")
        self.wbtn.setStyleSheet("background: rgba(40,160,80,150); color: white; border-radius:3px; padding:4px 10px; border:none; font-size:10px;")
        self.wbtn.clicked.connect(self.read_last)
        l2.addWidget(self.wbtn)

        self.cbtn = QPushButton("Limpar")
        self.cbtn.setStyleSheet(btn_s)
        self.cbtn.clicked.connect(self.clear_hist)
        l2.addWidget(self.cbtn)

        self.ctrl_bar.addLayout(l2)
        self.inner.addWidget(self.ctrl_widget)
        self.ctrl_widget.hide()

        # Histórico de Tradução
        self.hist = QPlainTextEdit()
        self.hist.setReadOnly(True)
        self.hist.setStyleSheet("background: transparent; border: none; color: rgba(255,255,255,180);")
        self.hist.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.hist.setFont(QFont("Inter", self.font_size, QFont.Weight.Bold))
        self.inner.addWidget(self.hist)

        self.update_style(False)
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(12, 12)

    def update_style(self, active):
        bg = 150 if active else 40
        self.box.setStyleSheet(f"#Box {{ background: rgba(5,5,10,{bg}); border: 1px solid rgba(255,255,255,10); border-radius:8px; }}")
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
        self.worker.lang_from = self.from_box.itemData(self.from_box.currentIndex())
        self.lang_to = self.to_box.itemData(self.to_box.currentIndex())

    def change_font(self, d):
        self.font_size = max(8, min(80, self.font_size + d))
        self.hist.setFont(QFont("Inter", self.font_size, QFont.Weight.Bold))

    def change_vol(self, d):
        self.tts_vol = max(0.1, min(2.0, self.tts_vol + d))
        print(f"Volume TTS: {self.tts_vol:.1f}")

    def clear_hist(self): self.hist.clear()

    def on_new_text(self, text):
        try:
            res = argostranslate.translate.translate(text, self.worker.lang_from, self.lang_to)
            self.hist.appendPlainText(res if res else text)
            self.hist.moveCursor(QTextCursor.MoveOperation.End)
        except: self.hist.appendPlainText(text)

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
    
    splash = QLabel("Carregando Porco Lingua v11...")
    splash.setWindowFlags(Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
    splash.setStyleSheet("background:#111; color:#fff; padding:20px; border-radius:10px;")
    splash.show()
    app.processEvents()
    
    try: model = WhisperModel(WHISPER_MODEL, device=DEVICE, compute_type=COMPUTE)
    except Exception as e:
        splash.setText(f"Erro IA: {e}")
        time.sleep(4); sys.exit(1)
    
    splash.close()
    
    worker = AudioWorker(model, get_best_audio_source())
    win = OverlayWindow(worker)
    worker.new_segment.connect(win.on_new_text)
    worker.start()
    
    app._worker = worker
    win.show()
    sys.exit(app.exec())
