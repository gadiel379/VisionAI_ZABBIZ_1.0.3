# -*- coding: utf-8 -*-

import subprocess
import threading
import time

import numpy as np


class AudioMonitor:

    def __init__(
        self,
        device="hw:3,0",
        sample_rate=48000,
        channels=2,
        chunk_frames=2048,
        audio_buffer=None,
        device_resolver=None,
        reconnect_delay=2.0,
        state_callback=None,
        recovery_chunks=5,
    ):
        self.device = str(device)
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.chunk_frames = int(chunk_frames)
        self.audio_buffer = audio_buffer
        self.device_resolver = device_resolver
        self.reconnect_delay = max(0.5, float(reconnect_delay))
        self.state_callback = state_callback
        self.recovery_chunks = max(1, int(recovery_chunks))

        self.left_db = -90.0
        self.right_db = -90.0
        self.running = False
        self.process = None
        self.thread = None
        self.lock = threading.Lock()
        self.online = False

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
        if self.thread is not None and self.thread.is_alive():
            self.thread.join(timeout=2)

    def get_levels(self):
        with self.lock:
            return {
                "left_db": round(self.left_db, 1),
                "right_db": round(self.right_db, 1),
            }

    def get_combined_level(self):
        levels = self.get_levels()
        return max(levels["left_db"], levels["right_db"])

    def _set_silence(self):
        with self.lock:
            self.left_db = -90.0
            self.right_db = -90.0

    def _set_online(self, online):
        online = bool(online)
        with self.lock:
            if self.online == online:
                return
            self.online = online
        if self.state_callback is not None:
            try:
                self.state_callback(online)
            except Exception as error:
                print(f"[AUDIO MONITOR] Error en callback de estado: {error}")

    def _resolved_device(self):
        if self.device_resolver is None:
            return self.device
        try:
            resolved = self.device_resolver()
        except Exception as error:
            print(f"[AUDIO MONITOR] Error resolviendo dispositivo USB: {error}")
            return None
        if not resolved:
            return None
        return str(resolved)

    def _wait_reconnect(self):
        deadline = time.monotonic() + self.reconnect_delay
        while self.running and time.monotonic() < deadline:
            time.sleep(0.1)

    def _capture_loop(self):
        bytes_per_frame = self.channels * 2
        chunk_size = self.chunk_frames * bytes_per_frame

        while self.running:
            device = self._resolved_device()
            if not device:
                self._set_silence()
                self._wait_reconnect()
                continue

            self.device = device
            command = [
                "arecord", "-D", device,
                "-f", "S16_LE",
                "-r", str(self.sample_rate),
                "-c", str(self.channels),
                "-t", "raw", "-q",
            ]

            try:
                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=0,
                )
                consecutive_chunks = 0

                while self.running:
                    data = self.process.stdout.read(chunk_size)
                    if not data:
                        break

                    timestamp = time.time()
                    if self.audio_buffer is not None:
                        self.audio_buffer.add(timestamp, data)
                    consecutive_chunks += 1
                    if consecutive_chunks == self.recovery_chunks:
                        self._set_online(True)
                        print(
                            "[AUDIO MONITOR] Dispositivo operativo y estable: "
                            f"{device}"
                        )

                    samples = np.frombuffer(data, dtype=np.int16)
                    if samples.size < self.channels:
                        continue
                    usable_samples = samples.size - (samples.size % self.channels)
                    stereo = samples[:usable_samples].reshape(-1, self.channels)
                    left_db = self._rms_db(stereo[:, 0].astype(np.float32))
                    right_db = self._rms_db(stereo[:, 1].astype(np.float32))
                    with self.lock:
                        self.left_db = left_db
                        self.right_db = right_db

            except Exception as error:
                print(f"[AUDIO MONITOR] Error: {error}")
            finally:
                return_code = None
                if self.process is not None:
                    return_code = self.process.poll()
                self._set_online(False)
                self._set_silence()
                if self.process is not None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                    self.process = None

            if self.running:
                print(
                    f"[AUDIO MONITOR] Audio perdido en {device}; "
                    "iniciando reconexion automatica "
                    f"(codigo={return_code})"
                )
                self._wait_reconnect()

    @staticmethod
    def _rms_db(samples):
        if samples.size == 0:
            return -90.0
        normalized = samples / 32768.0
        rms = np.sqrt(np.mean(np.square(normalized)))
        if rms <= 0.000001:
            return -90.0
        return max(-90.0, float(20.0 * np.log10(rms)))
