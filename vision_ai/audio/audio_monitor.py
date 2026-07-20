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
        audio_buffer=None
    ):
        self.device = device
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.chunk_frames = int(chunk_frames)

        self.audio_buffer = audio_buffer

        self.left_db = -90.0
        self.right_db = -90.0

        self.running = False
        self.process = None
        self.thread = None

        self.lock = threading.Lock()

    def start(self):

        if self.running:
            return

        self.running = True

        self.thread = threading.Thread(
            target=self._capture_loop,
            daemon=True
        )

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

        if (
            self.thread is not None
            and self.thread.is_alive()
        ):
            self.thread.join(timeout=2)

    def get_levels(self):

        with self.lock:

            return {
                "left_db": round(
                    self.left_db,
                    1
                ),
                "right_db": round(
                    self.right_db,
                    1
                )
            }

    def get_combined_level(self):

        levels = self.get_levels()

        return max(
            levels["left_db"],
            levels["right_db"]
        )

    def _capture_loop(self):

        command = [
            "arecord",
            "-D",
            self.device,
            "-f",
            "S16_LE",
            "-r",
            str(self.sample_rate),
            "-c",
            str(self.channels),
            "-t",
            "raw",
            "-q"
        ]

        bytes_per_sample = 2

        bytes_per_frame = (
            self.channels
            * bytes_per_sample
        )

        chunk_size = (
            self.chunk_frames
            * bytes_per_frame
        )

        while self.running:

            try:

                self.process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=0
                )

                while self.running:

                    data = self.process.stdout.read(
                        chunk_size
                    )

                    if not data:
                        break

                    timestamp = time.time()

                    if self.audio_buffer is not None:

                        self.audio_buffer.add(
                            timestamp,
                            data
                        )

                    samples = np.frombuffer(
                        data,
                        dtype=np.int16
                    )

                    if samples.size < self.channels:
                        continue

                    usable_samples = (
                        samples.size
                        - (
                            samples.size
                            % self.channels
                        )
                    )

                    samples = samples[
                        :usable_samples
                    ]

                    stereo = samples.reshape(
                        -1,
                        self.channels
                    )

                    left = stereo[:, 0].astype(
                        np.float32
                    )

                    right = stereo[:, 1].astype(
                        np.float32
                    )

                    left_db = self._rms_db(
                        left
                    )

                    right_db = self._rms_db(
                        right
                    )

                    with self.lock:

                        self.left_db = left_db
                        self.right_db = right_db

            except Exception as error:

                print(
                    "[AUDIO MONITOR] Error:",
                    error
                )

                with self.lock:

                    self.left_db = -90.0
                    self.right_db = -90.0

                time.sleep(1)

            finally:

                if self.process is not None:

                    self.process.terminate()

                    try:
                        self.process.wait(
                            timeout=1
                        )

                    except subprocess.TimeoutExpired:
                        self.process.kill()

                    self.process = None

    @staticmethod
    def _rms_db(samples):

        if samples.size == 0:
            return -90.0

        normalized = (
            samples / 32768.0
        )

        rms = np.sqrt(
            np.mean(
                np.square(
                    normalized
                )
            )
        )

        if rms <= 0.000001:
            return -90.0

        db = 20.0 * np.log10(
            rms
        )

        return max(
            -90.0,
            float(db)
        )
