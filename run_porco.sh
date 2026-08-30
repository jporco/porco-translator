#!/usr/bin/env bash
# Porco Translator - launcher robusto (v17.3)
set -u

CODE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -d "$CODE_DIR/../venv" ]]; then
    VENV_PATH="$(cd -- "$CODE_DIR/../venv" && pwd)"
else
    VENV_PATH="$CODE_DIR/venv"
fi
SCRIPT_PATH="$CODE_DIR/porco_translator.py"

PYTHON_VERSION="$(/usr/bin/python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
SITE_PACKAGES="$VENV_PATH/lib/python${PYTHON_VERSION}/site-packages"
PYTHON="$VENV_PATH/bin/python"

# Ambientes copiados de outro sistema podem conter atalhos inválidos em bin/python.
# Nesse caso, o Python do sistema usa as dependências preservadas no venv via PYTHONPATH.
if [[ ! -x "$PYTHON" ]] || ! "$PYTHON" -c 'import sys' >/dev/null 2>&1; then
    PYTHON=/usr/bin/python3
fi

if [[ -d "$SITE_PACKAGES" ]]; then
    if [[ -n "${PYTHONPATH:-}" ]]; then
        export PYTHONPATH="$SITE_PACKAGES:$PYTHONPATH"
    else
        export PYTHONPATH="$SITE_PACKAGES"
    fi
fi

CUDA_PATHS=()
for path in "$SITE_PACKAGES/nvidia/cublas/lib" "$SITE_PACKAGES/nvidia/cudnn/lib" /opt/cuda/lib64; do
    [[ -d "$path" ]] && CUDA_PATHS+=("$path")
done
if (( ${#CUDA_PATHS[@]} )); then
    CUDA_LIBS="$(IFS=:; printf '%s' "${CUDA_PATHS[*]}")"
    if [[ -n "${LD_LIBRARY_PATH:-}" ]]; then
        export LD_LIBRARY_PATH="$CUDA_LIBS:$LD_LIBRARY_PATH"
    else
        export LD_LIBRARY_PATH="$CUDA_LIBS"
    fi
fi

echo "Iniciando Porco Translator com: $PYTHON"
echo "Dependências Python: $SITE_PACKAGES"
exec "$PYTHON" "$SCRIPT_PATH"
