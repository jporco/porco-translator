#!/bin/bash
# Professional Interactive Installer for Porco Translator

# Cores para o terminal
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}🐽 Iniciando instalador do Porco Translator...${NC}"

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
# Usamos rsync se disponível, senão cp
if command -v rsync &> /dev/null; then
    rsync -av --exclude 'venv' --exclude '.git' --exclude '__pycache__' ./ "$INSTALL_DIR/"
else
    cp -r ./ "$INSTALL_DIR/"
    rm -rf "$INSTALL_DIR/venv" "$INSTALL_DIR/.git" "$INSTALL_DIR/__pycache__" 2>/dev/null
fi

cd "$INSTALL_DIR" || exit

# 3. Dependências do Sistema
echo -e "\n${BLUE}⚙️ Verificando dependências do sistema...${NC}"
if command -v pacman &> /dev/null; then
    sudo pacman -S --needed --noconfirm python python-pip pipewire pipewire-audio ffmpeg rsync
elif command -v dnf &> /dev/null; then
    sudo dnf install -y python3 python3-pip pipewire ffmpeg rsync
fi

# 4. Virtual Environment no local de destino
VENV_PATH="$INSTALL_DIR/venv"
if [ ! -d "$VENV_PATH" ]; then
    echo "🐍 Criando ambiente virtual dedicado..."
    python -m venv "$VENV_PATH"
fi

# 5. Instalar dependências Python
echo "📥 Instalando dependências do Python (isso pode levar um minuto na primeira vez)..."
"$VENV_PATH/bin/pip" install --upgrade pip
"$VENV_PATH/bin/pip" install -r requirements.txt

# 6. Configuração do Piper (opcional)
if [ ! -f "$HOME/.local/bin/piper_read.sh" ]; then
    echo "🔊 Configurando script TTS em ~/.local/bin/..."
    mkdir -p "$HOME/.local/bin"
    cp piper_read.sh "$HOME/.local/bin/"
    chmod +x "$HOME/.local/bin/piper_read.sh"
fi

# 7. Criar atalho Desktop
echo "🖥️ Criando atalho no menu de aplicativos..."
mkdir -p "$HOME/.local/share/icons"
mkdir -p "$HOME/.local/share/applications"
cp porco_translator.png "$HOME/.local/share/icons/porco_translator.png"

cat <<EOF > "$HOME/.local/share/applications/porco_translator.desktop"
[Desktop Entry]
Name=Porco Translator
Comment=Tradutor Real-Time com IA para Jogos e Vídeos
Exec=$VENV_PATH/bin/python $INSTALL_DIR/porco_translator.py
Icon=porco_translator
Terminal=false
Type=Application
Path=$INSTALL_DIR
Categories=Utility;AudioVideo;
StartupNotify=true
EOF

chmod +x "$HOME/.local/share/applications/porco_translator.desktop"
chmod +x "$INSTALL_DIR/porco_translator.py"

# 8. Criar Desinstalador
echo "🗑️ Gerando script de desinstalação..."
cat <<EOF > "$INSTALL_DIR/uninstall.sh"
#!/bin/bash
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'
echo -e "\${RED}🚨 Desinstalando Porco Translator...\${NC}"
read -p "Tem certeza que deseja remover todos os arquivos de $INSTALL_DIR? [s/N]: " confirm
if [[ "\$confirm" == "s" || "\$confirm" == "S" ]]; then
    rm -f "\$HOME/.local/share/applications/porco_translator.desktop"
    rm -rf "$INSTALL_DIR"
    echo -e "\${GREEN}✅ Desinstalado com sucesso!\${NC}"
else
    echo "Operação cancelada."
fi
EOF
chmod +x "$INSTALL_DIR/uninstall.sh"

echo -e "\n${GREEN}✨ Instalação Concluída com Sucesso!${NC}"
echo -e "Você já pode abrir o 'Porco Translator' no seu menu de aplicativos."
echo -e "Local: ${BLUE}$INSTALL_DIR${NC}"
echo -e "Desinstalador disponível em: ${BLUE}$INSTALL_DIR/uninstall.sh${NC}"
