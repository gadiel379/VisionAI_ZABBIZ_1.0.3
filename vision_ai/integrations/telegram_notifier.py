# -*- coding: utf-8 -*-

import copy
import http.client
import json
import mimetypes
import os
import queue
import threading
import uuid
from datetime import datetime
from html import escape
from pathlib import Path

import yaml


class TelegramNotifier:
    """Envía alarmas finalizadas sin bloquear el pipeline de monitoreo."""

    SUPPORTED_EVENT_TYPES = {
        "black",
        "artifact",
        "freeze",
        "no_audio",
    }

    EVENT_LABELS = {
        "black": "PANTALLA NEGRA",
        "artifact": "DIGITALIZACIÓN",
        "freeze": "IMAGEN CONGELADA",
        "no_audio": "SIN AUDIO",
    }

    def __init__(self, project_root=None, max_queue_size=100):
        self.project_root = Path(
            project_root
            or Path(__file__).resolve().parent.parent
        ).resolve()

        self.config_path = (
            self.project_root
            / "config"
            / "integrations.yaml"
        )

        self.queue = queue.Queue(
            maxsize=max(1, int(max_queue_size))
        )

        self.stop_event = threading.Event()

        self.worker = threading.Thread(
            target=self._worker_loop,
            name="telegram-notifier",
            daemon=True,
        )

        self.worker.start()

        print(
            "[TELEGRAM] Notificador final iniciado"
        )

    def notify_completed_event(self, event):
        """Encola una sola notificación cuando el clip ya está terminado."""

        if not isinstance(event, dict):
            return False

        event_type = str(
            event.get("type", "")
        ).strip()

        if event_type not in self.SUPPORTED_EVENT_TYPES:
            return False

        if event.get("status") != "recovered":
            return False

        if not event.get("clip"):
            return False

        try:
            self.queue.put_nowait(
                {
                    "kind": "alarm",
                    "event": copy.deepcopy(event),
                }
            )
        except queue.Full:
            print(
                "[TELEGRAM] Cola llena; "
                f"no se pudo encolar el evento {event.get('id', '')}"
            )
            return False

        print(
            "[TELEGRAM] Evento encolado: "
            f"{event.get('id', '')}"
        )

        return True

    def notify_channel_id_event(self, event):
        """Encola una identificación; el horario se valida en el trabajador."""

        if not isinstance(event, dict):
            return False

        if str(event.get("type", "")) != "channel_id":
            return False

        try:
            self.queue.put_nowait(
                {
                    "kind": "channel_id",
                    "event": copy.deepcopy(event),
                }
            )
        except queue.Full:
            print(
                "[TELEGRAM ID] Cola llena; "
                f"no se pudo encolar el evento {event.get('id', '')}"
            )
            return False

        return True

    def stop(self, timeout=3.0):
        self.stop_event.set()

        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass

        self.worker.join(
            timeout=max(0.0, float(timeout))
        )

    def _worker_loop(self):
        while not self.stop_event.is_set():
            try:
                task = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                if task is None:
                    return

                kind = str(task.get("kind", ""))
                event = task.get("event") or {}

                if kind == "alarm":
                    self._process_alarm_event(event)
                elif kind == "channel_id":
                    self._process_channel_id_event(event)

            except Exception as error:
                print(
                    "[TELEGRAM] Error interno: "
                    f"{self._safe_error(error)}"
                )

            finally:
                self.queue.task_done()

    def _load_configuration(self):
        try:
            with self.config_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                configuration = yaml.safe_load(file) or {}
        except (OSError, yaml.YAMLError) as error:
            print(
                "[TELEGRAM] No se pudo leer integrations.yaml: "
                f"{self._safe_error(error)}"
            )
            return None

        telegram = configuration.get("telegram")

        if not isinstance(telegram, dict):
            return None

        if not bool(telegram.get("enabled", False)):
            return None

        token = str(
            telegram.get("token", "")
            or ""
        ).strip()

        chat_id = str(
            telegram.get("chat_id", "")
            or ""
        ).strip()

        if not token or not chat_id:
            print(
                "[TELEGRAM] Integración habilitada, "
                "pero faltan token o chat ID"
            )
            return None

        return {
            "token": token,
            "chat_id": chat_id,
            "channel_id_enabled": bool(
                telegram.get(
                    "channel_id_enabled",
                    False,
                )
            ),
            "morning_enabled": bool(
                telegram.get(
                    "morning_enabled",
                    False,
                )
            ),
            "morning_time": str(
                telegram.get(
                    "morning_time",
                    "06:00",
                )
            ),
            "afternoon_enabled": bool(
                telegram.get(
                    "afternoon_enabled",
                    False,
                )
            ),
            "afternoon_time": str(
                telegram.get(
                    "afternoon_time",
                    "17:00",
                )
            ),
        }

    def _process_alarm_event(self, event):
        configuration = self._load_configuration()

        if configuration is None:
            return

        event_id = str(event.get("id", ""))
        clip_path = self._resolve_clip_path(event)

        attempted_at = datetime.now().isoformat(
            sep=" ",
            timespec="seconds",
        )

        if clip_path is None:
            self._save_delivery_status(
                event,
                {
                    "attempted": True,
                    "sent": False,
                    "status": "failed",
                    "time": attempted_at,
                    "error": "No se encontró el clip final del evento",
                },
            )

            print(
                "[TELEGRAM] No enviado; "
                f"clip inexistente para {event_id}"
            )
            return

        caption = self._build_caption(event)

        try:
            response = self._send_video(
                token=configuration["token"],
                chat_id=configuration["chat_id"],
                clip_path=clip_path,
                caption=caption,
            )

            result = response.get("result") or {}

            self._save_delivery_status(
                event,
                {
                    "attempted": True,
                    "sent": True,
                    "status": "sent",
                    "time": datetime.now().isoformat(
                        sep=" ",
                        timespec="seconds",
                    ),
                    "message_id": result.get("message_id"),
                },
            )

            print(
                "[TELEGRAM] Enviado: "
                f"evento={event_id}"
            )

        except Exception as error:
            safe_error = self._safe_error(
                error,
                configuration["token"],
            )

            self._save_delivery_status(
                event,
                {
                    "attempted": True,
                    "sent": False,
                    "status": "failed",
                    "time": attempted_at,
                    "error": safe_error,
                },
            )

            print(
                "[TELEGRAM] No enviado: "
                f"evento={event_id} error={safe_error}"
            )

    def _process_channel_id_event(self, event):
        configuration = self._load_configuration()
        event_id = str(event.get("id", ""))

        if configuration is None:
            return

        if not configuration["channel_id_enabled"]:
            self._save_delivery_status(
                event,
                {
                    "attempted": False,
                    "sent": False,
                    "status": "disabled",
                },
            )
            return

        event_time = self._channel_event_datetime(event)

        if not self._inside_channel_id_window(
            event_time,
            configuration,
        ):
            self._save_delivery_status(
                event,
                {
                    "attempted": False,
                    "sent": False,
                    "status": "outside_schedule",
                },
            )
            return

        snapshot_path = self._resolve_image_path(event)
        attempted_at = datetime.now().isoformat(
            sep=" ",
            timespec="seconds",
        )

        if snapshot_path is None:
            self._save_delivery_status(
                event,
                {
                    "attempted": True,
                    "sent": False,
                    "status": "failed",
                    "time": attempted_at,
                    "error": "No se encontró la imagen de identificación",
                },
            )
            return

        try:
            response = self._send_photo(
                token=configuration["token"],
                chat_id=configuration["chat_id"],
                image_path=snapshot_path,
                caption=self._build_channel_id_caption(event),
            )

            result = response.get("result") or {}

            self._save_delivery_status(
                event,
                {
                    "attempted": True,
                    "sent": True,
                    "status": "sent",
                    "time": datetime.now().isoformat(
                        sep=" ",
                        timespec="seconds",
                    ),
                    "message_id": result.get("message_id"),
                    "schedule_window": self._matching_window(
                        event_time,
                        configuration,
                    ),
                },
            )

            print(
                "[TELEGRAM ID] Enviado: "
                f"evento={event_id}"
            )

        except Exception as error:
            safe_error = self._safe_error(
                error,
                configuration["token"],
            )

            self._save_delivery_status(
                event,
                {
                    "attempted": True,
                    "sent": False,
                    "status": "failed",
                    "time": attempted_at,
                    "error": safe_error,
                },
            )

            print(
                "[TELEGRAM ID] No enviado: "
                f"evento={event_id} error={safe_error}"
            )

    def _resolve_clip_path(self, event):
        declared = Path(
            str(event.get("clip", ""))
        ).expanduser()

        candidates = []

        if declared.is_absolute():
            candidates.append(declared)
        else:
            candidates.append(
                self.project_root / declared
            )

            folder = Path(
                str(event.get("folder", ""))
            )

            if folder:
                if not folder.is_absolute():
                    folder = self.project_root / folder

                candidates.append(
                    folder / declared.name
                )

        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue

            if resolved.is_file():
                return resolved

        return None

    def _resolve_image_path(self, event):
        for key in (
            "snapshot",
            "banner",
            "roi",
        ):
            declared_text = str(
                event.get(key, "")
                or ""
            ).strip()

            if not declared_text:
                continue

            declared = Path(declared_text)

            if not declared.is_absolute():
                declared = self.project_root / declared

            try:
                resolved = declared.resolve()
            except OSError:
                continue

            if resolved.is_file():
                return resolved

        return None

    @staticmethod
    def _channel_event_datetime(event):
        value = (
            event.get("timestamp")
            or event.get("time")
        )

        if value:
            try:
                return datetime.fromisoformat(
                    str(value).replace("Z", "+00:00")
                ).replace(tzinfo=None)
            except ValueError:
                pass

        return datetime.now()

    @staticmethod
    def _time_to_minutes(value):
        try:
            hours_text, minutes_text = str(value).split(
                ":",
                1,
            )
            hours = int(hours_text)
            minutes = int(minutes_text)
        except (TypeError, ValueError):
            return None

        if not 0 <= hours <= 23:
            return None

        if not 0 <= minutes <= 59:
            return None

        return hours * 60 + minutes

    @classmethod
    def _minute_inside_window(cls, current, start):
        if start is None:
            return False

        return (current - start) % (24 * 60) < 60

    @classmethod
    def _matching_window(cls, event_time, configuration):
        current = (
            int(event_time.hour) * 60
            + int(event_time.minute)
        )

        windows = (
            (
                "morning",
                configuration.get("morning_enabled", False),
                configuration.get("morning_time", "06:00"),
            ),
            (
                "afternoon",
                configuration.get("afternoon_enabled", False),
                configuration.get("afternoon_time", "17:00"),
            ),
        )

        for name, enabled, start_text in windows:
            if not enabled:
                continue

            start = cls._time_to_minutes(start_text)

            if cls._minute_inside_window(
                current,
                start,
            ):
                return (
                    f"{name}:"
                    f"{str(start_text)[:5]}"
                )

        return ""

    @classmethod
    def _inside_channel_id_window(
        cls,
        event_time,
        configuration,
    ):
        return bool(
            cls._matching_window(
                event_time,
                configuration,
            )
        )

    def _event_json_path(self, event):
        declared = str(event.get("json", "")).strip()

        if declared:
            path = Path(declared)

            if not path.is_absolute():
                path = self.project_root / path

            return path.resolve()

        folder = Path(
            str(event.get("folder", ""))
        )

        if not folder.is_absolute():
            folder = self.project_root / folder

        return (folder / "event.json").resolve()

    def _save_delivery_status(self, event, status):
        json_path = self._event_json_path(event)
        json_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:
            current = json.loads(
                json_path.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError):
            current = copy.deepcopy(event)

        current["telegram"] = dict(status)

        temporary = json_path.with_suffix(
            ".json.telegram.tmp"
        )

        temporary.write_text(
            json.dumps(
                current,
                indent=4,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )

        os.replace(
            temporary,
            json_path,
        )

    def _build_caption(self, event):
        event_type = str(event.get("type", ""))
        label = self.EVENT_LABELS.get(
            event_type,
            event_type.upper(),
        )

        channel = str(
            event.get("channel_name")
            or event.get("channel")
            or "Sin definir"
        )

        station = str(
            event.get("station_id")
            or "Sin definir"
        )

        virtual_channel = str(
            event.get("virtual_channel")
            or "Sin definir"
        )

        location = str(
            event.get("location")
            or "Sin definir"
        )

        capture_id = str(
            event.get("capture_id")
            or "capture_1"
        )

        duration = self._number(
            event.get("duration_seconds")
        )

        started_at = self._format_datetime(
            event.get("failure_started_at")
        )

        ended_at = self._format_datetime(
            event.get("ended_at")
        )

        safe_label = self._html(label)
        safe_channel = self._html(channel)
        safe_station = self._html(station)
        safe_virtual_channel = self._html(
            virtual_channel
        )
        safe_location = self._html(location)
        safe_capture_id = self._html(capture_id)
        safe_started_at = self._html(started_at)
        safe_ended_at = self._html(ended_at)
        safe_event_id = self._html(
            event.get("id", "")
        )

        return "\n".join(
            [
                "🔵 <b>ALARMA FINALIZADA</b>",
                "",
                f"<b>Tipo:</b> {safe_label}",
                f"<b>Canal:</b> {safe_channel} | {safe_station} | {safe_virtual_channel}",
                f"<b>Ubicación:</b> {safe_location}",
                f"<b>Capturadora:</b> {safe_capture_id}",
                f"<b>Inicio:</b> {safe_started_at}",
                f"<b>Fin:</b> {safe_ended_at}",
                f"<b>Duración real:</b> {duration:.2f} segundos",
                f"<b>Evento:</b> {safe_event_id}",
            ]
        )

    def _build_channel_id_caption(self, event):
        expected_station = str(
            event.get("expected_station_id")
            or "Sin definir"
        )

        expected_channel = str(
            event.get("expected_virtual_channel")
            or event.get("virtual_channel")
            or "Sin definir"
        )

        channel_name = str(
            event.get("expected_name")
            or event.get("channel")
            or "Sin definir"
        )

        detected_station = str(
            event.get("detected_station_id")
            or "Sin definir"
        )

        detected_channel = str(
            event.get("detected_virtual_channel")
            or "Sin definir"
        )

        status = str(
            event.get("identification_status")
            or "detected"
        ).upper()

        location = str(
            event.get("detected_location")
            or event.get("expected_location")
            or "Sin definir"
        )

        event_time = self._format_datetime(
            event.get("timestamp")
            or event.get("time")
        )

        safe_channel_name = self._html(channel_name)
        safe_expected_station = self._html(
            expected_station
        )
        safe_expected_channel = self._html(
            expected_channel
        )
        safe_detected_station = self._html(
            detected_station
        )
        safe_detected_channel = self._html(
            detected_channel
        )
        safe_location = self._html(location)
        safe_status = self._html(status)
        safe_event_time = self._html(event_time)
        safe_event_id = self._html(
            event.get("id", "")
        )

        return "\n".join(
            [
                "🔵 <b>IDENTIFICACIÓN DE CANAL</b>",
                "",
                f"<b>Canal esperado:</b> {safe_channel_name} | {safe_expected_station} | {safe_expected_channel}",
                f"<b>Detectado:</b> {safe_detected_station} | {safe_detected_channel}",
                f"<b>Ubicación:</b> {safe_location}",
                f"<b>Estado:</b> {safe_status}",
                f"<b>Fecha y hora:</b> {safe_event_time}",
                f"<b>Evento:</b> {safe_event_id}",
            ]
        )

    @staticmethod
    def _html(value):
        return escape(
            str(value),
            quote=False,
        )

    @staticmethod
    def _number(value):
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _format_datetime(value):
        if value is None:
            return "Sin definir"

        text = str(value).replace("T", " ")

        if "." in text:
            text = text.split(".", 1)[0]

        return text

    def _send_video(
        self,
        token,
        chat_id,
        clip_path,
        caption,
    ):
        return self._send_media(
            token=token,
            chat_id=chat_id,
            endpoint="sendVideo",
            field_name="video",
            media_path=clip_path,
            caption=caption,
            extra_fields={
                "supports_streaming": "true",
            },
        )

    def _send_photo(
        self,
        token,
        chat_id,
        image_path,
        caption,
    ):
        return self._send_media(
            token=token,
            chat_id=chat_id,
            endpoint="sendPhoto",
            field_name="photo",
            media_path=image_path,
            caption=caption,
        )

    def _send_media(
        self,
        token,
        chat_id,
        endpoint,
        field_name,
        media_path,
        caption,
        extra_fields=None,
    ):
        boundary = (
            "----VisionAI"
            + uuid.uuid4().hex
        )

        fields = {
            "chat_id": str(chat_id),
            "caption": str(caption),
            "parse_mode": "HTML",
        }

        fields.update(extra_fields or {})

        field_parts = []

        for name, value in fields.items():
            field_parts.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode("utf-8")
            )

        filename = media_path.name.replace(
            '"',
            "_",
        )

        mime_type = (
            mimetypes.guess_type(filename)[0]
            or "application/octet-stream"
        )

        file_header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("utf-8")

        closing = (
            f"\r\n--{boundary}--\r\n"
        ).encode("utf-8")

        content_length = (
            sum(len(part) for part in field_parts)
            + len(file_header)
            + media_path.stat().st_size
            + len(closing)
        )

        connection = http.client.HTTPSConnection(
            "api.telegram.org",
            timeout=90,
        )

        try:
            connection.putrequest(
                "POST",
                f"/bot{token}/{endpoint}",
            )

            connection.putheader(
                "Content-Type",
                f"multipart/form-data; boundary={boundary}",
            )

            connection.putheader(
                "Content-Length",
                str(content_length),
            )

            connection.endheaders()

            for part in field_parts:
                connection.send(part)

            connection.send(file_header)

            with media_path.open("rb") as file:
                while True:
                    chunk = file.read(256 * 1024)

                    if not chunk:
                        break

                    connection.send(chunk)

            connection.send(closing)

            response = connection.getresponse()
            payload = response.read()

        finally:
            connection.close()

        try:
            decoded = json.loads(
                payload.decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = {}

        if response.status != 200 or not decoded.get("ok"):
            description = str(
                decoded.get("description")
                or f"HTTP {response.status}"
            )
            raise RuntimeError(description)

        return decoded

    @staticmethod
    def _safe_error(error, token=""):
        message = str(error) or error.__class__.__name__

        if token:
            message = message.replace(
                str(token),
                "[TOKEN OCULTO]",
            )

        return message[:500]
