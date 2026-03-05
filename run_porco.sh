#!/bin/bash
# Porco Translator - Fail-safe Launcher (v17.3)

VENV_PATH="/home/porco/.local/share/porco_translator/venv"
SCRIPT_PATH="/home/porco/.gemini/antigravity/scratch/porco-translator/porco_translator.py"

echo "Matando instâncias antigas..."
pkill -9 -f "porco_translator.py" 2>/dev/null

echo "Iniciando com venv: $VENV_PATH"
export PYTHONPATH="$VENV_PATH/lib/python3.12/site-packages:$PYTHONPATH"

# Executa o script diretamente com o python do venv
"$VENV_PATH/bin/python" "$SCRIPT_PATH"
