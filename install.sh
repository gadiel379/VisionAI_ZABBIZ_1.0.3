#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="${VISIONAI_VERSION:-1.0.3}"
REF="${VISIONAI_REF:-v1.0.3-r4}"
REPOSITORY="${VISIONAI_REPOSITORY:-gadiel379/VisionAI_ZABBIZ_1.0.3}"
INSTALL_ZEROTIER="${VISIONAI_INSTALL_ZEROTIER:-1}"

log() { printf '[VISION AI] %s\n' "$*"; }
fail() { printf '[VISION AI] ERROR: %s\n' "$*" >&2; exit 1; }

if [[ "${EUID}" -ne 0 ]]; then
    fail "Ejecuta este instalador con sudo."
fi

TARGET_USER="${VISIONAI_USER:-${SUDO_USER:-}}"
if [[ -z "${TARGET_USER}" || "${TARGET_USER}" == "root" ]]; then
    if id gadiel >/dev/null 2>&1; then
        TARGET_USER="gadiel"
    else
        TARGET_USER="$(getent passwd | awk -F: '$3 >= 1000 && $3 < 60000 {print $1; exit}')"
    fi
fi
[[ -n "${TARGET_USER}" ]] || fail "No se encontró un usuario operativo. Usa VISIONAI_USER=usuario."
id "${TARGET_USER}" >/dev/null 2>&1 || fail "No existe el usuario ${TARGET_USER}."

TARGET_HOME="$(getent passwd "${TARGET_USER}" | cut -d: -f6)"
TARGET_GROUP="$(id -gn "${TARGET_USER}")"
PROJECT_ROOT="${VISIONAI_INSTALL_DIR:-${TARGET_HOME}/vision_ai}"
BACKUP_ROOT="${TARGET_HOME}/vision_ai_backups"
FRESH_INSTALL=0
[[ -d "${PROJECT_ROOT}" ]] || FRESH_INSTALL=1

case "${PROJECT_ROOT}" in
    /home/*/vision_ai|/opt/vision_ai) ;;
    *) fail "Ruta de instalación no permitida: ${PROJECT_ROOT}" ;;
esac

TEMP_DIR="$(mktemp -d /tmp/vision-ai-install.XXXXXX)"
cleanup() { rm -rf -- "${TEMP_DIR}"; }
trap cleanup EXIT
trap 'printf "[VISION AI] Instalación interrumpida en la línea %s.\n" "$LINENO" >&2' ERR

log "Instalando dependencias del sistema..."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    acl alsa-utils ca-certificates curl ffmpeg git iproute2 \
    python3 python3-flask python3-numpy python3-opencv python3-pip \
    python3-venv python3-werkzeug python3-yaml \
    snmp snmpd sudo tesseract-ocr tesseract-ocr-spa \
    v4l-utils wireguard-tools

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]:-/nonexistent}")" 2>/dev/null && pwd || true)"
if [[ -d "${SCRIPT_DIRECTORY}/vision_ai" && -d "${SCRIPT_DIRECTORY}/system" ]]; then
    SOURCE_ROOT="${SCRIPT_DIRECTORY}"
else
    log "Descargando ${REPOSITORY} ${REF}..."
    ARCHIVE="${TEMP_DIR}/source.tar.gz"
    curl -fL --retry 3 --connect-timeout 15 \
        "https://github.com/${REPOSITORY}/archive/refs/tags/${REF}.tar.gz" \
        -o "${ARCHIVE}" \
        || curl -fL --retry 3 --connect-timeout 15 \
            "https://github.com/${REPOSITORY}/archive/${REF}.tar.gz" \
            -o "${ARCHIVE}"
    SOURCE_ROOT="${TEMP_DIR}/source"
    mkdir -p "${SOURCE_ROOT}"
    tar -xzf "${ARCHIVE}" --strip-components=1 -C "${SOURCE_ROOT}"
fi

[[ -f "${SOURCE_ROOT}/vision_ai/main.py" ]] || fail "La descarga no contiene vision_ai/main.py."
[[ -f "${SOURCE_ROOT}/system/vision-ai.service.in" ]] || fail "Falta la plantilla systemd."

systemctl stop vision-ai.service >/dev/null 2>&1 || true

STATE_DIR="${TEMP_DIR}/state"
mkdir -p "${STATE_DIR}"
if [[ -d "${PROJECT_ROOT}" ]]; then
    STAMP="$(date +%Y%m%d_%H%M%S)"
    install -d -o "${TARGET_USER}" -g "${TARGET_GROUP}" "${BACKUP_ROOT}"
    tar -czf "${BACKUP_ROOT}/vision_ai_${STAMP}.tar.gz" \
        -C "$(dirname "${PROJECT_ROOT}")" \
        "$(basename "${PROJECT_ROOT}")/config" \
        "$(basename "${PROJECT_ROOT}")/main.py" 2>/dev/null || true
    chown "${TARGET_USER}:${TARGET_GROUP}" "${BACKUP_ROOT}/vision_ai_${STAMP}.tar.gz" || true

    for relative in config/channels.yaml config/integrations.yaml; do
        if [[ -f "${PROJECT_ROOT}/${relative}" ]]; then
            mkdir -p "${STATE_DIR}/$(dirname "${relative}")"
            cp -a "${PROJECT_ROOT}/${relative}" "${STATE_DIR}/${relative}"
        fi
    done
    if [[ -d "${PROJECT_ROOT}/config/templates" ]]; then
        mkdir -p "${STATE_DIR}/config"
        cp -a "${PROJECT_ROOT}/config/templates" "${STATE_DIR}/config/templates"
    fi
fi

log "Instalando código en ${PROJECT_ROOT}..."
install -d -o "${TARGET_USER}" -g "${TARGET_GROUP}" "${PROJECT_ROOT}"
cp -a "${SOURCE_ROOT}/vision_ai/." "${PROJECT_ROOT}/"

for relative in config/channels.yaml config/integrations.yaml; do
    if [[ -f "${STATE_DIR}/${relative}" ]]; then
        cp -a "${STATE_DIR}/${relative}" "${PROJECT_ROOT}/${relative}"
    fi
done
if [[ -d "${STATE_DIR}/config/templates" ]]; then
    cp -a "${STATE_DIR}/config/templates/." "${PROJECT_ROOT}/config/templates/"
fi

if [[ ! -f "${PROJECT_ROOT}/config/integrations.yaml" ]]; then
    cp "${PROJECT_ROOT}/config/integrations.example.yaml" \
       "${PROJECT_ROOT}/config/integrations.yaml"
fi
chmod 600 "${PROJECT_ROOT}/config/integrations.yaml"
install -d -o "${TARGET_USER}" -g "${TARGET_GROUP}" \
    "${PROJECT_ROOT}/storage/events" \
    "${PROJECT_ROOT}/storage/live" \
    "${PROJECT_ROOT}/storage/snmp" \
    "${PROJECT_ROOT}/logs"

if [[ ! -x "${PROJECT_ROOT}/venv/bin/python3" ]]; then
    python3 -m venv --system-site-packages "${PROJECT_ROOT}/venv"
fi
"${PROJECT_ROOT}/venv/bin/python3" -m pip install --disable-pip-version-check \
    --upgrade pip setuptools wheel
"${PROJECT_ROOT}/venv/bin/python3" -m pip install --disable-pip-version-check \
    -r "${SOURCE_ROOT}/requirements.txt"

chown -R "${TARGET_USER}:${TARGET_GROUP}" "${PROJECT_ROOT}"
chmod 600 "${PROJECT_ROOT}/config/integrations.yaml"
if id Debian-snmp >/dev/null 2>&1; then
    setfacl -m "u:Debian-snmp:--x" "${TARGET_HOME}"
fi

log "Resolviendo capturadoras conectadas..."
(
    cd "${SOURCE_ROOT}"
    VISIONAI_PROJECT_ROOT="${PROJECT_ROOT}" PYTHONPATH="${PROJECT_ROOT}" \
        "${PROJECT_ROOT}/venv/bin/python3" \
        "${SOURCE_ROOT}/scripts/assign_hardware.py"
) || log "No se asignaron capturadoras; podrán seleccionarse desde el dashboard."

render() {
    local source="$1" destination="$2" mode="$3"
    sed \
        -e "s|@USER@|${TARGET_USER}|g" \
        -e "s|@GROUP@|${TARGET_GROUP}|g" \
        -e "s|@HOME@|${TARGET_HOME}|g" \
        -e "s|@PROJECT_ROOT@|${PROJECT_ROOT}|g" \
        "${source}" > "${TEMP_DIR}/rendered"
    install -o root -g root -m "${mode}" "${TEMP_DIR}/rendered" "${destination}"
}

log "Instalando servicio y controles restringidos..."
render "${SOURCE_ROOT}/system/vision-ai.service.in" \
    /etc/systemd/system/vision-ai.service 0644
render "${SOURCE_ROOT}/system/vision-ai-vpn.sudoers.in" \
    /etc/sudoers.d/vision-ai-vpn 0440
render "${SOURCE_ROOT}/system/vision-ai-snmp.sudoers.in" \
    /etc/sudoers.d/vision-ai-snmp 0440
render "${SOURCE_ROOT}/system/vision-ai-power.sudoers.in" \
    /etc/sudoers.d/vision-ai-power 0440
render "${SOURCE_ROOT}/system/vision-ai-snmpctl" \
    /usr/local/sbin/vision-ai-snmpctl 0755
install -o root -g root -m 0755 "${SOURCE_ROOT}/system/vision-ai-vpnctl" \
    /usr/local/sbin/vision-ai-vpnctl
install -o root -g root -m 0755 "${SOURCE_ROOT}/scripts/verify-install.sh" \
    /usr/local/sbin/vision-ai-verify
install -o root -g root -m 0755 "${SOURCE_ROOT}/scripts/update.sh" \
    /usr/local/sbin/vision-ai-update
install -o root -g root -m 0755 "${SOURCE_ROOT}/scripts/uninstall.sh" \
    /usr/local/sbin/vision-ai-uninstall

visudo -cf /etc/sudoers.d/vision-ai-vpn >/dev/null
visudo -cf /etc/sudoers.d/vision-ai-snmp >/dev/null
visudo -cf /etc/sudoers.d/vision-ai-power >/dev/null

install -d -o root -g root -m 0755 /etc/vision-ai
touch /etc/vision-ai/vision-ai.env
chmod 0644 /etc/vision-ai/vision-ai.env

if [[ "${FRESH_INSTALL}" -eq 1 ]]; then
    systemctl disable --now snmpd.service >/dev/null 2>&1 || true
fi

if [[ "${INSTALL_ZEROTIER}" == "1" ]] && ! command -v zerotier-cli >/dev/null 2>&1; then
    log "Instalando ZeroTier desde su instalador oficial..."
    if curl -fsSL --retry 3 https://install.zerotier.com -o "${TEMP_DIR}/zerotier-install.sh"; then
        bash "${TEMP_DIR}/zerotier-install.sh" || log "ZeroTier no pudo instalarse; Vision AI continuará."
        systemctl disable --now zerotier-one.service >/dev/null 2>&1 || true
    else
        log "No se pudo descargar ZeroTier; podrá instalarse después."
    fi
fi

log "Verificando código Python..."
(
    cd "${PROJECT_ROOT}"
    "${PROJECT_ROOT}/venv/bin/python3" -m compileall -q \
        audio camera channel_id core detectors events integrations utils web main.py
)
FFMPEG_ENCODERS="${TEMP_DIR}/ffmpeg-encoders.txt"
ffmpeg -hide_banner -encoders >"${FFMPEG_ENCODERS}" 2>/dev/null \
    || fail "No fue posible consultar los codificadores de FFmpeg."
grep -q libx264 "${FFMPEG_ENCODERS}" \
    || fail "FFmpeg no incluye libx264."
grep -q ' aac ' "${FFMPEG_ENCODERS}" \
    || fail "FFmpeg no incluye AAC."

systemctl daemon-reload
systemctl enable vision-ai.service >/dev/null
systemctl restart vision-ai.service

log "Esperando el dashboard..."
for _ in $(seq 1 30); do
    if curl -fsS --max-time 2 http://127.0.0.1:5000/api/status >/dev/null 2>&1 \
       || curl -fsS --max-time 2 http://127.0.0.1:5000/ >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! systemctl is-active --quiet vision-ai.service; then
    journalctl -u vision-ai.service -n 120 --no-pager || true
    fail "vision-ai.service no quedó activo."
fi

IP_ADDRESS="$(hostname -I 2>/dev/null | awk '{print $1}')"
log "Instalación ${VERSION} completada."
log "Dashboard: http://${IP_ADDRESS:-IP_DE_LA_RASPBERRY}:5000"
log "Configura únicamente Telegram, Red/SNMP y VPN desde CONFIGURACIÓN."
