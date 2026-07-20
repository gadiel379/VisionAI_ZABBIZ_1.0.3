# -*- coding: utf-8 -*-

import ipaddress
import json
import os
import socket
import shutil
import subprocess
import threading
import time
from pathlib import Path

import cv2
import yaml
from flask import Flask, Response, jsonify, render_template, request, send_file, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash

from web.live_hls_streamer import LiveHlsStreamer
from integrations.vpn_manager import VpnManager
from camera.hardware_discovery import CaptureHardwareDiscovery


class Dashboard:
    def __init__(
        self,
        audio_monitor=None,
        zabbix_notifier=None,
        host="0.0.0.0",
        port=5000,
    ):
        self.audio_monitor = audio_monitor
        self.audio_monitors = {}
        self.zabbix_notifier = zabbix_notifier
        self.host = host
        self.port = port
        self.project_root = Path(__file__).resolve().parent.parent
        self.config_path = self.project_root / "config" / "channels.yaml"
        self.integrations_path = self.project_root / "config" / "integrations.yaml"
        self.events_path = self.project_root / "storage" / "events"
        self.clips_path = self.project_root / "storage" / "clips"
        self.snapshots_path = self.project_root / "storage" / "snapshots"
        self.live_path = self.project_root / "storage" / "live"
        self.templates_path = self.project_root / "config" / "templates"

        self.app = Flask(__name__, template_folder="templates")
        self.latest_frames = {"capture_1": None, "capture_2": None}
        self.latest_jpegs = {"capture_1": None, "capture_2": None}
        self.last_jpeg_monotonic = {"capture_1": 0.0, "capture_2": 0.0}
        self.mjpeg_clients = {"capture_1": 0, "capture_2": 0}
        self.lock = threading.Lock()
        self.channel_status = "INICIANDO"
        self.capture_status = {
            "capture_1": "INICIANDO",
            "capture_2": "DESHABILITADA",
        }
        self.last_event = "Sin eventos"
        self.service_started_monotonic = time.monotonic()
        self.capture_started_monotonic = {}
        self._cpu_lock = threading.Lock()
        self._last_cpu_total = None
        self._last_cpu_idle = None
        self.vpn_manager = VpnManager()

        self.live_streamers = {}
        self.hardware_discovery = CaptureHardwareDiscovery(maximum_devices=2)

        if audio_monitor is not None:
            self.register_capture("capture_1", audio_monitor)

        config = self._load_config()
        for capture_id, capture in config["captures"].items():
            if capture.get("enabled", False):
                self.capture_started_monotonic[capture_id] = self.service_started_monotonic

        self._configure_routes()

    @staticmethod
    def _default_config():
        return {
            "captures": {
                "capture_1": {
                    "hardware_id": "",
                    "video_device": "/dev/video0",
                    "audio_device": "",
                    "enabled": True,
                    "station_id": "XHTP-TDT",
                    "channel_name": "RED2",
                    "channel_number": "2.1",
                    "location": "Mérida, Yucatán",
                    "template_name": "red2",
                    "template_directory": "config/templates/capture_1/red2",
                },
                "capture_2": {
                    "hardware_id": "",
                    "video_device": "",
                    "audio_device": "",
                    "enabled": False,
                    "station_id": "",
                    "channel_name": "",
                    "channel_number": "",
                    "location": "",
                    "template_name": "",
                    "template_directory": "",
                },
            },
            "network": {
                "ip": "",
                "netmask": "",
                "gateway": "",
                "dns1": "",
                "dns2": "",
            },
        }

    def _load_config(self):
        default = self._default_config()
        if not self.config_path.exists():
            self._save_config(default)
            return default
        try:
            with self.config_path.open("r", encoding="utf-8") as file:
                loaded = yaml.safe_load(file) or {}
        except (OSError, yaml.YAMLError):
            return default

        loaded.setdefault("captures", {})
        loaded.setdefault("network", {})
        for capture_id, defaults in default["captures"].items():
            loaded["captures"].setdefault(capture_id, {})
            for key, value in defaults.items():
                loaded["captures"][capture_id].setdefault(key, value)
        for key, value in default["network"].items():
            loaded["network"].setdefault(key, value)
        return loaded

    def _save_config(self, config):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".yaml.tmp")
        with temporary.open("w", encoding="utf-8") as file:
            yaml.safe_dump(config, file, allow_unicode=True, sort_keys=False)
        os.replace(temporary, self.config_path)

    @staticmethod
    def _default_integrations():
        return {
            "security": {
                "username": "",
                "password_hash": "",
            },
            "telegram": {
                "enabled": False,
                "chat_id": "",
                "token": "",
                "channel_id_enabled": False,
                "morning_enabled": False,
                "morning_time": "06:00",
                "afternoon_enabled": False,
                "afternoon_time": "17:00",
            },
            "snmp": {
                "enabled": False,
                "zabbix_server": "",
                "agent_port": 161,
                "trap_port": 162,
                "community": "",
                "long_event_seconds": 60.0,
            },
            "vpn": VpnManager.defaults(),
        }

    def _load_integrations(self):
        default = self._default_integrations()
        if not self.integrations_path.exists():
            self._save_integrations(default)
            return default
        try:
            with self.integrations_path.open("r", encoding="utf-8") as file:
                loaded = yaml.safe_load(file) or {}
        except (OSError, yaml.YAMLError):
            return default
        for section, values in default.items():
            loaded.setdefault(section, {})
            for key, value in values.items():
                loaded[section].setdefault(key, value)

        snmp = loaded.get("snmp", {})
        if not snmp.get("community"):
            snmp["community"] = (
                snmp.get("read_community")
                or snmp.get("public_community")
                or ""
            )
        if "port" in snmp:
            snmp["agent_port"] = snmp.get("port", 161)
        return loaded

    def _save_integrations(self, config):
        self.integrations_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.integrations_path.with_suffix(".yaml.tmp")
        with temporary.open("w", encoding="utf-8") as file:
            yaml.safe_dump(config, file, allow_unicode=True, sort_keys=False)
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.integrations_path)

    def _authorize_update(self, auth, integrations):
        username = str((auth or {}).get("username", "")).strip()
        password = str((auth or {}).get("password", ""))
        security = integrations["security"]
        stored_user = security.get("username", "")
        stored_hash = security.get("password_hash", "")
        if not stored_user or not stored_hash:
            if not username or len(password) < 8:
                return False, "Primera configuración: define un usuario y una contraseña de mínimo 8 caracteres."
            security["username"] = username
            security["password_hash"] = generate_password_hash(password)
            return True, "Credenciales administrativas creadas."
        if username != stored_user or not check_password_hash(stored_hash, password):
            return False, "Usuario o contraseña incorrectos."
        return True, "Autorización correcta."

    @staticmethod
    def _authorize_telegram_update(auth):
        username = str(
            (auth or {}).get("username", "")
        )
        password = str(
            (auth or {}).get("password", "")
        )

        if username != "Admin" or password != "admin":
            return False, "Usuario o contraseña incorrectos."

        return True, "Autorización correcta."

    @staticmethod
    def _validate_schedule_time(value, field_name):
        text = str(value or "").strip()

        try:
            hours_text, minutes_text = text.split(":", 1)
            hours = int(hours_text)
            minutes = int(minutes_text)
        except (TypeError, ValueError):
            raise ValueError(
                f"{field_name} debe tener formato HH:MM."
            )

        if not 0 <= hours <= 23 or not 0 <= minutes <= 59:
            raise ValueError(
                f"{field_name} debe tener formato HH:MM."
            )

        return f"{hours:02d}:{minutes:02d}"

    @staticmethod
    def _parse_event_datetime(value, fallback_name):
        if value:
            text = str(value).replace("T", " ")
            return text[:19]
        digits = "".join(ch for ch in fallback_name if ch.isdigit())
        if len(digits) >= 14:
            return f"{digits[6:8]}/{digits[4:6]}/{digits[0:4]} {digits[8:10]}:{digits[10:12]}:{digits[12:14]}"
        return ""

    def _list_events(self):
        """Lee eventos guardados en carpetas storage/events/<id>/.

        Estructura soportada:
            storage/events/20260714_213604/event.json
            storage/events/20260714_213604/clip.mp4
            storage/events/20260714_213604/snapshot.jpg
            storage/events/20260714_213604/snapshot_ai.jpg

        También conserva compatibilidad con el formato plano anterior.
        """
        self.events_path.mkdir(parents=True, exist_ok=True)
        results = []

        json_paths = list(self.events_path.glob("*/event.json"))
        json_paths.extend(self.events_path.glob("*.json"))
        json_paths = sorted(
            set(path.resolve() for path in json_paths),
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )

        for json_path in json_paths:
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            event_dir = json_path.parent
            folder_id = event_dir.name if json_path.name == "event.json" else json_path.stem
            event_id = str(
                data.get("id")
                or data.get("event_id")
                or folder_id.replace("evento_", "")
            )

            event_type = str(
                data.get("type")
                or data.get("event_type")
                or data.get("alarm_type")
                or "unknown"
            )

            channel = str(
                data.get("channel")
                or data.get("channel_name")
                or data.get("signal", {}).get("channel_name", "")
                if isinstance(data.get("signal"), dict)
                else data.get("channel") or data.get("channel_name") or ""
            )

            duration_value = (
                data.get("duration")
                or data.get("duration_seconds")
                or data.get("event_duration")
            )
            try:
                duration = float(duration_value) if duration_value is not None else None
            except (TypeError, ValueError):
                duration = None

            candidates_video = [
                event_dir / "clip.mp4",
                event_dir / f"evento_{event_id}.mp4",
                event_dir / f"{event_id}.mp4",
                self.clips_path / f"evento_{event_id}.mp4",
                self.clips_path / f"{event_id}.mp4",
            ]

            candidates_image = [
                event_dir / "snapshot_ai.jpg",
                event_dir / "snapshot.jpg",
                event_dir / "image.jpg",
                event_dir / f"evento_{event_id}.jpg",
                event_dir / f"{event_id}.jpg",
                self.snapshots_path / f"evento_{event_id}.jpg",
                self.snapshots_path / f"{event_id}.jpg",
                self.snapshots_path / f"channel_id_{event_id}.jpg",
            ]

            clip_value = data.get("clip") or data.get("clip_path")
            image_value = (
                data.get("snapshot")
                or data.get("snapshot_path")
                or data.get("image")
                or data.get("image_path")
            )

            def resolve_declared_path(value):
                if not value:
                    return None
                declared = Path(str(value))
                if declared.is_absolute():
                    return declared
                local_candidate = event_dir / declared.name
                if local_candidate.exists():
                    return local_candidate
                return self.project_root / declared

            declared_clip = resolve_declared_path(clip_value)
            declared_image = resolve_declared_path(image_value)
            if declared_clip is not None:
                candidates_video.insert(0, declared_clip)
            if declared_image is not None:
                candidates_image.insert(0, declared_image)

            media_path = next(
                (path.resolve() for path in candidates_video if path.exists()),
                None,
            )
            media_type = "video"

            if media_path is None:
                media_path = next(
                    (path.resolve() for path in candidates_image if path.exists()),
                    None,
                )
                media_type = "image"

            if media_path is None:
                continue

            telegram_data = data.get("telegram") if isinstance(data.get("telegram"), dict) else {}
            zabbix_data = data.get("zabbix") if isinstance(data.get("zabbix"), dict) else {}

            timestamp_value = (
                data.get("timestamp")
                or data.get("start_time")
                or data.get("started_at")
                or data.get("date_time")
            )

            results.append({
                "id": event_id,
                "type": event_type,
                "channel": channel,
                "datetime": self._parse_event_datetime(timestamp_value, event_id),
                "duration": duration,
                "media_type": media_type,
                "media_url": f"/api/events/{event_id}/media",
                "download_url": f"/api/events/{event_id}/download",
                "media_path": str(media_path),
                "telegram": {
                    "attempted": bool(telegram_data.get("attempted") or telegram_data.get("sent")),
                    "sent": bool(telegram_data.get("sent")),
                    "time": str(telegram_data.get("time") or ""),
                    "status": str(telegram_data.get("status") or "pending"),
                },
                "zabbix": {
                    "attempted": bool(zabbix_data.get("attempted") or zabbix_data.get("sent")),
                    "sent": bool(zabbix_data.get("sent")),
                    "time": str(zabbix_data.get("time") or ""),
                },
            })

        return results

    @staticmethod
    def _get_local_ip():
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            sock.close()

    def _request_is_local(self):
        try:
            address = ipaddress.ip_address(request.remote_addr or "")
            return address.is_private or address.is_loopback
        except ValueError:
            return False

    def _network_details(self):
        result = {
            "ip": self._get_local_ip(),
            "netmask": "255.255.255.0",
            "gateway": "",
            "dns1": "",
            "dns2": "",
        }
        try:
            interfaces = json.loads(
                subprocess.check_output(
                    ["ip", "-j", "-4", "addr", "show", "scope", "global"],
                    text=True,
                    timeout=2,
                )
            )
            for interface in interfaces:
                if interface.get("addr_info"):
                    address = interface["addr_info"][0]
                    result["ip"] = address.get("local", result["ip"])
                    prefix = address.get("prefixlen", 24)
                    result["netmask"] = str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)
                    break
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
            pass
        try:
            routes = json.loads(
                subprocess.check_output(
                    ["ip", "-j", "route", "show", "default"],
                    text=True,
                    timeout=2,
                )
            )
            if routes:
                result["gateway"] = routes[0].get("gateway", "")
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            pass
        try:
            dns_values = []
            with open("/etc/resolv.conf", "r", encoding="utf-8") as file:
                for line in file:
                    if line.strip().startswith("nameserver "):
                        dns_values.append(line.split(None, 1)[1].strip())
            if dns_values:
                result["dns1"] = dns_values[0]
            if len(dns_values) > 1:
                result["dns2"] = dns_values[1]
        except OSError:
            pass
        return result

    def _cpu_usage(self):
        try:
            with open("/proc/stat", "r", encoding="utf-8") as file:
                values = [int(value) for value in file.readline().split()[1:]]
        except (OSError, ValueError, IndexError):
            return 0.0
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        with self._cpu_lock:
            if self._last_cpu_total is None:
                self._last_cpu_total = total
                self._last_cpu_idle = idle
                return 0.0
            total_delta = total - self._last_cpu_total
            idle_delta = idle - self._last_cpu_idle
            self._last_cpu_total = total
            self._last_cpu_idle = idle
        if total_delta <= 0:
            return 0.0
        return round(max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0)), 1)

    def _system_metrics(self):
        ram_total = ram_used = ram_percent = 0.0
        disk_total = disk_used = disk_free = disk_percent = 0.0
        temperature = None
        try:
            values = {}
            with open("/proc/meminfo", "r", encoding="utf-8") as file:
                for line in file:
                    key, value = line.split(":", 1)
                    values[key] = int(value.strip().split()[0])
            total_kb = values.get("MemTotal", 0)
            available_kb = values.get("MemAvailable", 0)
            used_kb = max(0, total_kb - available_kb)
            ram_total = total_kb / (1024 ** 2)
            ram_used = used_kb / (1024 ** 2)
            ram_percent = used_kb / total_kb * 100 if total_kb else 0
        except (OSError, ValueError):
            pass
        try:
            stat = os.statvfs("/")
            total_bytes = stat.f_blocks * stat.f_frsize
            free_bytes = stat.f_bavail * stat.f_frsize
            used_bytes = total_bytes - free_bytes
            disk_total = total_bytes / (1024 ** 3)
            disk_used = used_bytes / (1024 ** 3)
            disk_free = free_bytes / (1024 ** 3)
            disk_percent = used_bytes / total_bytes * 100 if total_bytes else 0
        except OSError:
            pass
        try:
            temperature = round(
                int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000,
                1,
            )
        except (OSError, ValueError):
            pass
        return {
            "cpu": self._cpu_usage(),
            "ram": round(ram_percent, 1),
            "ram_total_gb": round(ram_total, 1),
            "ram_used_gb": round(ram_used, 1),
            "ram_free_gb": round(max(0.0, ram_total - ram_used), 1),
            "disk": round(disk_percent, 1),
            "disk_total_gb": round(disk_total, 1),
            "disk_used_gb": round(disk_used, 1),
            "disk_free_gb": round(disk_free, 1),
            "temperature": temperature,
        }

    def _capture_uptimes(self, config):
        now = time.monotonic()
        result = {}
        for capture_id, capture in config["captures"].items():
            enabled = bool(capture.get("enabled", False))
            if enabled:
                started = self.capture_started_monotonic.setdefault(capture_id, self.service_started_monotonic)
                uptime = max(0, int(now - started))
                started_at = time.strftime("%d/%m/%Y %H:%M:%S", time.localtime(time.time() - uptime))
            else:
                self.capture_started_monotonic.pop(capture_id, None)
                uptime = 0
                started_at = "--/--/---- --:--:--"
            status = (
                self.capture_status.get(capture_id, "INICIANDO")
                if enabled
                else "DESHABILITADA"
            )
            result[capture_id] = {
                **{key: capture.get(key, "") for key in (
                    "hardware_id", "video_device", "station_id", "channel_name", "channel_number", "location"
                )},
                "enabled": enabled,
                "status": status,
                "uptime_seconds": uptime,
                "started_at": started_at,
            }
        return result

    def register_capture(self, capture_id, audio_monitor):
        if capture_id not in {"capture_1", "capture_2"}:
            raise ValueError("Capturadora lógica inválida")
        if capture_id in self.live_streamers:
            return
        self.audio_monitors[capture_id] = audio_monitor
        if capture_id == "capture_1":
            self.audio_monitor = audio_monitor
        output_directory = self.live_path / capture_id
        self.live_streamers[capture_id] = LiveHlsStreamer(
            audio_buffer=getattr(audio_monitor, "audio_buffer", None),
            output_directory=output_directory,
            width=640,
            height=360,
            output_width=480,
            output_height=270,
            fps=15.0,
            sample_rate=48000,
            channels=2,
            video_delay_seconds=0.8,
        )

    def set_capture_status(self, capture_id, status):
        if capture_id in self.capture_status:
            self.capture_status[capture_id] = str(status)
        if capture_id == "capture_1":
            self.channel_status = str(status)

    @staticmethod
    def _validate_ipv4(value, field_name, allow_empty=False):
        clean = str(value or "").strip()
        if allow_empty and not clean:
            return ""
        try:
            return str(ipaddress.IPv4Address(clean))
        except ValueError as error:
            raise ValueError(f"{field_name} inválido") from error

    def _schedule_system_command(self, action):
        commands = {
            "reboot": ["sudo", "/usr/bin/systemctl", "reboot"],
            "poweroff": ["sudo", "/usr/bin/systemctl", "poweroff"],
        }
        command = commands[action]
        timer = threading.Timer(
            1.5,
            lambda: subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            ),
        )
        timer.daemon = True
        timer.start()

    @staticmethod
    def _safe_template_name(value):
        raw = str(value or "").strip().lower()
        clean = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)
        clean = clean.strip("_-")
        if not clean:
            raise ValueError("Nombre de plantilla inválido")
        return clean[:60]

    def _template_capture_directory(self, capture_id):
        if capture_id not in {"capture_1", "capture_2"}:
            raise ValueError("Capturadora inválida")
        return self.templates_path / capture_id

    def _master_template_directory(self):
        return self.templates_path / "red2"

    def _template_metadata_from_payload(self, payload):
        name = str(payload.get("name", "")).strip()
        station_id = str(payload.get("station_id", "")).strip()
        virtual_channel = str(payload.get("virtual_channel", "")).strip()
        location = str(payload.get("location", "")).strip()

        if not name:
            raise ValueError("Nombre del canal requerido")
        if not station_id:
            raise ValueError("Distintivo requerido")
        if not virtual_channel:
            raise ValueError("Canal requerido")
        if not location:
            raise ValueError("Lugar o ciudad requerido")

        return {
            "name": name,
            "station_id": station_id,
            "virtual_channel": virtual_channel,
            "location": location,
            "template_threshold": 0.62,
            "confirmation_seconds": 0.5,
            "disappearance_seconds": 2.0,
            "processing_interval_seconds": 0.25,
            "roi": {
                "x": 0,
                "y": 0,
                "width": 320,
                "height": 100,
            },
        }

    def _copy_master_templates(self, target_dir):
        master_dir = self._master_template_directory()
        required = [master_dir / f"template_{index:02d}.png" for index in range(1, 5)]
        missing = [path.name for path in required if not path.exists()]
        if missing:
            raise ValueError(
                "Faltan plantillas maestras: " + ", ".join(missing)
            )

        target_dir.mkdir(parents=True, exist_ok=True)
        for old_file in target_dir.glob("template_*.png"):
            old_file.unlink()
        for source in required:
            shutil.copy2(source, target_dir / source.name)

    def _list_templates(self):
        self.templates_path.mkdir(parents=True, exist_ok=True)
        config = self._load_config()
        result = {"capture_1": [], "capture_2": []}

        for capture_id in result:
            capture_dir = self.templates_path / capture_id
            if capture_dir.exists():
                for folder in sorted(capture_dir.iterdir()):
                    if not folder.is_dir():
                        continue
                    preview = folder / "template_01.png"
                    if not preview.exists():
                        continue
                    metadata = {}
                    config_path = folder / "config.yaml"
                    if config_path.exists():
                        try:
                            metadata = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                        except (OSError, yaml.YAMLError):
                            metadata = {}
                    result[capture_id].append({
                        "name": folder.name,
                        "display_name": metadata.get("name", folder.name.upper()),
                        "created_at": metadata.get("created_at", ""),
                        "preview_url": f"/api/templates/{capture_id}/{folder.name}/preview",
                        "active": config["captures"][capture_id].get("template_name") == folder.name,
                    })
        return result

    def _sync_capture_template_config(self, capture_id, capture):
        """
        Sincroniza los datos descriptivos de la capturadora con el
        config.yaml de su plantilla, sin modificar las imágenes ni
        los parámetros técnicos ya existentes.
        """

        template_directories = []

        configured_directory = str(
            capture.get("template_directory", "")
        ).strip()

        if configured_directory:
            configured_path = Path(configured_directory)

            if not configured_path.is_absolute():
                configured_path = (
                    self.project_root
                    / configured_path
                )

            template_directories.append(
                configured_path
            )

        # Compatibilidad con la ruta maestra usada actualmente
        # por el detector de la Capturadora 1.
        if capture_id == "capture_1":
            template_directories.append(
                self.templates_path / "red2"
            )

        unique_directories = []

        for directory in template_directories:
            resolved = directory.resolve()

            if resolved not in unique_directories:
                unique_directories.append(
                    resolved
                )

        for directory in unique_directories:
            config_path = directory / "config.yaml"

            # No crea una plantilla inexistente ni toca sus imágenes.
            if not directory.exists():
                continue

            metadata = {}

            if config_path.exists():
                try:
                    metadata = (
                        yaml.safe_load(
                            config_path.read_text(
                                encoding="utf-8"
                            )
                        )
                        or {}
                    )
                except (
                    OSError,
                    yaml.YAMLError
                ):
                    metadata = {}

            metadata.update({
                "name": str(
                    capture.get(
                        "channel_name",
                        ""
                    )
                ).strip(),

                "station_id": str(
                    capture.get(
                        "station_id",
                        ""
                    )
                ).strip(),

                "virtual_channel": str(
                    capture.get(
                        "channel_number",
                        ""
                    )
                ).strip(),

                "location": str(
                    capture.get(
                        "location",
                        ""
                    )
                ).strip(),
            })

            # Conserva parámetros técnicos existentes. Si faltan,
            # usa los valores validados del detector actual.
            metadata.setdefault(
                "template_threshold",
                0.62
            )

            metadata.setdefault(
                "confirmation_seconds",
                0.5
            )

            metadata.setdefault(
                "disappearance_seconds",
                2.0
            )

            metadata.setdefault(
                "processing_interval_seconds",
                0.25
            )

            metadata.setdefault(
                "roi",
                {
                    "x": 0,
                    "y": 0,
                    "width": 320,
                    "height": 100,
                }
            )

            temporary_path = (
                config_path.with_suffix(
                    ".yaml.tmp"
                )
            )

            temporary_path.write_text(
                yaml.safe_dump(
                    metadata,
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            os.replace(
                temporary_path,
                config_path,
            )

    def _configure_routes(self):
        @self.app.route("/")
        def index():
            return render_template("index.html")

        @self.app.route("/video_feed")
        @self.app.route("/video_feed/<capture_id>")
        def video_feed(capture_id="capture_1"):
            if capture_id not in {"capture_1", "capture_2"}:
                return Response(status=404)
            return Response(
                self._generate_video_stream(capture_id),
                mimetype="multipart/x-mixed-replace; boundary=frame",
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache"
                }
            )

        @self.app.route("/audio_feed")
        def audio_feed():
            return Response(
                "El audio ahora forma parte de /live/stream.m3u8",
                status=410,
                mimetype="text/plain"
            )

        @self.app.route("/live/<capture_id>/<path:filename>")
        def live_media(capture_id, filename):

            if capture_id not in {"capture_1", "capture_2"}:
                return Response(status=404)

            if not (
                filename.endswith(".m3u8")
                or filename.endswith(".ts")
            ):
                return Response(status=404)

            response = send_from_directory(
                self.live_path / capture_id,
                filename,
                conditional=False,
                max_age=0
            )

            response.headers[
                "Cache-Control"
            ] = (
                "no-store, no-cache, "
                "must-revalidate, max-age=0"
            )

            response.headers[
                "Pragma"
            ] = "no-cache"

            return response

        @self.app.route("/live/<path:filename>")
        def legacy_live_media(filename):
            """Compatibilidad con marcadores/pruebas del HLS anterior."""
            if not (filename.endswith(".m3u8") or filename.endswith(".ts")):
                return Response(status=404)
            response = send_from_directory(
                self.live_path / "capture_1",
                filename,
                conditional=False,
                max_age=0,
            )
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            response.headers["Pragma"] = "no-cache"
            return response

        @self.app.route("/audio_levels")
        @self.app.route("/audio_levels/<capture_id>")
        def audio_levels(capture_id="capture_1"):
            monitor = self.audio_monitors.get(capture_id)
            if monitor is None:
                return jsonify({"db": -90.0, "left_db": -90.0, "right_db": -90.0})
            levels = monitor.get_levels()
            return {
                "db": max(levels["left_db"], levels["right_db"]),
                "left_db": levels["left_db"],
                "right_db": levels["right_db"],
            }

        @self.app.route("/status")
        def status():
            config = self._load_config()
            return jsonify({
                "status": self.channel_status,
                "last_event": self.last_event,
                "ip": self._get_local_ip(),
                "metrics": self._system_metrics(),
                "captures": self._capture_uptimes(config),
            })

        @self.app.route("/api/config")
        def get_config():
            config = self._load_config()
            config["network"].update(self._network_details())
            for capture in config["captures"].values():
                capture.pop("audio_device", None)
            integrations = self._load_integrations()
            config["integrations"] = {
                "telegram": {
                    "enabled": integrations["telegram"].get("enabled", False),
                    "chat_id": integrations["telegram"].get("chat_id", ""),
                    "token_configured": bool(integrations["telegram"].get("token")),
                    "channel_id_enabled": integrations["telegram"].get("channel_id_enabled", False),
                    "morning_enabled": integrations["telegram"].get("morning_enabled", False),
                    "morning_time": integrations["telegram"].get("morning_time", "06:00"),
                    "afternoon_enabled": integrations["telegram"].get("afternoon_enabled", False),
                    "afternoon_time": integrations["telegram"].get("afternoon_time", "17:00"),
                },
                "snmp": {
                    "enabled": integrations["snmp"].get("enabled", False),
                    "zabbix_server": integrations["snmp"].get(
                        "zabbix_server", ""
                    ),
                    "agent_port": integrations["snmp"].get(
                        "agent_port", 161
                    ),
                    "trap_port": integrations["snmp"].get(
                        "trap_port", 162
                    ),
                    "community_configured": bool(
                        integrations["snmp"].get("community")
                    ),
                    "oid_base": "1.3.6.1.4.1.8072.9999.1",
                },
                "vpn": self.vpn_manager.public_configuration(
                    integrations.get("vpn", {})
                ),
                "security": {
                    "configured": bool(integrations["security"].get("password_hash")),
                    "username": integrations["security"].get("username", ""),
                },
            }
            return jsonify(config)

        @self.app.route("/api/hardware/captures")
        def get_capture_hardware():
            return jsonify({
                "maximum": 2,
                "devices": self.hardware_discovery.discover(),
            })

        @self.app.route("/api/config/captures", methods=["POST"])
        def save_captures():
            payload = request.get_json(silent=True) or {}
            config = self._load_config()
            discovered = {
                item["hardware_id"]: item
                for item in self.hardware_discovery.discover()
            }
            try:
                for capture_id in ("capture_1", "capture_2"):
                    incoming = payload.get(capture_id, {})
                    hardware_id = str(incoming.get("hardware_id", "")).strip()
                    enabled = bool(incoming.get("enabled", False))
                    hardware = discovered.get(hardware_id)
                    if enabled and hardware is None:
                        raise ValueError(f"{capture_id}: selecciona una capturadora USB disponible")
                    config["captures"][capture_id].update({
                        "hardware_id": hardware_id,
                        "video_device": hardware["video_device"] if hardware else "",
                        "audio_device": hardware["audio_device"] if hardware else "",
                        "enabled": enabled,
                        "station_id": str(incoming.get("station_id", "")).strip()[:80],
                        "channel_name": str(incoming.get("channel_name", "")).strip()[:80],
                        "channel_number": str(incoming.get("channel_number", "")).strip()[:40],
                        "location": str(incoming.get("location", "")).strip()[:120],
                    })
                if (
                    config["captures"]["capture_1"].get("enabled")
                    and config["captures"]["capture_2"].get("enabled")
                    and config["captures"]["capture_1"]["hardware_id"]
                    == config["captures"]["capture_2"]["hardware_id"]
                ):
                    raise ValueError("Los dos canales no pueden usar la misma capturadora física")
                self._save_config(config)

                for capture_id in (
                    "capture_1",
                    "capture_2",
                ):
                    self._sync_capture_template_config(
                        capture_id,
                        config["captures"][capture_id],
                    )

            except (OSError, ValueError) as error:
                return jsonify({"ok": False, "message": str(error)}), 400
            return jsonify({
                "ok": True,
                "message": "Configuración guardada. Reinicia el servicio para activar los pipelines y la marca de agua.",
            })

        @self.app.route("/api/events")
        def list_events():
            events = self._list_events()
            for item in events:
                item.pop("media_path", None)
            return jsonify(events)

        @self.app.route("/api/events/<event_id>/media")
        def event_media(event_id):
            event = next((item for item in self._list_events() if item["id"] == event_id), None)
            if event is None:
                return jsonify({"ok": False, "message": "Evidencia no encontrada"}), 404
            return send_file(event["media_path"], conditional=True)

        @self.app.route("/api/events/<event_id>/download")
        def event_download(event_id):
            event = next((item for item in self._list_events() if item["id"] == event_id), None)
            if event is None:
                return jsonify({"ok": False, "message": "Evidencia no encontrada"}), 404
            return send_file(event["media_path"], as_attachment=True)

        @self.app.route("/api/config/telegram", methods=["POST"])
        def save_telegram():
            if not self._request_is_local():
                return jsonify({"ok": False, "message": "Acceso no autorizado"}), 403
            payload = request.get_json(silent=True) or {}
            integrations = self._load_integrations()
            authorized, message = self._authorize_telegram_update(payload.get("auth"))
            if not authorized:
                return jsonify({"ok": False, "message": message}), 401
            telegram = payload.get("telegram") or {}
            chat_id = str(telegram.get("chat_id", "")).strip()
            token = str(telegram.get("token", "")).strip()
            enabled = bool(telegram.get("enabled", False))
            channel_id_enabled = bool(
                telegram.get("channel_id_enabled", False)
            )
            morning_enabled = bool(
                telegram.get("morning_enabled", False)
            )
            afternoon_enabled = bool(
                telegram.get("afternoon_enabled", False)
            )

            try:
                morning_time = self._validate_schedule_time(
                    telegram.get("morning_time", "06:00"),
                    "Horario de mañana",
                )
                afternoon_time = self._validate_schedule_time(
                    telegram.get("afternoon_time", "17:00"),
                    "Horario de tarde",
                )
            except ValueError as error:
                return jsonify({"ok": False, "message": str(error)}), 400

            if enabled and not chat_id:
                return jsonify({"ok": False, "message": "El ID del grupo es obligatorio."}), 400
            if enabled and not token and not integrations["telegram"].get("token"):
                return jsonify({"ok": False, "message": "El token del bot es obligatorio."}), 400
            integrations["telegram"]["enabled"] = enabled
            integrations["telegram"]["chat_id"] = chat_id
            integrations["telegram"]["channel_id_enabled"] = channel_id_enabled
            integrations["telegram"]["morning_enabled"] = morning_enabled
            integrations["telegram"]["morning_time"] = morning_time
            integrations["telegram"]["afternoon_enabled"] = afternoon_enabled
            integrations["telegram"]["afternoon_time"] = afternoon_time
            if token:
                integrations["telegram"]["token"] = token
            self._save_integrations(integrations)
            return jsonify({"ok": True, "message": "Configuración de Telegram guardada."})

        @self.app.route("/api/config/vpn", methods=["POST"])
        def save_vpn():
            if not self._request_is_local():
                return jsonify({"ok": False, "message": "Acceso no autorizado"}), 403

            payload = request.get_json(silent=True) or {}
            authorized, message = self._authorize_telegram_update(
                payload.get("auth")
            )

            if not authorized:
                return jsonify({"ok": False, "message": message}), 401

            integrations = self._load_integrations()
            current = integrations.get(
                "vpn",
                VpnManager.defaults(),
            )

            try:
                requested = self.vpn_manager.normalize(
                    payload.get("vpn")
                )
                applied = self.vpn_manager.apply(
                    current,
                    requested,
                )
            except ValueError as error:
                return jsonify({"ok": False, "message": str(error)}), 400
            except RuntimeError as error:
                return jsonify({"ok": False, "message": str(error)}), 409

            integrations["vpn"] = applied
            self._save_integrations(integrations)

            return jsonify({
                "ok": True,
                "message": "Configuración VPN aplicada correctamente.",
                "vpn": self.vpn_manager.public_configuration(applied),
            })

        @self.app.route("/api/config/network-snmp", methods=["POST"])
        def save_network_snmp():
            if not self._request_is_local():
                return jsonify({"ok": False, "message": "Acceso no autorizado"}), 403
            payload = request.get_json(silent=True) or {}
            integrations = self._load_integrations()
            authorized, message = self._authorize_update(payload.get("auth"), integrations)
            if not authorized:
                return jsonify({"ok": False, "message": message}), 401
            network_payload = payload.get("network") or {}
            snmp_payload = payload.get("snmp") or {}
            try:
                network = {
                    "ip": self._validate_ipv4(network_payload.get("ip"), "IP"),
                    "netmask": self._validate_ipv4(network_payload.get("netmask"), "Netmask"),
                    "gateway": self._validate_ipv4(network_payload.get("gateway"), "Gateway"),
                    "dns1": self._validate_ipv4(network_payload.get("dns1"), "DNS1"),
                    "dns2": self._validate_ipv4(network_payload.get("dns2"), "DNS2", allow_empty=True),
                }
                zabbix_server = self._validate_ipv4(
                    snmp_payload.get("zabbix_server"),
                    "Servidor Zabbix",
                    allow_empty=not bool(snmp_payload.get("enabled", False)),
                )
                agent_port = int(snmp_payload.get("agent_port", 161))
                trap_port = int(snmp_payload.get("trap_port", 162))
                if not 1 <= agent_port <= 65535:
                    raise ValueError("Puerto de consultas SNMP inválido")
                if not 1 <= trap_port <= 65535:
                    raise ValueError("Puerto de traps SNMP inválido")
            except (ValueError, TypeError) as error:
                return jsonify({"ok": False, "message": str(error)}), 400
            config = self._load_config()
            config["network"] = network
            self._save_config(config)
            enabled = bool(snmp_payload.get("enabled", False))
            community = str(snmp_payload.get("community", "")).strip()
            if not community:
                community = str(
                    integrations["snmp"].get("community", "")
                ).strip()
            if enabled and not 8 <= len(community) <= 64:
                return jsonify({
                    "ok": False,
                    "message": (
                        "La comunidad SNMPv2c debe tener entre "
                        "8 y 64 caracteres."
                    ),
                }), 400

            snmp_configuration = {
                "enabled": enabled,
                "zabbix_server": zabbix_server,
                "agent_port": agent_port,
                "trap_port": trap_port,
                "community": community,
                "long_event_seconds": 60.0,
            }

            if self.zabbix_notifier is None:
                return jsonify({
                    "ok": False,
                    "message": "La integración Zabbix/SNMP no está iniciada.",
                }), 503

            applied, apply_message = (
                self.zabbix_notifier.apply_agent_configuration(
                    snmp_configuration
                )
            )
            if not applied:
                return jsonify({
                    "ok": False,
                    "message": apply_message,
                }), 409

            integrations["snmp"] = snmp_configuration
            self._save_integrations(integrations)
            return jsonify({
                "ok": True,
                "message": (
                    "Configuración de Red y SNMP aplicada. "
                    + apply_message
                ),
            })

        @self.app.route("/api/config/network", methods=["POST"])
        def save_network():
            if not self._request_is_local():
                return jsonify({"ok": False, "message": "Acceso no autorizado"}), 403
            payload = request.get_json(silent=True) or {}
            try:
                network = {
                    "ip": self._validate_ipv4(payload.get("ip"), "IP"),
                    "netmask": self._validate_ipv4(payload.get("netmask"), "Netmask"),
                    "gateway": self._validate_ipv4(payload.get("gateway"), "Gateway"),
                    "dns1": self._validate_ipv4(payload.get("dns1"), "DNS1"),
                    "dns2": self._validate_ipv4(payload.get("dns2"), "DNS2", allow_empty=True),
                }
            except ValueError as error:
                return jsonify({"ok": False, "message": str(error)}), 400
            config = self._load_config()
            config["network"] = network
            self._save_config(config)
            return jsonify({"ok": True, "message": "Configuración de red guardada."})

        @self.app.route("/api/templates")
        def list_templates():
            return jsonify(self._list_templates())

        @self.app.route("/api/templates", methods=["POST"])
        def save_template():
            if not self._request_is_local():
                return jsonify({"ok": False, "message": "Acceso no autorizado"}), 403

            payload = request.get_json(silent=True) or {}
            capture_id = str(payload.get("capture_id", "")).strip()
            action = str(payload.get("action", "save")).strip().lower()

            try:
                if action not in {"save", "modify"}:
                    raise ValueError("Acción inválida")

                config = self._load_config()
                if capture_id not in config["captures"]:
                    raise ValueError("Capturadora inválida")

                metadata = self._template_metadata_from_payload(payload)
                safe_name = self._safe_template_name(metadata["name"])
                capture_dir = self._template_capture_directory(capture_id)
                target_dir = capture_dir / safe_name

                current_name = str(
                    config["captures"][capture_id].get("template_name", "")
                ).strip()

                if action == "save" and target_dir.exists():
                    raise ValueError("La plantilla ya existe; usa Modificar")

                if action == "modify" and current_name and current_name != safe_name:
                    old_dir = capture_dir / current_name
                    if old_dir.exists() and not target_dir.exists():
                        old_dir.rename(target_dir)

                self._copy_master_templates(target_dir)
                metadata_text = yaml.safe_dump(
                    metadata, allow_unicode=True, sort_keys=False
                )
                (target_dir / "config.yaml").write_text(
                    metadata_text, encoding="utf-8"
                )

                capture = config["captures"][capture_id]
                capture["station_id"] = metadata["station_id"]
                capture["channel_name"] = metadata["name"]
                capture["channel_number"] = metadata["virtual_channel"]
                capture["location"] = metadata["location"]
                capture["template_name"] = safe_name
                capture["template_directory"] = str(
                    target_dir.relative_to(self.project_root)
                )
                self._save_config(config)

                # El detector actual de la Capturadora 1 usa esta ruta fija.
                if capture_id == "capture_1":
                    master_dir = self._master_template_directory()
                    (master_dir / "config.yaml").write_text(
                        metadata_text, encoding="utf-8"
                    )

            except (ValueError, OSError) as error:
                return jsonify({"ok": False, "message": str(error)}), 400

            return jsonify({
                "ok": True,
                "message": "Datos de plantilla guardados y asignados a la capturadora.",
            })

        @self.app.route("/api/templates/<capture_id>/<template_name>", methods=["DELETE"])
        def delete_template(capture_id, template_name):
            if not self._request_is_local():
                return jsonify({"ok": False, "message": "Acceso no autorizado"}), 403
            try:
                safe_name = self._safe_template_name(template_name)
                target_dir = self._template_capture_directory(capture_id) / safe_name
                if not target_dir.exists() or not target_dir.is_dir():
                    raise ValueError("Plantilla no encontrada")

                for item in target_dir.iterdir():
                    if item.is_file():
                        item.unlink()
                target_dir.rmdir()

                config = self._load_config()
                capture = config["captures"][capture_id]
                if capture.get("template_name") == safe_name:
                    capture["template_name"] = ""
                    capture["template_directory"] = ""
                    self._save_config(config)
                    if capture_id == "capture_1":
                        legacy_dir = self.templates_path / "red2"
                        if legacy_dir.exists():
                            for legacy_file in legacy_dir.iterdir():
                                if legacy_file.is_file():
                                    legacy_file.unlink()

            except (ValueError, OSError) as error:
                return jsonify({"ok": False, "message": str(error)}), 400

            return jsonify({"ok": True, "message": "Plantilla eliminada."})

        @self.app.route("/api/templates/<capture_id>/<template_name>/preview")
        def template_preview(capture_id, template_name):
            try:
                safe_name = self._safe_template_name(template_name)
                path = self._template_capture_directory(capture_id) / safe_name / "template_01.png"
                if not path.exists():
                    raise ValueError("Vista previa no encontrada")
            except ValueError as error:
                return jsonify({"ok": False, "message": str(error)}), 404
            return send_file(path, conditional=True)

        @self.app.route("/system/reboot", methods=["POST"])
        def reboot_system():
            self._schedule_system_command("reboot")
            return jsonify({
                "ok": True,
                "message": "La Raspberry Pi se reiniciará."
            })

        @self.app.route("/system/shutdown", methods=["POST"])
        def shutdown_system():
            self._schedule_system_command("poweroff")
            return jsonify({
                "ok": True,
                "message": "La Raspberry Pi se apagará."
            })

    def update_frame(self, capture_id, frame=None):
        # Compatibilidad con llamadas antiguas update_frame(frame).
        if frame is None:
            frame = capture_id
            capture_id = "capture_1"
        if frame is None:
            return

        streamer = self.live_streamers.get(capture_id)
        if streamer is not None:
            streamer.update_frame(frame)

        with self.lock:
            has_mjpeg_clients = (
                self.mjpeg_clients.get(capture_id, 0) > 0
            )

        if not has_mjpeg_clients:
            self.set_capture_status(capture_id, "ONLINE")
            return

        # La vista MJPEG se conserva únicamente como respaldo. Se
        # limita a 10 FPS para no cargar el ciclo de detectores.
        now = time.monotonic()

        if (
            now
            - self.last_jpeg_monotonic.get(capture_id, 0.0)
            < 0.1
        ):
            self.set_capture_status(capture_id, "ONLINE")
            return

        self.last_jpeg_monotonic[capture_id] = now

        success, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 76])
        if not success:
            return
        with self.lock:
            self.latest_frames[capture_id] = frame.copy()
            self.latest_jpegs[capture_id] = encoded.tobytes()
        self.set_capture_status(capture_id, "ONLINE")

    def update_event(self, event):
        if event:
            self.last_event = f"{event.get('type', 'unknown')} - {event.get('id', '')}"

    def _generate_video_stream(self, capture_id):

        with self.lock:
            self.mjpeg_clients[capture_id] += 1

        try:

            while True:
                with self.lock:
                    jpeg = self.latest_jpegs.get(capture_id)
                if jpeg is None:
                    time.sleep(0.05)
                    continue
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                time.sleep(0.04)

        finally:

            with self.lock:
                self.mjpeg_clients[capture_id] = max(
                    0,
                    self.mjpeg_clients[capture_id] - 1
                )

    def _generate_audio_stream(self):
        config = self._load_config()
        audio_device = config["captures"]["capture_1"].get("audio_device", "")
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-thread_queue_size", "512", "-f", "alsa", "-ac", "2", "-ar", "48000",
            "-i", audio_device, "-vn", "-ac", "2", "-ar", "48000",
            "-codec:a", "libmp3lame", "-b:a", "128k", "-f", "mp3", "pipe:1",
        ]
        process = None
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            while True:
                chunk = process.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
        except (GeneratorExit, OSError):
            pass
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    def start(self):
        for streamer in self.live_streamers.values():
            streamer.start()

        thread = threading.Thread(
            target=self.app.run,
            kwargs={
                "host": self.host,
                "port": self.port,
                "debug": False,
                "use_reloader": False,
                "threaded": True,
            },
            daemon=True,
        )
        thread.start()

    def stop(self):
        for streamer in self.live_streamers.values():
            streamer.stop()
