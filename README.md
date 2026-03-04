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

## 🛠️ Requirements (Arch Linux)

- **OS**: Arch Linux (or derivatives like CachyOS/Manjaro)
- **Audio System**: PipeWire
- **Hardware**: NVIDIA GPU (recommended for CUDA acceleration)
- **Packages**:
  - `python`
  - `pipewire`, `pipewire-audio`, `pactl`
  - `piper-tts-bin` (AUR)
  - `ffmpeg`

## 🚀 Installation

### 1. Clone the repository
```bash
git clone https://github.com/jporco/porco-translator.git
cd porco-translator
```

### 2. Run the Installer
The included `install.sh` will set up the virtual environment and install all Python dependencies.
```bash
chmod +x install.sh
./install.sh
```

### 3. Run the Translator
```bash
./porco_translator.py
```

## 🎮 Controls

- **No Key**: Window is a "ghost" (clicks pass through to the game).
- **Hold Shift**: 
  - **Yellow Handle**: Drag to move.
  - **A+ / A-**: Increase/Decrease font size.
  - **V+ / V-**: Increase/Decrease TTS volume.
  - **Linguagens**: Change input/output languages.
  - **Ouvir**: Trigger Narrator Voice (TTS) for the last translation.
  - **Limpar**: Clear history.

## 🤝 Credits
Created with 🐽 and AI for the Porco community.
