#!/bin/bash
# Porco Translator - Fail-safe Launcher (v17.3)

VENV_PATH="/mnt/X/arch/porco_translator/venv"
SCRIPT_PATH="/mnt/X/arch/porco_translator/code/porco_translator.py"

echo "Matando todas as instâncias do Porco Translator..."
pkill -9 -f "porco_translator.py" 2>/dev/null
pkill -9 -f "porco_listener.py" 2>/dev/null
pkill -9 -f "porco_ui.py" 2>/dev/null
sleep 0.5

echo "Iniciando com venv: $VENV_PATH"
export PYTHONPATH="$VENV_PATH/lib/python3.14/site-packages:$PYTHONPATH"
export LD_LIBRARY_PATH="$VENV_PATH/lib/python3.14/site-packages/nvidia/cublas/lib:$VENV_PATH/lib/python3.14/site-packages/nvidia/cudnn/lib:$LD_LIBRARY_PATH"

# Executa o script diretamente com o python do venv
"$VENV_PATH/bin/python" "$SCRIPT_PATH"
