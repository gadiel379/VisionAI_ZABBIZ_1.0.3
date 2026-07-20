#!/usr/bin/env bash
set -Eeuo pipefail

[[ "${EUID}" -eq 0 ]] || { echo "Ejecuta con sudo." >&2; exit 1; }
[[ "${1:-}" == "--confirm" ]] || {
    echo "Uso: sudo scripts/uninstall.sh --confirm"
    echo "El código y las evidencias se conservan; solamente se retira el servicio."
    exit 2
}

systemctl disable --now vision-ai.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/vision-ai.service
rm -f /etc/sudoers.d/vision-ai-vpn
rm -f /etc/sudoers.d/vision-ai-snmp
rm -f /etc/sudoers.d/vision-ai-power
rm -f /usr/local/sbin/vision-ai-vpnctl
rm -f /usr/local/sbin/vision-ai-snmpctl
rm -f /usr/local/sbin/vision-ai-verify
rm -f /usr/local/sbin/vision-ai-update
rm -f /usr/local/sbin/vision-ai-uninstall
systemctl daemon-reload
echo "Servicio Vision AI retirado. El proyecto, configuración y eventos se conservaron."
