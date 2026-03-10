import sys, os, json, socket, threading, time, subprocess, concurrent.futures
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QFrame, QComboBox,
                             QScrollArea, QColorDialog, QSystemTrayIcon, QMenu, QSizeGrip)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, pyqtSlot, QMetaObject, Q_ARG, QPoint
from PyQt6.QtGui import QFont, QIcon, QColor, QAction, QPixmap, QPainter, QPen, QBrush
from deep_translator import GoogleTranslator

DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.expanduser("~/.config/porco-translator/config.json")
UDP_IP, UDP_PORT_LISTENER, UDP_PORT_UI = "127.0.0.1", 50135, 50134
HISTORY_PATH = os.path.expanduser("~/.config/porco-translator/history.json")
ASH_DIM, BG_DARK, BG_PANEL, BONE = "#606060", "rgba(13, 13, 13, 220)", "rgba(20, 20, 20, 240)", "#e0e0e0"
ICON_PATH = os.path.join(DIR, "porco.svg")

class ConfigManager:
    @staticmethod
    def load():
        if os.path.exists(CONFIG_PATH):
            try: return json.load(open(CONFIG_PATH, 'r'))
            except: pass
        return {}
    @staticmethod
    def save(cfg):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        try: json.dump(cfg, open(CONFIG_PATH, 'w'))
        except: pass

def list_pw_sources():
    try:
        out = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
        found = []
        for line in out.strip().split('\n'):
            parts = line.split('\t')
            if len(parts) >= 2:
                n = parts[1]
                l = n.replace("alsa_input.", "").replace("alsa_output.", "").replace(".analog-stereo", "").replace(".monitor", "")
                label = f"🎙️ {l[:15]}" if "input" in n else f"🖥️ {l[:15]}"
                found.append((label, n))
        return found
    except: return [("Padrão", "default")]

class UdpReceiver(QObject):
    signal_text = pyqtSignal(dict); signal_peak = pyqtSignal(float)
    def __init__(self): super().__init__(); self.running = True
    def listen(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("", UDP_PORT_UI)); sock.settimeout(1.0)
        while self.running:
            try:
                data, _ = sock.recvfrom(4096)
                msg = json.loads(data.decode('utf-8'))
                if msg["type"] == "text": self.signal_text.emit(msg)
                elif msg["type"] == "peak": self.signal_peak.emit(msg["value"])
            except: continue
        sock.close()

class ResizeGrip(QWidget):
    """Bolinha no canto inferior direito — resize manual com grabMouse."""
    SIZE = 22

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setToolTip("Arrastar para redimensionar")
        self._drag = False
        self._start_gpos = None
        self._start_geom = None
        self.raise_()

    def reposition(self):
        p = self.parent()
        self.move(p.width() - self.SIZE - 2, p.height() - self.SIZE - 2)
        self.raise_()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = QColor("#ffffff") if self._drag else QColor("#00ffaa")
        painter.setPen(QPen(QColor("#404040"), 1))
        painter.setBrush(QBrush(col))
        r = self.SIZE - 4
        painter.drawEllipse(2, 2, r, r)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            self._start_gpos = e.globalPosition().toPoint()
            g = self.parent().geometry()
            self._start_geom = (g.x(), g.y(), g.width(), g.height())
            self.grabMouse()   # captura todos eventos mesmo fora do widget
            self.update()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag and self._start_gpos is not None:
            delta = e.globalPosition().toPoint() - self._start_gpos
            x, y, w, h = self._start_geom
            new_w = max(180, w + delta.x())
            new_h = max(100, h + delta.y())
            self.parent().setGeometry(x, y, new_w, new_h)
            e.accept()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self._drag:
            self._drag = False
            self.releaseMouse()
            self.update()
            if hasattr(self.parent(), 'save_cfg'):
                self.parent().save_cfg()
            e.accept()

class ExternalComboBox(QPushButton):

    currentIndexChanged = pyqtSignal()
    def __init__(self, items, initial_data, parent=None):
        super().__init__(parent); self.items, self._current_data = items, initial_data
        for l, d in items: 
            if d == initial_data: self.setText(l); break
        self.clicked.connect(self.show_popup)
    def itemData(self): return self._current_data
    def show_popup(self):
        m = QMenu(self); m.setStyleSheet(f"QMenu {{ background: {BG_PANEL}; color: {BONE}; }} QMenu::item:selected {{ background: {ASH_DIM}; }}")
        for l, d in self.items: a = m.addAction(l); a.setData(d)
        res = m.exec(self.mapToGlobal(self.rect().bottomLeft()))
        if res: self._current_data = res.data(); self.setText(res.text()); self.currentIndexChanged.emit()

class TranslatorUI(QWidget):
    def __init__(self):
        super().__init__()
        self.config = ConfigManager.load(); self.ghost_mode = self.config.get("ghost_mode", False)
        self.text_color = self.config.get("text_color", "#00ffaa"); self.font_size = self.config.get("font_size", 22)
        self.active_label = None; self.history_labels = []; self.last_text = ""
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Resize logic
        self.resize_margin = 10
        self.resizing = False
        self.resize_edge = None
        self.setMouseTracking(True)
        
        # Real-time state
        self.last_translated_text = ""
        self.pending_translation = None
        self.translation_timer = QTimer(); self.translation_timer.setSingleShot(True); self.translation_timer.timeout.connect(self.process_deferred_translation)
        
        # UI Initialized
        self.init_tray()
        self.live_eng = QLabel("...") # Fixed attribute
        self.setup_window()
        
        self.receiver = UdpReceiver()
        self.receiver.signal_text.connect(self.on_text); self.receiver.signal_peak.connect(self.on_peak)
        threading.Thread(target=self.receiver.listen, daemon=True).start()
        
        # Aplica o modo inicial (Ghost/Edit) de forma estável no boot
        self.apply_window_mode()
        
        # Load history
        QTimer.singleShot(200, self.load_history)
        
        QTimer(self, timeout=self.raise_, interval=5000).start()
        QTimer.singleShot(1000, self.do_auto_detect) # Auto-detect audio source 1s after start

    def init_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(ICON_PATH) if os.path.exists(ICON_PATH) else QIcon())
        m = QMenu(); m.setStyleSheet(f"QMenu {{ background: {BG_PANEL}; color: {BONE}; }} QMenu::item:selected {{ background: {ASH_DIM}; }}")
        self.act = QAction("Modo Edição", self); self.act.setCheckable(True); self.act.setChecked(not self.ghost_mode)
        self.act.triggered.connect(self.toggle_edit_mode)
        m.addAction(self.act); m.addSeparator(); m.addAction("Sair", self.close_all)
        self.tray.setContextMenu(m); self.tray.show()

    def setup_window(self):
        if self.layout():
            while self.layout().count():
                item = self.layout().takeAt(0)
                if item.widget(): item.widget().deleteLater()
        else:
            self.main_layout = QVBoxLayout(self)
            self.main_layout.setContentsMargins(0, 0, 0, 0)

        # Window flags: always on top + bypass WM (needed for fullscreen game overlay)
        f = (Qt.WindowType.FramelessWindowHint
             | Qt.WindowType.WindowStaysOnTopHint
             | Qt.WindowType.Tool
             | Qt.WindowType.X11BypassWindowManagerHint)
        if self.ghost_mode:
            f |= Qt.WindowType.WindowTransparentForInput
        self.setWindowFlags(f)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground) # Performance optimization

        self.cont = QFrame()
        self.main_layout.addWidget(self.cont)
        if not self.ghost_mode:
            self.cont.setStyleSheet(f"background: {BG_DARK}; border: 1px solid {ASH_DIM}; border-radius: 4px;")
        else:
            self.cont.setStyleSheet("background: transparent; border: none;")

        l = QVBoxLayout(self.cont)
        l.setContentsMargins(8, 8, 8, 8)
        
        # Bloco de controles (escondido no modo compacto)
        self.ctrl_widget = QWidget()
        self.ctrl_widget.setStyleSheet("background: transparent;")
        ctrl_l = QVBoxLayout(self.ctrl_widget)
        ctrl_l.setContentsMargins(0,0,0,4)
        ctrl_l.setSpacing(4)

        c = QWidget(); cl = QHBoxLayout(c); cl.setContentsMargins(0,0,0,0)
        st = QLabel("✏️ MODO EDIÇÃO"); st.setStyleSheet("color: #00ff88; font-weight: bold; font-size: 10px;")
        p1 = QPushButton("a-"); p1.setFixedSize(24,24); p1.clicked.connect(lambda: self.change_font(-2))
        p2 = QPushButton("A+"); p2.setFixedSize(24,24); p2.clicked.connect(lambda: self.change_font(2))
        cp = QPushButton("🎨"); cp.setFixedSize(24,24); cp.clicked.connect(self.pick_color)
        p_clr = QPushButton("🧹"); p_clr.setFixedSize(24,24); p_clr.clicked.connect(self.clear_history)
        p_clr.setToolTip("Limpar Histórico de Texto")
        cl.addWidget(st); cl.addStretch(); cl.addWidget(p1); cl.addWidget(p2); cl.addWidget(cp); cl.addWidget(p_clr)
        ctrl_l.addWidget(c)

        c2 = QWidget(); c2l = QHBoxLayout(c2); c2l.setContentsMargins(0,0,0,0)
        langs = [("English 🇺🇸", "en"), ("Português 🇧🇷", "pt"), ("Español 🇪🇸", "es"), ("Français 🇫🇷", "fr"), ("Deutsch 🇩🇪", "de"), ("Italiano 🇮🇹", "it"), ("日本語 🇯🇵", "ja"), ("한국어 🇰🇷", "ko"), ("中文 🇨🇳", "zh-CN"), ("Русский 🇷🇺", "ru")]
        self.b1 = ExternalComboBox(langs, self.config.get("lang_from", "en"))
        self.b2 = ExternalComboBox(langs, self.config.get("lang_to", "pt"))
        c2l.addWidget(QLabel("🔈")); c2l.addWidget(self.b1); c2l.addWidget(QLabel("→")); c2l.addWidget(self.b2)

        self.s = QComboBox(); self.s.setFixedWidth(140); self.s.setStyleSheet("font-size: 10px;")
        for lb, d in list_pw_sources(): self.s.addItem(lb, d)
        idx = self.s.findData(self.config.get("audio_source", "default"))
        if idx >= 0: self.s.setCurrentIndex(idx)
        c2l.addWidget(self.s)

        self.scan_btn = QPushButton("🔍"); self.scan_btn.setFixedSize(24,24); self.scan_btn.clicked.connect(self.do_auto_detect)
        c2l.addWidget(self.scan_btn)
        self.p_lbl = QLabel("🔈"); self.p_lbl.setStyleSheet(f"color: {ASH_DIM}; font-size: 10px;")
        c2l.addWidget(self.p_lbl)
        ctrl_l.addWidget(c2)
        self.b1.currentIndexChanged.connect(self.save_cfg); self.b2.currentIndexChanged.connect(self.save_cfg); self.s.currentIndexChanged.connect(self.save_cfg)

        l.addWidget(self.ctrl_widget)
        # Respeita ghost_mode na abertura
        if self.ghost_mode:
            self.ctrl_widget.hide()

        self.sc = QScrollArea(); self.sc.setWidgetResizable(True); self.sc.setStyleSheet("background: transparent; border: none;")
        self.sc.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if self.ghost_mode else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.hw = QWidget(); self.hl = QVBoxLayout(self.hw); self.hl.setAlignment(Qt.AlignmentFlag.AlignTop); self.hl.setContentsMargins(0,0,0,0)
        
        # Dual-Label setup
        self.live_eng.setFont(QFont("Inter", max(10, self.font_size - 4)))
        self.live_eng.setStyleSheet(f"color: {ASH_DIM}; font-style: italic;"); self.live_eng.setWordWrap(True)
        self.hl.addWidget(self.live_eng)
        
        self.sc.setWidget(self.hw); l.addWidget(self.sc)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, self.ghost_mode)

        g = self.config.get("geometry", [100, 100, 500, 300]); self.setGeometry(g[0], g[1], g[2], g[3])
        # O grip agora é criado sob demanda ou atualizado no toggle_edit_mode
        self.start_line()

    def do_auto_detect(self):
        # Só auto-detecta se estiver no "Padrão" (default)
        if self.config.get("audio_source", "default") != "default":
            return
        try:
            df = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
            target = df + ".monitor"; out = subprocess.check_output(["pactl", "list", "short", "sources"], text=True)
            for line in out.strip().split('\n'):
                parts = line.split('\t')
                if len(parts) >= 2:
                    name = parts[1]; status = parts[-1] if len(parts) > 5 else ""
                    if ".monitor" in name and "RUNNING" in status and "easyeffects" not in name.lower():
                        target = name; break
            ix = self.s.findData(target)
            if ix >= 0: self.s.setCurrentIndex(ix)
            self.save_cfg()
        except: pass

    def change_font(self, d):
        self.font_size = max(6, min(70, self.font_size + d)); self.save_cfg()
        if self.active_label: self.active_label.setFont(QFont("Inter", self.font_size))
        for lb in self.history_labels: lb.setFont(QFont("Inter", self.font_size))
        self.live_eng.setFont(QFont("Inter", max(6, self.font_size-4)))

    def clear_history(self):
        """Remove todos os labels do histórico e limpa o arquivo."""
        # Remove labels da lista e deleta widgets do layout
        for lb in self.history_labels:
            lb.deleteLater()
        self.history_labels = []
        
        # O active_label é resetado para vazio
        if self.active_label:
            self.active_label.setText(" ")
            
        # Limpa o arquivo de histórico físico
        try:
            with open(HISTORY_PATH, "w") as f:
                json.dump([], f)
        except: pass
        
        self.sc.verticalScrollBar().setValue(0)

    def apply_window_mode(self):
        """Aplica as flags de janela baseadas no modo ghost/edit. Chamado apenas no início para estabilidade."""
        # Se for modo Ghost, usa flags agressivas para sumir da barra e ficar transparente
        f = (Qt.WindowType.FramelessWindowHint
             | Qt.WindowType.WindowStaysOnTopHint
             | Qt.WindowType.Tool)
             
        if self.ghost_mode:
            f |= Qt.WindowType.X11BypassWindowManagerHint | Qt.WindowType.WindowTransparentForInput
            
        self.setWindowFlags(f)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, self.ghost_mode)
        
        # Configura visibilidade dos controles conforme o modo carregado
        if not self.ghost_mode:
            if not hasattr(self, 'grip'):
                self.grip = ResizeGrip(self)
            self.grip.reposition()
            self.grip.show()
            self.ctrl_widget.show()
            self.cont.setStyleSheet(f"background: {BG_DARK}; border: 1px solid {ASH_DIM}; border-radius: 4px;")
        else:
            if hasattr(self, 'grip'):
                self.grip.hide()
            self.ctrl_widget.hide()
            self.cont.setStyleSheet("background: transparent; border: none;")

    def toggle_edit_mode(self, checked):
        """Apenas salva a preferência e avisa o usuário. Troca de flags dinâmica causava crash."""
        self.ghost_mode = not checked
        self.config["ghost_mode"] = self.ghost_mode
        self.save_cfg()
        
        # Em vez de mudar as flags agora, avisamos o usuário
        msg_txt = "𝗠𝗼𝗱𝗼 𝗘𝗱𝗶𝗰̧𝗮̃𝗼 𝘀𝗮𝗹𝘃𝗼! Reinicie o Tradutor para aplicar." if checked else "𝗠𝗼𝗱𝗼 𝗚𝗵𝗼𝘀𝘁 𝘀𝗮𝗹𝘃𝗼! Reinicie o Tradutor para aplicar."
        
        # Tenta mostrar na própria UI como uma mensagem de sistema
        if self.active_label:
            self.on_text({"text": f"SYSTEM: {msg_txt}", "is_final": True})
            
        # Mostra notificação do sistema
        self.tray.showMessage("Porco Translator", msg_txt, QSystemTrayIcon.MessageIcon.Information, 5000)
        
        # Atualiza o estado visual do botão no menu da bandeja para o usuário ter feedback
        self.act.setChecked(checked)

    def save_cfg(self):
        if not hasattr(self, 'b1'): return
        self.config.update({
            "lang_from": self.b1.itemData(), 
            "lang_to": self.b2.itemData(), 
            "audio_source": self.s.currentData(), 
            "ghost_mode": self.ghost_mode, 
            "font_size": self.font_size,
            "text_color": self.text_color
        })
        r = self.geometry(); self.config["geometry"] = [r.x(), r.y(), r.width(), r.height()]; ConfigManager.save(self.config)
        msg = {"type": "config", "lang_from": self.b1.itemData(), "audio_source": self.s.currentData()}
        try: self.udp_sock.sendto(json.dumps(msg).encode('utf-8'), (UDP_IP, UDP_PORT_LISTENER))
        except: pass

    def on_text(self, m):
        t, f = m.get("text", ""), m.get("is_final", False)
        if not t: return
        self.live_eng.setText(f"ENG: {t}")
        
        # Garante que temos um label ativo para a tradução aparecer
        if not self.active_label:
            self.start_line()
            
        if t != self.last_text:
            self.last_text = t
            self.pending_translation = (t, f)
            self.translation_timer.start(250)

    def process_deferred_translation(self):
        if self.pending_translation:
            t, f = self.pending_translation
            self.executor.submit(self.translate_bg, t, f)
            self.pending_translation = None

    def translate_bg(self, t, f):
        source_lang = self.config.get("lang_from", "en")
        target_lang = self.config.get("lang_to", "pt")
        try: 
            res = GoogleTranslator(source=source_lang, target=target_lang).translate(t)
        except: 
            res = t
        QMetaObject.invokeMethod(self, "update_ui", Qt.ConnectionType.QueuedConnection, Q_ARG(str, res), Q_ARG(bool, f))

    @pyqtSlot(str, bool)
    def update_ui(self, t, f):
        if self.active_label: 
            self.active_label.setText(t)
            if f:
                self.live_eng.setText("...")
                self.start_line()
            self.sc.verticalScrollBar().setValue(self.sc.verticalScrollBar().maximum())
            self.save_history()

    def on_peak(self, v):
        if hasattr(self, 'p_lbl'):
            if v > 0.01: self.p_lbl.setText("🔊"); self.p_lbl.setStyleSheet("color: #00ffaa; font-weight: bold;")
            else: self.p_lbl.setText("🔈"); self.p_lbl.setStyleSheet(f"color: {ASH_DIM};")

    def start_line(self, text=" "):
        if self.active_label: self.history_labels.append(self.active_label)
        l = QLabel(text); l.setFont(QFont("Inter", self.font_size)); l.setStyleSheet(f"color: {self.text_color}; font-weight: bold;"); l.setWordWrap(True)
        self.hl.addWidget(l); self.active_label = l
        if len(self.history_labels) > 500: self.history_labels.pop(0).deleteLater()

    def save_history(self):
        h = [lb.text() for lb in self.history_labels if lb.text().strip()]
        if self.active_label and self.active_label.text().strip(): h.append(self.active_label.text())
        try:
            with open(HISTORY_PATH, "w") as f: json.dump(h[-500:], f)
        except: pass

    def load_history(self):
        if not os.path.exists(HISTORY_PATH): return
        try:
            h = json.load(open(HISTORY_PATH, "r"))
            for t in h:
                self.start_line(t)
            self.start_line() # Empty active line
        except: pass

    def pick_color(self):
        d = QColorDialog(QColor(self.text_color), self)
        if d.exec(): self.text_color = d.selectedColor().name(); self.save_cfg(); self.active_label.setStyleSheet(f"color: {self.text_color}; font-weight: bold;")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, 'grip'):
            self.grip.reposition()
        self.save_cfg()

    # ── Resize & Move ─────────────────────────────────────────────────────────
    # ── Mover e Redimensionar ──────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if self.ghost_mode: return
        if e.button() == Qt.MouseButton.LeftButton:
            # Só permite arrastar a janela se clicar no bloco de controles (barra superior)
            # ou em áreas que não sejam os labels de texto para evitar cliques acidentais
            self.dp = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self.ghost_mode: return
        if e.buttons() == Qt.MouseButton.LeftButton and hasattr(self, 'dp'):
            self.move(e.globalPosition().toPoint() - self.dp)
            e.accept()

    def mouseReleaseEvent(self, e):
        if hasattr(self, 'dp'):
            delattr(self, 'dp')
        self.save_cfg()
        e.accept()

    def close_all(self): subprocess.call(["pkill", "-9", "-f", "porco_"]); sys.exit(0)

if __name__ == "__main__":
    app = QApplication(sys.argv); app.setQuitOnLastWindowClosed(False)
    w = TranslatorUI(); w.show(); sys.exit(app.exec())
