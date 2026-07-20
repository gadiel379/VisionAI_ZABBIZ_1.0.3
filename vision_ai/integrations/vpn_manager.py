# -*- coding: utf-8 -*-

import re
import shutil
import subprocess
from pathlib import Path


class VpnManager:
    """Consulta y aplica estados VPN mediante un ayudante privilegiado."""

    NETWORK_ID_PATTERN = re.compile(
        r"^[0-9a-fA-F]{16}$"
    )
    INTERFACE_PATTERN = re.compile(
        r"^[A-Za-z0-9_=+.-]{1,15}$"
    )

    def __init__(
        self,
        helper_path="/usr/local/sbin/vision-ai-vpnctl",
    ):
        self.helper_path = Path(helper_path)

    @staticmethod
    def defaults():
        return {
            "zerotier": {
                "enabled": False,
                "network_id": "",
                "device_name": "raspberrypi-vision-ai",
            },
            "wireguard": {
                "enabled": False,
                "interface": "wg0",
                "config_path": "/etc/wireguard/wg0.conf",
            },
        }

    def normalize(self, payload):
        payload = payload if isinstance(payload, dict) else {}
        zerotier = payload.get("zerotier")
        wireguard = payload.get("wireguard")
        zerotier = zerotier if isinstance(zerotier, dict) else {}
        wireguard = wireguard if isinstance(wireguard, dict) else {}

        zerotier_enabled = bool(
            zerotier.get("enabled", False)
        )
        network_id = str(
            zerotier.get("network_id", "")
            or ""
        ).strip().lower()
        device_name = str(
            zerotier.get(
                "device_name",
                "raspberrypi-vision-ai",
            )
            or ""
        ).strip()[:80]

        if zerotier_enabled and not self.NETWORK_ID_PATTERN.fullmatch(
            network_id
        ):
            raise ValueError(
                "El Network ID de ZeroTier debe contener "
                "exactamente 16 caracteres hexadecimales."
            )

        interface = str(
            wireguard.get("interface", "wg0")
            or "wg0"
        ).strip()

        if not self.INTERFACE_PATTERN.fullmatch(interface):
            raise ValueError(
                "La interfaz WireGuard es inválida."
            )

        expected_config_path = (
            f"/etc/wireguard/{interface}.conf"
        )
        requested_path = str(
            wireguard.get(
                "config_path",
                expected_config_path,
            )
            or expected_config_path
        ).strip()

        if requested_path != expected_config_path:
            raise ValueError(
                "La ruta WireGuard debe ser "
                f"{expected_config_path}."
            )

        return {
            "zerotier": {
                "enabled": zerotier_enabled,
                "network_id": network_id,
                "device_name": (
                    device_name
                    or "raspberrypi-vision-ai"
                ),
            },
            "wireguard": {
                "enabled": bool(
                    wireguard.get("enabled", False)
                ),
                "interface": interface,
                "config_path": expected_config_path,
            },
        }

    def public_configuration(self, configuration):
        defaults = self.defaults()
        configuration = (
            configuration
            if isinstance(configuration, dict)
            else {}
        )

        merged = {
            "zerotier": {
                **defaults["zerotier"],
                **(
                    configuration.get("zerotier")
                    if isinstance(
                        configuration.get("zerotier"),
                        dict,
                    )
                    else {}
                ),
            },
            "wireguard": {
                **defaults["wireguard"],
                **(
                    configuration.get("wireguard")
                    if isinstance(
                        configuration.get("wireguard"),
                        dict,
                    )
                    else {}
                ),
            },
        }

        merged["status"] = self.status(merged)
        return merged

    def status(self, configuration):
        zerotier_cli = self._find_command(
            "zerotier-cli",
            "/usr/sbin/zerotier-cli",
            "/usr/bin/zerotier-cli",
        )
        wg_command = self._find_command(
            "wg",
            "/usr/bin/wg",
            "/usr/sbin/wg",
        )
        wg_quick = self._find_command(
            "wg-quick",
            "/usr/bin/wg-quick",
            "/usr/sbin/wg-quick",
        )

        interface = str(
            configuration.get("wireguard", {}).get(
                "interface",
                "wg0",
            )
        )

        return {
            "helper_installed": self.helper_path.is_file(),
            "zerotier": {
                "installed": bool(zerotier_cli),
                "active": self._service_active(
                    "zerotier-one"
                ),
            },
            "wireguard": {
                "installed": bool(
                    wg_command and wg_quick
                ),
                "config_exists": self._wireguard_config_exists(
                    interface
                ),
                "active": self._service_active(
                    f"wg-quick@{interface}"
                ),
            },
        }

    def apply(self, current, requested):
        current = self.normalize(current)
        requested = self.normalize(requested)
        status = self.status(requested)
        operations = self._operations(
            current,
            requested,
        )

        action_names = {
            arguments[0]
            for arguments, _ in operations
        }

        if (
            requested["zerotier"]["enabled"]
            and not status["zerotier"]["active"]
            and "zerotier-enable" not in action_names
        ):
            operations.append(
                (
                    (
                        "zerotier-enable",
                        requested["zerotier"]["network_id"],
                    ),
                    (
                        "zerotier-disable",
                        requested["zerotier"]["network_id"],
                    ),
                )
            )

        if (
            requested["wireguard"]["enabled"]
            and not status["wireguard"]["active"]
            and "wireguard-enable" not in action_names
        ):
            operations.append(
                (
                    (
                        "wireguard-enable",
                        requested["wireguard"]["interface"],
                    ),
                    (
                        "wireguard-disable",
                        requested["wireguard"]["interface"],
                    ),
                )
            )

        if not operations:
            return requested

        if not status["helper_installed"]:
            raise RuntimeError(
                "No está instalado el ayudante "
                "vision-ai-vpnctl."
            )

        if (
            requested["zerotier"]["enabled"]
            and not status["zerotier"]["installed"]
        ):
            raise RuntimeError(
                "ZeroTier no está instalado en la Raspberry Pi."
            )

        if requested["wireguard"]["enabled"]:
            if not status["wireguard"]["installed"]:
                raise RuntimeError(
                    "WireGuard no está instalado en la Raspberry Pi."
                )
            if not status["wireguard"]["config_exists"]:
                raise RuntimeError(
                    "No existe el archivo "
                    + requested["wireguard"]["config_path"]
                    + "."
                )

        completed_inverses = []

        try:
            for arguments, inverse in operations:
                self._run_helper(*arguments)
                completed_inverses.append(inverse)
        except Exception:
            for inverse in reversed(completed_inverses):
                try:
                    self._run_helper(*inverse)
                except Exception:
                    pass
            raise

        return requested

    @staticmethod
    def _operations(current, requested):
        operations = []
        old_zt = current["zerotier"]
        new_zt = requested["zerotier"]
        zt_changed = (
            old_zt["network_id"]
            != new_zt["network_id"]
        )

        if old_zt["enabled"] and (
            not new_zt["enabled"] or zt_changed
        ):
            operations.append(
                (
                    (
                        "zerotier-disable",
                        old_zt["network_id"],
                    ),
                    (
                        "zerotier-enable",
                        old_zt["network_id"],
                    ),
                )
            )

        if new_zt["enabled"] and (
            not old_zt["enabled"] or zt_changed
        ):
            operations.append(
                (
                    (
                        "zerotier-enable",
                        new_zt["network_id"],
                    ),
                    (
                        "zerotier-disable",
                        new_zt["network_id"],
                    ),
                )
            )

        old_wg = current["wireguard"]
        new_wg = requested["wireguard"]
        wg_changed = (
            old_wg["interface"]
            != new_wg["interface"]
        )

        if old_wg["enabled"] and (
            not new_wg["enabled"] or wg_changed
        ):
            operations.append(
                (
                    (
                        "wireguard-disable",
                        old_wg["interface"],
                    ),
                    (
                        "wireguard-enable",
                        old_wg["interface"],
                    ),
                )
            )

        if new_wg["enabled"] and (
            not old_wg["enabled"] or wg_changed
        ):
            operations.append(
                (
                    (
                        "wireguard-enable",
                        new_wg["interface"],
                    ),
                    (
                        "wireguard-disable",
                        new_wg["interface"],
                    ),
                )
            )

        return operations

    def _run_helper(self, *arguments):
        command = [
            "sudo",
            "-n",
            str(self.helper_path),
            *[str(value) for value in arguments],
        ]

        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=45,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RuntimeError(
                f"No se pudo ejecutar el control VPN: {error}"
            )

        if result.returncode != 0:
            message = (
                result.stderr.strip()
                or result.stdout.strip()
                or "Error desconocido al aplicar la VPN."
            )
            raise RuntimeError(message[:500])

    def _wireguard_config_exists(self, interface):
        if not self.helper_path.is_file():
            return Path(
                f"/etc/wireguard/{interface}.conf"
            ).is_file()

        command = [
            "sudo",
            "-n",
            str(self.helper_path),
            "wireguard-check",
            str(interface),
        ]

        try:
            result = subprocess.run(
                command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False

        return result.returncode == 0

    @staticmethod
    def _find_command(name, *candidates):
        found = shutil.which(name)
        if found:
            return found

        for candidate in candidates:
            if Path(candidate).is_file():
                return candidate

        return None

    @staticmethod
    def _service_active(service):
        systemctl = shutil.which("systemctl")
        if not systemctl:
            return False

        try:
            result = subprocess.run(
                [systemctl, "is-active", "--quiet", service],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False

        return result.returncode == 0
