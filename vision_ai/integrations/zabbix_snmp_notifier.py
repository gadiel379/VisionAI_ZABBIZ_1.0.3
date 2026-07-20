# -*- coding: utf-8 -*-

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml


class ZabbixSnmpNotifier:
    """Métricas SNMP y traps SNMPv2c para Vision AI.

    El árbol 1.3.6.1.4.1.8072.9999.1 es de uso local. No representa
    un PEN registrado por Televisa y no debe anunciarse fuera de esta red.
    """

    BASE_OID = "1.3.6.1.4.1.8072.9999.1"
    TRAP_SHORT_RECOVERED = BASE_OID + ".0.1"
    TRAP_LONG_ACTIVE = BASE_OID + ".0.2"
    TRAP_LONG_RECOVERED = BASE_OID + ".0.3"
    TRAP_CHANNEL_ID = BASE_OID + ".0.4"

    EVENT_OIDS = {
        "event_id": BASE_OID + ".3.1",
        "state": BASE_OID + ".3.2",
        "type_code": BASE_OID + ".3.3",
        "type_name": BASE_OID + ".3.4",
        "channel": BASE_OID + ".3.5",
        "station_id": BASE_OID + ".3.6",
        "virtual_channel": BASE_OID + ".3.7",
        "capture_id": BASE_OID + ".3.8",
        "started_at": BASE_OID + ".3.9",
        "ended_at": BASE_OID + ".3.10",
        "duration_centiseconds": BASE_OID + ".3.11",
        "event_epoch": BASE_OID + ".3.12",
    }

    SUPPORTED_FAILURES = {
        "black": (1, "PANTALLA NEGRA"),
        "no_audio": (2, "SIN AUDIO"),
        "artifact": (3, "DIGITALIZACION"),
        "freeze": (4, "IMAGEN CONGELADA"),
    }

    DEFAULTS = {
        "enabled": False,
        "zabbix_server": "",
        "agent_port": 161,
        "trap_port": 162,
        "community": "",
        "long_event_seconds": 60.0,
    }

    def __init__(self, project_root):
        self.project_root = Path(project_root).resolve()
        self.config_path = self.project_root / "config" / "integrations.yaml"
        self.channels_path = self.project_root / "config" / "channels.yaml"
        self.metrics_directory = self.project_root / "storage" / "snmp"
        self.metrics_path = self.metrics_directory / "metrics.json"

        self.running = True
        self.lock = threading.RLock()
        self.active_events = {}
        self.capture_heartbeats = {}
        self.last_event = self._empty_last_event()
        self.tasks = queue.Queue()
        self.previous_cpu = None

        self.metrics_directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.metrics_directory, 0o755)
        except OSError:
            pass

        self.worker_thread = threading.Thread(
            target=self._worker_loop,
            name="zabbix-snmp-traps",
            daemon=True,
        )
        self.monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="zabbix-long-events",
            daemon=True,
        )
        self.metrics_thread = threading.Thread(
            target=self._metrics_loop,
            name="zabbix-snmp-metrics",
            daemon=True,
        )

        self.worker_thread.start()
        self.monitor_thread.start()
        self.metrics_thread.start()

        print(
            "[ZABBIX SNMP] Integración iniciada "
            f"árbol={self.BASE_OID}"
        )

    @staticmethod
    def _empty_last_event():
        return {
            "event_id": "",
            "state": 0,
            "type_code": 0,
            "type_name": "SIN EVENTOS",
            "channel": "",
            "station_id": "",
            "virtual_channel": "",
            "capture_id": "",
            "started_at": "",
            "ended_at": "",
            "duration_centiseconds": 0,
            "event_epoch": 0,
        }

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

        # Migración transparente de la configuración visual anterior.
        if not result.get("community"):
            result["community"] = (
                section.get("read_community")
                or section.get("public_community")
                or ""
            )
        return result

    @staticmethod
    def _timestamp(value, fallback=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(fallback)

    @staticmethod
    def _format_time(timestamp):
        if not timestamp:
            return ""
        return datetime.fromtimestamp(float(timestamp)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    @staticmethod
    def _text(value, limit=160):
        return str(value or "").replace("\x00", " ")[:limit]

    def update_capture_frame(self, capture_id):
        with self.lock:
            self.capture_heartbeats[str(capture_id)] = time.monotonic()

    def notify_event_action(self, action):
        if not isinstance(action, dict):
            return
        event = action.get("event")
        event_action = str(action.get("action") or "")
        if not isinstance(event, dict):
            return
        if event.get("type") not in self.SUPPORTED_FAILURES:
            return

        event_id = self._text(event.get("id"), 80)
        if not event_id:
            return

        if event_action == "started":
            with self.lock:
                self.active_events[event_id] = {
                    "event": event,
                    "long_sent": False,
                }
            return

        if event_action != "recovered":
            return

        duration = self._timestamp(event.get("duration_seconds"), 0.0)
        with self.lock:
            tracked = self.active_events.pop(event_id, None)

        long_sent = bool(tracked and tracked.get("long_sent"))
        threshold = self._timestamp(
            self._configuration().get("long_event_seconds"),
            60.0,
        )

        if duration >= threshold:
            if not long_sent:
                self._enqueue("long_active", event)
            self._enqueue("long_recovered", event)
        else:
            self._enqueue("short_recovered", event)

    def notify_channel_id_event(self, event):
        if not isinstance(event, dict):
            return
        self._enqueue("channel_id", event)

    def _enqueue(self, task_type, event):
        if not self.running:
            return
        self.tasks.put((str(task_type), event))

    def _monitor_loop(self):
        while self.running:
            now = time.time()
            threshold = self._timestamp(
                self._configuration().get("long_event_seconds"),
                60.0,
            )
            with self.lock:
                for tracked in self.active_events.values():
                    event = tracked["event"]
                    started = self._timestamp(
                        event.get("failure_started_timestamp"),
                        now,
                    )
                    if not tracked["long_sent"] and now - started >= threshold:
                        tracked["long_sent"] = True
                        # Se encola antes de liberar el bloqueo. Así una
                        # recuperación simultánea nunca puede adelantarse al
                        # trap que declara la falla larga como activa.
                        self._enqueue("long_active", event)

            time.sleep(0.5)

    def _worker_loop(self):
        while self.running or not self.tasks.empty():
            try:
                task_type, event = self.tasks.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                self._process_task(task_type, event)
            except Exception as error:
                print(f"[ZABBIX SNMP] Error de envío: {error}")
            finally:
                self.tasks.task_done()

    def _process_task(self, task_type, event):
        if task_type == "channel_id":
            fields = self._channel_id_fields(event)
            trap_oid = self.TRAP_CHANNEL_ID
        else:
            fields = self._failure_fields(task_type, event)
            trap_oid = {
                "short_recovered": self.TRAP_SHORT_RECOVERED,
                "long_active": self.TRAP_LONG_ACTIVE,
                "long_recovered": self.TRAP_LONG_RECOVERED,
            }[task_type]

        with self.lock:
            self.last_event = dict(fields)

        sent, status, detail = self._send_trap(trap_oid, fields)
        self._record_delivery(event, task_type, sent, status, detail)

    def _failure_fields(self, task_type, event):
        event_type = str(event.get("type") or "")
        type_code, type_name = self.SUPPORTED_FAILURES[event_type]
        started = self._timestamp(event.get("failure_started_timestamp"), 0.0)
        ended = self._timestamp(event.get("ended_timestamp"), 0.0)
        duration = self._timestamp(event.get("duration_seconds"), 0.0)

        if task_type == "long_active":
            state = 2
            ended = 0.0
            duration = max(60.0, time.time() - started)
        else:
            state = 1

        return {
            "event_id": self._text(event.get("id"), 80),
            "state": state,
            "type_code": type_code,
            "type_name": type_name,
            "channel": self._text(
                event.get("channel_name") or event.get("channel"), 80
            ),
            "station_id": self._text(event.get("station_id"), 80),
            "virtual_channel": self._text(event.get("virtual_channel"), 40),
            "capture_id": self._text(event.get("capture_id"), 40),
            "started_at": self._format_time(started),
            "ended_at": self._format_time(ended),
            "duration_centiseconds": int(round(max(0.0, duration) * 100.0)),
            "event_epoch": int(ended or time.time()),
        }

    def _channel_id_fields(self, event):
        raw_time = event.get("time") or event.get("timestamp")
        try:
            event_time = datetime.fromisoformat(str(raw_time)).timestamp()
        except (TypeError, ValueError):
            event_time = time.time()

        return {
            "event_id": self._text(event.get("id"), 80),
            "state": 3,
            "type_code": 5,
            "type_name": "IDENTIFICACION DE CANAL",
            "channel": self._text(
                event.get("expected_name") or event.get("channel"), 80
            ),
            "station_id": self._text(
                event.get("expected_station_id")
                or event.get("detected_station_id"),
                80,
            ),
            "virtual_channel": self._text(
                event.get("expected_virtual_channel")
                or event.get("virtual_channel"),
                40,
            ),
            "capture_id": self._text(event.get("capture_id") or "capture_1", 40),
            "started_at": self._format_time(event_time),
            "ended_at": "",
            "duration_centiseconds": 0,
            "event_epoch": int(event_time),
        }

    def _send_trap(self, trap_oid, fields):
        config = self._configuration()
        if not bool(config.get("enabled")):
            return False, "disabled", "SNMP deshabilitado"

        target = self._text(config.get("zabbix_server"), 64)
        community = self._text(config.get("community"), 80)
        try:
            port = int(config.get("trap_port", 162))
        except (TypeError, ValueError):
            port = 162

        if not target or not community:
            return False, "not_configured", "Falta servidor o comunidad"
        if shutil.which("snmptrap") is None:
            return False, "missing_snmptrap", "No está instalado snmptrap"

        command = [
            "snmptrap", "-v", "2c", "-c", community,
            f"udp:{target}:{port}", "", "." + trap_oid,
        ]

        integer_fields = {
            "state", "type_code", "duration_centiseconds", "event_epoch"
        }
        for field_name, oid in self.EVENT_OIDS.items():
            value = fields.get(field_name, "")
            if field_name in integer_fields:
                command.extend(["." + oid, "i", str(int(value or 0))])
            else:
                command.extend(["." + oid, "s", self._text(value)])

        try:
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return False, "error", str(error)

        if result.returncode != 0:
            return False, "error", (result.stderr or "snmptrap falló")[-300:]

        print(
            "[ZABBIX SNMP] Trap enviado "
            f"oid={trap_oid} evento={fields['event_id']}"
        )
        return True, "sent", ""

    def _record_delivery(self, event, task_type, sent, status, detail):
        delivery = event.setdefault("zabbix", {})
        history = delivery.setdefault("history", [])
        item = {
            "kind": task_type,
            "attempted": status not in ("disabled", "not_configured"),
            "sent": bool(sent),
            "status": status,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if detail:
            item["detail"] = self._text(detail, 300)
        history.append(item)
        delivery.update(item)

        json_path = event.get("json")
        if not json_path:
            return
        path = Path(json_path)
        if not path.is_absolute():
            path = self.project_root / path
        try:
            current = {}
            if path.exists():
                current = json.loads(path.read_text(encoding="utf-8"))
            current["zabbix"] = delivery
            temporary = path.with_suffix(".json.zabbix.tmp")
            temporary.write_text(
                json.dumps(current, indent=4, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            os.replace(temporary, path)
        except (OSError, ValueError, TypeError) as error:
            print(f"[ZABBIX SNMP] No se actualizó event.json: {error}")

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

    def _capture_state(self, capture_id, captures):
        capture = captures.get(capture_id, {}) or {}
        if not bool(capture.get("enabled", False)):
            return 0
        device = Path(str(capture.get("video_device") or ""))
        if not device.exists():
            return 3
        with self.lock:
            heartbeat = self.capture_heartbeats.get(capture_id)
        if heartbeat is not None and time.monotonic() - heartbeat <= 3.0:
            return 1
        return 2

    def _metrics_snapshot(self):
        usage = shutil.disk_usage(self.project_root)
        captures = self._channels_configuration()
        with self.lock:
            last_event = dict(self.last_event)

        return {
            "version": 1,
            "updated_epoch": int(time.time()),
            "service_status": 1,
            "cpu_basis_points": int(round(self._read_cpu_percent() * 100.0)),
            "ram_basis_points": int(round(self._ram_percent() * 100.0)),
            "temperature_decicelsius": int(round(self._temperature_celsius() * 10.0)),
            "disk_used_basis_points": int(round((usage.used / usage.total) * 10000.0)),
            "disk_total_mb": int(usage.total / (1024 * 1024)),
            "disk_free_mb": int(usage.free / (1024 * 1024)),
            "capture_1_state": self._capture_state("capture_1", captures),
            "capture_2_state": self._capture_state("capture_2", captures),
            "last_event": last_event,
        }

    def _metrics_loop(self):
        while self.running:
            try:
                snapshot = self._metrics_snapshot()
                temporary = self.metrics_path.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(snapshot, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                os.chmod(temporary, 0o644)
                os.replace(temporary, self.metrics_path)
            except (OSError, ValueError, ZeroDivisionError) as error:
                print(f"[ZABBIX SNMP] Error de métricas: {error}")
            time.sleep(5.0)

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
        for thread in (self.worker_thread, self.monitor_thread, self.metrics_thread):
            thread.join(timeout=2.0)
        print("[ZABBIX SNMP] Integración detenida")
