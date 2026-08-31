# Porco Translator 🐽

Tradutor em tempo real para jogos, vídeos e filmes. Captura áudio via PipeWire, transcreve com Faster-Whisper local usando GPU e traduz para português usando deep-translator.

## Novidades:
- **Modo Ghost/Edição**: Alterne entre interface interativa e apenas texto transparente.
- **Resize Grip**: Bolinha no canto inferior direito para redimensionar facilmente.
- **Always-on-Top**: Funciona acima de jogos em tela cheia (X11).
- **Limpar Histórico**: Botão �� para limpar as traduções acumuladas.
- **Fontes Flexíveis**: Suporta tamanhos bem pequenos (6px+).

## Instalação:
1. `chmod +x install.sh`
2. `./install.sh` (O instalador perguntará onde colocar os arquivos).

- **Confirmed streaming history**: Stable blocks appear during continuous speech and are appended permanently like film credits.
- **Translation fallback**: Uses MyMemory for short live blocks and Google as fallback; a failed translation is never replaced silently by the original language.
- **Ghost Mode**: Invisible to clicks by default; hold **Shift** to move, resize, or interact.
- **AI-Powered**: Uses NVIDIA GPU acceleration for near-instant response.
- **Narração (TTS)**: Integration with Piper-TTS to read translations in a customized narrator voice.
- **Smart Audio Detection**: Automatically identifies active PipeWire sinks and monitors.
- **History & Scroll**: Keep track of the conversation with a scrollable history.
- **Bounded latency**: Old audio is discarded when inference is slower than real time, preventing an ever-growing delay while keeping confirmed lines ordered.
- **Recognition quality**: Uses `small.en` by default for English speech and falls back to `base.en`/`tiny.en`; set `PORCO_WHISPER_MODEL` to override it. The short streaming window keeps latency bounded.

## 🛠️ Requirements

- **OS**: Arch Linux (CachyOS, Manjaro) and RPM-based systems (Fedora, RHEL, OpenSUSE).
- **Audio System**: PipeWire
- **Hardware**: NVIDIA GPU (recommended for CUDA acceleration)
- **Packages**:
  - `python`
  - `pipewire`, `pipewire-audio`, `pactl`
  - `piper-tts` (AUR/Bin, optional TTS)
  - `ffmpeg` (optional; faster-whisper decodes audio through PyAV)
  - CUDA 12 + cuDNN 9 for GPU inference

## 🚀 Installation

### 1. Clone the repository
```bash
git clone https://github.com/jporco/porco-translator.git
cd porco-translator
```

### 2. Run the Installer
The new interactive `install.sh` will ask you where you want to install the application (default is `~/.local/share/porco-translator`). It will set up the virtual environment, install dependencies, and create a Desktop shortcut and an **Uninstaller**.
```bash
chmod +x install.sh
./install.sh
```

### 3. Uninstalling
If you ever want to remove the application, simply run the `uninstall.sh` script located in your installation folder.

### 3. Run the Translator
You can run it from your **Application Menu** (search for "Porco Translator") or via terminal:
```bash
/home/porco/.local/share/porco_translator/venv/bin/python porco_translator.py
```

## 🎮 Controls

- **No Key**: Window is a "ghost" (clicks pass through to the game).
- **Hold Shift**:
  - **Yellow Handle**: Drag to move.
  - **A+ / A-**: Increase/Decrease font size (auto-saved).
  - **V+ / V-**: Increase/Decrease TTS volume (auto-saved).
  - **Fonte (Source)**: Select audio input (Microphone or Monitor).
  - **Ouvir**: Toggle **Real-Time Speech**. When active (Red button), everything translated is spoken automatically.
  - **Limpar**: Clear history.

## 🤝 Credits
Created with 🐽 and AI for the Porco community.
