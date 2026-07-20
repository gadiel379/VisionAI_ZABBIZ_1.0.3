#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"
CACHE_DIR="$(mktemp -d /tmp/vision-ai-pycache.XXXXXX)"
trap 'rm -rf -- "${CACHE_DIR}"' EXIT

bash -n install.sh scripts/*.sh
PYTHONPYCACHEPREFIX="${CACHE_DIR}" python3 -m compileall -q \
    vision_ai scripts/assign_hardware.py \
    system/vision-ai-snmpctl system/vision-ai-vpnctl

test "$(tr -d '[:space:]' < VERSION)" = "1.0.3"
grep -q 'video_delay_seconds=0.8' vision_ai/web/dashboard.py
grep -q 'Versión: 1.0.3' vision_ai/web/templates/index.html
grep -q 'freeze_candidate_active' vision_ai/detectors/monitor_engine.py

if find . -type f \( \
    -name '*.pyc' -o -name '*.bak*' -o -name '*.save' -o \
    -name '*.mp4' -o -name '*.wav' -o -name '*.zip' -o \
    -name 'integrations.yaml' \
\) -print -quit | grep -q .; then
    echo "La distribución contiene archivos locales prohibidos." >&2
    exit 1
fi

if grep -R -I -n -E \
    '([0-9]{8,10}:[A-Za-z0-9_-]{30,}|bot_token:[[:space:]]*[^[:space:]]|community:[[:space:]]+[^'"'"']|password_hash:[[:space:]]+[^'"'"'])' \
    --exclude='validate-release.sh' .; then
    echo "Se encontró un posible secreto." >&2
    exit 1
fi

echo "Distribución Vision AI 1.0.3 validada."
