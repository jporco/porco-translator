#!/bin/bash

# Script para ler texto usando Piper-TTS com suporte a Toggle e Velocidade
# Autor: Antigravity

VOICE="/home/porco/.config/piper/pt-BR-cadu-medium.onnx"
RATE=22050
LOGFILE="/tmp/piper_read.log"

# Capturar velocidade do 1o argumento, se vazio vira 1.6. Volume do 3o arg.
SPEED="${1:-1.6}"
VOLUME="${3:-1.0}"

# Se o processo ja estiver rodando, mata ele e sai (Toggle)
if pgrep -f "piper-tts.*$VOICE" > /dev/null; then
    pkill -f "piper-tts.*$VOICE"
    pkill -u "$USER" -x aplay
    echo "$(date): Parando leitura (Toggle)" >> "$LOGFILE"
    exit 0
fi

# Capturar texto selecionado PRIMEIRO (X11 e Wayland)
if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
    TEXT=$(wl-paste -p 2>/dev/null || wl-paste)
else
    TEXT=$(xclip -o -selection primary 2>/dev/null || xclip -o -selection clipboard 2>/dev/null)
fi

# Se não houver texto selecionado, tenta Visão Computacional (OCR - Sem cliques)
if [ -z "$TEXT" ]; then
    if [ "$XDG_SESSION_TYPE" != "wayland" ]; then
        # Identifica a janela sob o mouse
        WINDOW_UNDER_MOUSE=$(xdotool getmouselocation --shell | grep WINDOW | cut -d= -f2)
        
        if [ ! -z "$WINDOW_UNDER_MOUSE" ]; then
            notify-send "Piper TTS" "Analisando conteúdo inteligente..." -i scanner -t 1500
            TMP_IMG="/tmp/piper_ocr.png"
            # Tira print silencioso da janela ativa
            import -window "$WINDOW_UNDER_MOUSE" "$TMP_IMG" 2>/dev/null
            
            # OCR com Tesseract
            RAW_OCR=$(tesseract "$TMP_IMG" stdout -l afr 2>/dev/null)
            rm -f "$TMP_IMG"
            
            # Filtragem Inteligente via Python (Remove Menus, Botões e foca em Frases)
            TEXT=$(python3 -c "
import sys, re, unicodedata

def is_useful(line):
    line = line.strip()
    words = line.split()
    if len(words) < 3: return False
    ui_noise = {'file', 'edit', 'view', 'history', 'bookmarks', 'tools', 'help', 'arquivos', 'editar', 'ajuda', 'pesquisar', 'search', 'ok', 'cancel', 'close', 'fechar'}
    if len(words) < 5 and any(w.lower() in ui_noise for w in words): return False
    return True

text = sys.stdin.read()
lines = text.split('\n')
useful = []
seen = set()
for l in lines:
    if is_useful(l):
        # Limpeza básica
        l = ''.join(c for c in l if unicodedata.category(c)[0] != 'C' and unicodedata.category(c) != 'So')
        l = re.sub(r'[^\w\s.,?!;ÁÉÍÓÚáéíóúÂÊÎÔÛâêîôûÀÈÌÒÙàèìòùÃÕãõÇç]', ' ', l)
        l = re.sub(r'\s+', ' ', l).strip()
        if l and l not in seen:
            useful.append(l)
            seen.add(l)
print(' '.join(useful))
" <<< "$RAW_OCR")
        fi
    fi
fi

# Limpar seleções antigas para o próximo uso (Apenas se capturamos algo novo)
if [ ! -z "$TEXT" ]; then
    echo -n "" | xclip -selection primary 2>/dev/null
fi

# Se ainda nao houver texto, tenta ler o que foi passado como texto opcional no 2o arg
if [ -z "$TEXT" ]; then
    TEXT="$2"
fi

if [ -z "$TEXT" ]; then
    notify-send "Piper TTS" "Nenhum texto relevante encontrado."
    exit 1
fi

CLEAN_TEXT="$TEXT"
echo "$(date): Iniciando leitura. Inteligência aplicada." >> "$LOGFILE"

# Filtro de Voz de Narração:
# 1. asetrate: Ajuste de tom (0.88 - menos grave/abafado)
# 2. atempo: Velocidade (SPEED)
# 3. highpass: Remove frequências abafadas abaixo de 200Hz
# 4. equalizer: Brilho extra em 4kHz e 8kHz para clareza
FILTER="asetrate=$RATE*0.88,atempo=$SPEED,highpass=f=200,equalizer=f=4000:t=q:w=1:g=5,equalizer=f=8000:t=q:w=1:g=3,volume=$VOLUME"

(echo "$CLEAN_TEXT" | /usr/bin/piper-tts --model "$VOICE" --output_raw | \
 /usr/bin/ffmpeg -f s16le -ar "$RATE" -ac 1 -i - -af "$FILTER" -f wav - 2>>"$LOGFILE" | \
 /usr/bin/aplay -q) &

notify-send "Piper TTS" "Lendo texto inteligente..." -i audio-speakers
