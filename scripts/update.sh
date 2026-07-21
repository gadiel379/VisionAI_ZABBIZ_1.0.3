#!/usr/bin/env bash
set -Eeuo pipefail

REF="${1:-v1.0.3-r4}"
TEMP_FILE="$(mktemp /tmp/vision-ai-update.XXXXXX.sh)"
trap 'rm -f -- "${TEMP_FILE}"' EXIT

curl -fL --retry 3 \
    "https://raw.githubusercontent.com/gadiel379/VisionAI_ZABBIZ_1.0.3/${REF}/install.sh" \
    -o "${TEMP_FILE}"

sudo env VISIONAI_REF="${REF}" bash "${TEMP_FILE}"
