# PorcoTranslator 🐽🕹️

**PorcoTranslator** is an ultra-low-latency real-time audio translator designed for gamers and power users. It captures system audio (using PipeWire), transcribes it using **Faster-Whisper (OpenAI)** via GPU acceleration, and translates it to Portuguese using **Argos Translate**.

The interface is a sleek, "Ghost Mode" overlay that stays on top of your game without interfering with clicks unless the **Shift** key is held.

## ✨ Features

- **Conversational Streaming**: Translations appear as people speak, with no long pauses.
- **Ghost Mode**: Invisible to clicks by default; hold **Shift** to move, resize, or interact.
- **AI-Powered**: Uses NVIDIA GPU acceleration for near-instant response.
- **Narração (TTS)**: Integration with Piper-TTS to read translations in a customized narrator voice.
- **Smart Audio Detection**: Automatically identifies active PipeWire sinks and monitors.
- **History & Scroll**: Keep track of the conversation with a scrollable history.

## 🛠️ Requirements

- **OS**: Arch Linux (CachyOS, Manjaro) and RPM-based systems (Fedora, RHEL, OpenSUSE).
- **Audio System**: PipeWire
- **Hardware**: NVIDIA GPU (recommended for CUDA acceleration)
- **Packages**:
  - `python`
  - `pipewire`, `pipewire-audio`, `pactl`
  - `piper-tts` (AUR/Bin)
  - `ffmpeg`

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
