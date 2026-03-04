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

# Capturar texto selecionado
if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
    TEXT=$(wl-paste -p 2>/dev/null || wl-paste)
else
    # X11: Tenta selecao primaria (mouse) primeiro, depois clipboard
    TEXT=$(xclip -o -selection primary 2>/dev/null || xclip -o -selection clipboard 2>/dev/null)
fi

# Se nao houver texto, tenta ler o que foi passado como texto opcional no 2o arg
if [ -z "$TEXT" ]; then
    TEXT="$2"
fi

if [ -z "$TEXT" ]; then
    notify-send "Piper TTS" "Selecione ou copie um texto primeiro."
    echo "$(date): Erro - Nenhum texto encontrado" >> "$LOGFILE"
    exit 1
fi

# Limpar o texto de pontuções que podem bugar a fala (ignorar fala de pontuação)
# Remove traços, exclamações, pontos e outros símbolos, mantendo apenas letras e números
CLEAN_TEXT=$(echo "$TEXT" | sed 's/[.!?"()#$*+=\/\\_-]//g')

echo "$(date): Iniciando leitura. Velocidade: $SPEED" >> "$LOGFILE"

# Filtro de Voz "Wolverine":
# 1. asetrate: Abaixa o tom (0.83 do original) para ficar grosso
# 2. atempo: Corrige a velocidade para ficar rapida (SPEED)
# 3. equalizer: Aumenta graves (80Hz) e clareza (4kHz)
# 4. volume: Ajuste de volume
FILTER="asetrate=$RATE*0.83,atempo=$SPEED,equalizer=f=80:t=q:w=1:g=4,equalizer=f=4000:t=q:w=1:g=6,volume=$VOLUME"

(echo "$CLEAN_TEXT" | /usr/bin/piper-tts --model "$VOICE" --output_raw | \
 /usr/bin/ffmpeg -f s16le -ar "$RATE" -ac 1 -i - -af "$FILTER" -f wav - 2>>"$LOGFILE" | \
 /usr/bin/aplay -q) &

notify-send "Piper TTS" "Lendo em ${SPEED}x..." -i audio-speakers
