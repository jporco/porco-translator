#!/bin/bash
# Professional Installer for Porco Translator 🐽

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}🐽 Instalador do Porco Translator...${NC}"

# 1. Perguntar local de instalação
DEFAULT_INSTALL_DIR="$HOME/.local/share/porco-translator"
echo -e "\nOnde deseja instalar o Porco Translator?"
echo -e "1) Local padrão (${DEFAULT_INSTALL_DIR})"
echo -e "2) Digitar um local personalizado"
read -p "Opção [1/2]: " install_option

if [[ "$install_option" == "2" ]]; then
    read -p "Digite o caminho completo para a pasta de instalação: " CUSTOM_DIR
    INSTALL_DIR="${CUSTOM_DIR/#\~/$HOME}"
else
    INSTALL_DIR="$DEFAULT_INSTALL_DIR"
fi

# Criar pasta se não existir
mkdir -p "$INSTALL_DIR"
if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Erro ao criar a pasta $INSTALL_DIR. Verifique as permissões.${NC}"
    exit 1
fi

echo -e "${BLUE}📁 Preparando instalação em: $INSTALL_DIR${NC}"

# 2. Copiar arquivos para o local de destino
echo "📦 Copiando arquivos do projeto..."
rsync -av --exclude 'venv' --exclude '.git' --exclude '__pycache__' ./ "$INSTALL_DIR/"

cd "$INSTALL_DIR" || exit

# 3. Dependências do Sistema
echo -e "\n${BLUE}⚙️ Verificando dependências do sistema...${NC}"
if command -v pacman &> /dev/null; then
    sudo pacman -S --needed --noconfirm python python-pip pipewire pipewire-audio ffmpeg rsync wmctrl xdotool
elif command -v apt-get &> /dev/null; then
    sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv pipewire ffmpeg rsync wmctrl xdotool
fi

# 4. Virtual Environment no local de destino
VENV_PATH="$INSTALL_DIR/venv"
if [ ! -d "$VENV_PATH" ]; then
    echo "🐍 Criando ambiente virtual dedicado..."
    python3 -m venv "$VENV_PATH"
fi

# 5. Instalar dependências Python
echo "📥 Instalando dependências do Python..."
"$VENV_PATH/bin/pip" install --upgrade pip
"$VENV_PATH/bin/pip" install -r requirements.txt

# 6. Criar atalho Desktop
echo "🖥️ Criando atalho no menu de aplicativos..."
mkdir -p "$HOME/.local/share/icons"
mkdir -p "$HOME/.local/share/applications"
cp assets/porco.svg "$HOME/.local/share/icons/porco_translator.svg" 2>/dev/null || cp porco_translator.png "$HOME/.local/share/icons/porco_translator.png"

cat <<EOF_DESK > "$HOME/.local/share/applications/porco_translator.desktop"
[Desktop Entry]
Name=Porco Translator
Comment=Tradutor Real-Time com IA para Jogos e Vídeos
Exec=bash -c "DISPLAY=:0 $VENV_PATH/bin/python $INSTALL_DIR/porco_translator.py"
Icon=porco_translator
Terminal=false
Type=Application
Path=$INSTALL_DIR
Categories=Utility;AudioVideo;
StartupNotify=true
EOF_DESK

chmod +x "$HOME/.local/share/applications/porco_translator.desktop"
chmod +x "$INSTALL_DIR/porco_translator.py"
chmod +x "$INSTALL_DIR/porco_listener.py"
chmod +x "$INSTALL_DIR/porco_ui.py"

# 7. Criar Desinstalador
echo "🗑️ Gerando script de desinstalação..."
cat <<EOF_UN > "$INSTALL_DIR/uninstall.sh"
#!/bin/bash
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'
echo -e "\${RED}🚨 Desinstalando Porco Translator...\${NC}"
read -p "Tem certeza que deseja remover todos os arquivos de $INSTALL_DIR? [s/N]: " confirm
if [[ "\$confirm" == "s" || "\$confirm" == "S" ]]; then
    rm -f "\$HOME/.local/share/applications/porco_translator.desktop"
    rm -f "\$HOME/.local/share/icons/porco_translator.svg"
    rm -f "\$HOME/.local/share/icons/porco_translator.png"
    rm -rf "$INSTALL_DIR"
    echo -e "\${GREEN}✅ Desinstalado com sucesso!\${NC}"
else
    echo "Operação cancelada."
fi
EOF_UN
chmod +x "$INSTALL_DIR/uninstall.sh"

echo -e "\n${GREEN}✨ Instalação Conclída com Sucesso!${NC}"
echo -e "Você já pode abrir o 'Porco Translator' no seu menu de aplicativos."
