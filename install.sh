#!/bin/bash
# Installer for PorcoTranslator on Arch Linux

echo "🐽 Iniciando instalador do PorcoTranslator..."

# 1. Dependências do Sistema
echo "📦 Verificando dependências do sistema..."
sudo pacman -S --needed --noconfirm python python-pip pipewire pipewire-audio ffmpeg libexif

# 2. Virtual Environment
VENV_PATH="./venv"
if [ ! -d "$VENV_PATH" ]; then
    echo "🐍 Criando ambiente virtual..."
    python -m venv "$VENV_PATH"
fi

# 3. Pip Install
echo "pip 📥 Instalando dependências do Python..."
"$VENV_PATH/bin/pip" install --upgrade pip
"$VENV_PATH/bin/pip" install -r requirements.txt

# 4. Configuração do Piper (opcional se já tiver)
if [ ! -f "/home/$USER/.local/bin/piper_read.sh" ]; then
    echo "🔊 Configurando piper_read.sh..."
    mkdir -p "/home/$USER/.local/bin"
    cp piper_read.sh "/home/$USER/.local/bin/"
    chmod +x "/home/$USER/.local/bin/piper_read.sh"
fi

# 5. Permissão de execução
chmod +x porco_translator.py

# Configuração de Ícone e Atalho Desktop
mkdir -p "$HOME/.local/share/icons"
mkdir -p "$HOME/.local/share/applications"
cp assets/icon.png "$HOME/.local/share/icons/porco_translator.png"

cat <<EOF > "$HOME/.local/share/applications/porco_translator.desktop"
[Desktop Entry]
Name=Porco Translator
Comment=Tradutor Real-Time com IA para Jogos e Vídeos
Exec=$BIN_PATH/porco_translator.py
Icon=porco_translator
Terminal=false
Type=Application
Categories=Utility;AudioVideo;
StartupNotify=true
EOF

chmod +x "$HOME/.local/share/applications/porco_translator.desktop"

echo -e "\e[1;32m✨ Instalação Completa!\e[0m"
echo -e "\e[1;34mUse o atalho 'Porco Translator' no seu menu de aplicativos ou rode: \e[1;37mporco-translator.py\e[0m"
