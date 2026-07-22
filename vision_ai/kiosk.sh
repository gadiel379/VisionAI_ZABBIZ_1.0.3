#!/bin/bash

URL="http://127.0.0.1:5000"

# Esperar hasta 60 segundos a que Flask responda
for intento in $(seq 1 60)
do
    if curl --silent --fail "$URL" > /dev/null
    then
        break
    fi

    sleep 1
done

# Evitar múltiples ventanas de Chromium
pkill -f "chromium.*127.0.0.1:5000" 2>/dev/null || true

sleep 2

chromium \
    --kiosk \
    --noerrdialogs \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-translate \
    --disable-features=Translate \
    --autoplay-policy=no-user-gesture-required \
    --check-for-update-interval=31536000 \
    --user-data-dir=/home/gadiel/.config/vision-ai-kiosk \
    "$URL"
