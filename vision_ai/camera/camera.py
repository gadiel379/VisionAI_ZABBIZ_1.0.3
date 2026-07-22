# -*- coding: utf-8 -*-

"""Captura V4L2 con reconexion automatica del dispositivo USB."""

import threading
import time
from pathlib import Path

import cv2


class Camera:

    def __init__(
        self,
        device,
        width,
        height,
        fps,
        device_resolver=None,
        reconnect_delay=2.0,
        failed_reads_before_reconnect=3,
    ):
        self.device = str(device)
        self.width = int(width)
        self.height = int(height)
        self.fps = float(fps)
        self.device_resolver = device_resolver
        self.reconnect_delay = max(0.5, float(reconnect_delay))
        self.failed_reads_before_reconnect = max(
            1, int(failed_reads_before_reconnect)
        )

        self.cap = None
        self.failed_reads = 0
        self.next_reconnect_at = 0.0
        self.lock = threading.Lock()

        with self.lock:
            self._open_locked()

    def _resolved_device(self):
        if self.device_resolver is None:
            return self.device
        try:
            resolved = self.device_resolver()
        except Exception as error:
            print(f"[CAMERA] Error resolviendo dispositivo USB: {error}")
            return None
        if not resolved:
            return None
        return str(resolved)

    def _release_locked(self):
        if self.cap is None:
            return
        try:
            self.cap.release()
        except Exception:
            pass
        self.cap = None

    @staticmethod
    def _opencv_device(device):
        """Convierte /dev/videoN al indice que CAP_V4L2 reabre mejor.

        Algunas versiones de OpenCV abren la ruta en el primer arranque pero,
        despues de un hot-plug, rechazan la misma cadena con el mensaje
        "can't be used to capture by name". El indice numerico evita ese
        estado interno sin perder la resolucion fisica hecha por discovery.
        """
        text = str(device).strip()
        name = Path(text).name
        if text.startswith("/dev/video") and name.startswith("video"):
            suffix = name[5:]
            if suffix.isdigit():
                return int(suffix)
        return text

    def _open_locked(self):
        self._release_locked()
        device = self._resolved_device()
        if not device:
            self.next_reconnect_at = time.monotonic() + self.reconnect_delay
            return False

        cap = None
        try:
            cap = cv2.VideoCapture(
                self._opencv_device(device),
                cv2.CAP_V4L2,
            )
            if not cap.isOpened():
                cap.release()
                self.next_reconnect_at = time.monotonic() + self.reconnect_delay
                return False

            cap.set(
                cv2.CAP_PROP_FOURCC,
                cv2.VideoWriter_fourcc(*"MJPG"),
            )
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
        except Exception as error:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
            self.next_reconnect_at = time.monotonic() + self.reconnect_delay
            print(f"[CAMERA] Error abriendo {device}: {error}")
            return False

        self.cap = cap
        self.device = device
        self.failed_reads = 0
        self.next_reconnect_at = 0.0
        print(f"[CAMERA] Dispositivo operativo: {self.device}")
        return True

    def read(self):
        with self.lock:
            if self.cap is None:
                if time.monotonic() < self.next_reconnect_at:
                    return None
                if not self._open_locked():
                    return None

            try:
                ok, frame = self.cap.read()
            except Exception as error:
                ok, frame = False, None
                print(
                    f"[CAMERA] Error transitorio leyendo {self.device}: "
                    f"{error}"
                )

            if ok and frame is not None:
                self.failed_reads = 0
                return frame

            self.failed_reads += 1
            if self.failed_reads >= self.failed_reads_before_reconnect:
                lost_device = self.device
                self._release_locked()
                self.failed_reads = 0
                self.next_reconnect_at = time.monotonic() + self.reconnect_delay
                print(
                    f"[CAMERA] Sin frames en {lost_device}; "
                    "iniciando reconexion automatica"
                )
            return None

    def release(self):
        with self.lock:
            self._release_locked()
