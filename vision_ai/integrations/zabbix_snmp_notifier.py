# -*- coding: utf-8 -*-

"""Publica el estado actual de Vision AI para consultas SNMP.

Este módulo no envía traps. Los eventos confirmados, las identificaciones y
el estado físico de cada capturadora se guardan en ``storage/snmp/metrics.json``
para que ``snmp_pass_persist.py`` los exponga a Zabbix.
"""

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import yaml


class ZabbixSnmpNotifier:
    """Mantiene métricas SNMP sin bloquear los pipelines de captura."""

    BASE_OID = "1.3.6.1.4.1.8072.9999.1"

    SUPPORTED_FAILURES = {
        "black": "black",
        "no_audio": "no_audio",
        "artifact": "digitalization",
        "freeze": "frozen",
    }

    CAPTURE_IDS = ("capture_1", "capture_2")
    IDENTIFICATION_PULSE_SECONDS = 10.0
    FRAME_TIMEOUT_SECONDS = 3.0
    METRICS_INTERVAL_SECONDS = 1.0

    DEFAULTS = {
        "enabled": False,
        "zabbix_server": "",
        "agent_port": 161,
        "community": "",
    }

    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()
        self.config_path = self.project_root / "config" / "integrations.yaml"
        self.channels_path = self.project_root / "config" / "channels.yaml"
        self.metrics_directory = self.project_root / "storage" / "snmp"
        self.metrics_path = self.metrics_directory / "metrics.json"

        self.running = True
        self.lock = threading.RLock()
        self.capture_heartbeats = {}
        self.previous_cpu = None
        self.failure_states = {
            capture_id: {
                "black": 0,
                "no_audio": 0,
                "digitalization": 0,
                "frozen": 0,
            }
            for capture_id in self.CAPTURE_IDS
        }
        self.channel_id_deadlines = {
            capture_id: 0.0 for capture_id in self.CAPTURE_IDS
        }

        self.metrics_directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.metrics_directory, 0o755)
        except OSError:
            pass

        self.metrics_thread = threading.Thread(
            target=self._metrics_loop,
            name="zabbix-snmp-metrics",
            daemon=True,
        )
        self.metrics_thread.start()

        print(
            "[ZABBIX SNMP] Métricas por consulta iniciadas "
            f"árbol={self.BASE_OID}; traps deshabilitados"
        )

    @staticmethod
    def _text(value, limit=160):
        return str(value or "").replace("\x00", " ").replace("\n", " ")[:limit]

    def _configuration(self):
        loaded = {}
        try:
            with self.config_path.open("r", encoding="utf-8") as file:
                loaded = yaml.safe_load(file) or {}
        except (OSError, yaml.YAMLError):
            loaded = {}

        section = loaded.get("snmp", {}) or {}
        result = dict(self.DEFAULTS)
        result.update(section)
        if not result.get("community"):
            result["community"] = (
                section.get("read_community")
                or section.get("public_community")
                or ""
            )
        return result

    def update_capture_frame(self, capture_id):
        """Registra que una capturadora entregó un frame utilizable."""
        capture_id = str(capture_id)
        if capture_id not in self.CAPTURE_IDS:
            return
        with self.lock:
            self.capture_heartbeats[capture_id] = time.monotonic()

    def notify_event_action(self, action):
        """Actualiza 1/0 usando acciones ya confirmadas por EventEngine."""
        if not isinstance(action, dict):
            return
        event = action.get("event")
        event_action = str(action.get("action") or "")
        if not isinstance(event, dict) or event_action not in ("started", "recovered"):
            return

        metric_name = self.SUPPORTED_FAILURES.get(str(event.get("type") or ""))
        capture_id = str(event.get("capture_id") or "capture_1")
        if metric_name is None or capture_id not in self.CAPTURE_IDS:
            return

        value = 1 if event_action == "started" else 0
        with self.lock:
            self.failure_states[capture_id][metric_name] = value

        print(
            f"[ZABBIX SNMP] {capture_id} {metric_name}={value} "
            f"acción={event_action}"
        )

    def notify_channel_id_event(self, event):
        """Inicia un pulso de identificación de exactamente 10 segundos."""
        if not isinstance(event, dict):
            return
        capture_id = str(event.get("capture_id") or "capture_1")
        if capture_id not in self.CAPTURE_IDS:
            return
        with self.lock:
            self.channel_id_deadlines[capture_id] = (
                time.monotonic() + self.IDENTIFICATION_PULSE_SECONDS
            )
        print(f"[ZABBIX SNMP] {capture_id} channel_id=1 durante 10 segundos")

    def _read_cpu_percent(self):
        try:
            values = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0]
            numbers = [int(item) for item in values.split()[1:]]
            idle = numbers[3] + (numbers[4] if len(numbers) > 4 else 0)
            total = sum(numbers)
        except (OSError, ValueError, IndexError):
            return 0.0

        previous = self.previous_cpu
        self.previous_cpu = (total, idle)
        if previous is None:
            return 0.0
        total_delta = total - previous[0]
        idle_delta = idle - previous[1]
        if total_delta <= 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta))

    @staticmethod
    def _ram_percent():
        try:
            values = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                key, raw = line.split(":", 1)
                values[key] = int(raw.strip().split()[0])
            total = values["MemTotal"]
            available = values.get("MemAvailable", values.get("MemFree", 0))
            return 100.0 * (total - available) / total if total else 0.0
        except (OSError, ValueError, KeyError):
            return 0.0

    @staticmethod
    def _temperature_celsius():
        try:
            raw = Path("/sys/class/thermal/thermal_zone0/temp").read_text(
                encoding="utf-8"
            )
            value = float(raw.strip())
            return value / 1000.0 if value > 200.0 else value
        except (OSError, ValueError):
            return 0.0

    def _channels_configuration(self):
        try:
            with self.channels_path.open("r", encoding="utf-8") as file:
                return (yaml.safe_load(file) or {}).get("captures", {}) or {}
        except (OSError, yaml.YAMLError):
            return {}

    def _capture_status(self, capture_id, capture):
        """0=operación normal; 1=falla física, desconexión o sin frames."""
        if not bool(capture.get("enabled", False)):
            return 0

        device_value = str(capture.get("video_device") or "").strip()
        if not device_value or not Path(device_value).exists():
            return 1

        with self.lock:
            heartbeat = self.capture_heartbeats.get(capture_id)
        if heartbeat is None:
            return 1
        if time.monotonic() - heartbeat > self.FRAME_TIMEOUT_SECONDS:
            return 1
        return 0

    def _capture_snapshot(self, capture_id, captures, now_monotonic):
        capture = captures.get(capture_id, {}) or {}
        with self.lock:
            failures = dict(self.failure_states[capture_id])
            channel_id = int(
                now_monotonic < self.channel_id_deadlines[capture_id]
            )

        return {
            "station_id": self._text(capture.get("station_id"), 80),
            "name": self._text(capture.get("channel_name"), 80),
            "channel": self._text(capture.get("channel_number"), 40),
            "location": self._text(capture.get("location"), 120),
            "enabled": int(bool(capture.get("enabled", False))),
            "status": self._capture_status(capture_id, capture),
            "black": int(failures["black"]),
            "no_audio": int(failures["no_audio"]),
            "digitalization": int(failures["digitalization"]),
            "frozen": int(failures["frozen"]),
            "channel_id": channel_id,
        }

    def _metrics_snapshot(self):
        usage = shutil.disk_usage(self.project_root)
        captures = self._channels_configuration()
        now_monotonic = time.monotonic()

        return {
            "version": 2,
            "updated_epoch": int(time.time()),
            "service_status": 1,
            "cpu_basis_points": int(round(self._read_cpu_percent() * 100.0)),
            "ram_basis_points": int(round(self._ram_percent() * 100.0)),
            "temperature_decicelsius": int(round(self._temperature_celsius() * 10.0)),
            "disk_used_basis_points": int(round((usage.used / usage.total) * 10000.0)),
            "disk_total_mb": int(usage.total / (1024 * 1024)),
            "disk_free_mb": int(usage.free / (1024 * 1024)),
            "captures": {
                capture_id: self._capture_snapshot(
                    capture_id, captures, now_monotonic
                )
                for capture_id in self.CAPTURE_IDS
            },
        }

    def _write_metrics(self):
        snapshot = self._metrics_snapshot()
        temporary = self.metrics_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o644)
        os.replace(temporary, self.metrics_path)

    def _metrics_loop(self):
        while self.running:
            try:
                self._write_metrics()
            except (OSError, ValueError, ZeroDivisionError) as error:
                print(f"[ZABBIX SNMP] Error de métricas: {error}")
            deadline = time.monotonic() + self.METRICS_INTERVAL_SECONDS
            while self.running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, 0.2))

    def apply_agent_configuration(self, configuration):
        helper = "/usr/local/sbin/vision-ai-snmpctl"
        if not Path(helper).exists():
            return False, "Falta instalar el controlador SNMP privilegiado."

        payload = {
            "enabled": bool(configuration.get("enabled", False)),
            "zabbix_server": str(configuration.get("zabbix_server") or ""),
            "agent_port": int(configuration.get("agent_port", 161)),
            "community": str(configuration.get("community") or ""),
            "project_root": str(self.project_root),
        }
        try:
            result = subprocess.run(
                ["sudo", "-n", helper],
                input=json.dumps(payload),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, str(error)

        message = (result.stdout or result.stderr or "").strip()
        return result.returncode == 0, message or "Configuración SNMP aplicada."

    def stop(self):
        self.running = False
        self.metrics_thread.join(timeout=2.0)
        try:
            self._write_metrics()
        except (OSError, ValueError, ZeroDivisionError):
            pass
        print("[ZABBIX SNMP] Integración detenida")
