#!/usr/bin/env bash
set -u

USER_NAME="${VISIONAI_USER:-${SUDO_USER:-$(id -un)}}"
if [[ "${USER_NAME}" == "root" ]] && id gadiel >/dev/null 2>&1; then
    USER_NAME=gadiel
fi
HOME_DIR="$(getent passwd "${USER_NAME}" | cut -d: -f6)"
ROOT="${VISIONAI_INSTALL_DIR:-${HOME_DIR}/vision_ai}"
FAILED=0

check() {
    if "$@"; then printf '[OK] %s\n' "$*"; else printf '[ERROR] %s\n' "$*"; FAILED=1; fi
}

check test -f "${ROOT}/main.py"
check test -x "${ROOT}/venv/bin/python3"
check test -f "${ROOT}/config/detectors.yaml"
check test -f "${ROOT}/config/channels.yaml"
check test -f "${ROOT}/config/integrations.yaml"
check systemctl is-active --quiet vision-ai.service
check command -v ffmpeg
check command -v arecord
check command -v v4l2-ctl
check command -v tesseract

MODE="$(stat -c '%a' "${ROOT}/config/integrations.yaml" 2>/dev/null || true)"
if [[ "${MODE}" == "600" ]]; then
    printf '[OK] integrations.yaml protegido\n'
else
    printf '[ERROR] integrations.yaml tiene permisos %s; se esperaba 600\n' "${MODE}"
    FAILED=1
fi

printf '\n=== Servicio ===\n'
systemctl status vision-ai.service --no-pager -l || true
printf '\n=== Pipelines ===\n'
journalctl -u vision-ai.service -n 150 --no-pager \
    | grep -E '\[HARDWARE\]|\[PIPELINE\]|\[LIVE HLS\]|Traceback|ERROR' || true

exit "${FAILED}"
