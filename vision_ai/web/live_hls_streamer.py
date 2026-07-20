# -*- coding: utf-8 -*-

import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import cv2


class LiveHlsStreamer:

    def __init__(
        self,
        audio_buffer,
        output_directory,
        width=640,
        height=360,
        output_width=480,
        output_height=270,
        fps=15.0,
        sample_rate=48000,
        channels=2,
        video_delay_seconds=0.8
    ):

        self.audio_buffer = audio_buffer
        self.output_directory = Path(
            output_directory
        )

        self.width = int(width)
        self.height = int(height)
        self.output_width = int(output_width)
        self.output_height = int(output_height)
        self.fps = max(
            1.0,
            float(fps)
        )

        self.sample_rate = int(
            sample_rate
        )

        self.channels = int(channels)

        # La instalación validada utiliza un ajuste de 0.8 segundos.
        # Se retrasa solamente el
        # video del HLS para conservar el lip-sync sin tocar evidencias,
        # OCR, detectores ni los datos originales de la capturadora.
        self.video_delay_seconds = max(
            0.0,
            min(5.0, float(video_delay_seconds))
        )

        self.frame_lock = threading.Lock()
        self.latest_frame = None

        self.running = False
        self.process = None
        self.video_fd = None
        self.audio_fd = None
        self.threads = []

        self.pipe_directory = None
        self.video_pipe = None
        self.audio_pipe = None

    def update_frame(self, frame):

        if frame is None:
            return

        if (
            frame.shape[1] != self.width
            or frame.shape[0] != self.height
        ):

            frame = cv2.resize(
                frame,
                (
                    self.width,
                    self.height
                )
            )

        with self.frame_lock:
            self.latest_frame = frame.copy()

    def start(self):

        if self.running:
            return

        self.running = True

        self.output_directory.mkdir(
            parents=True,
            exist_ok=True
        )

        self._clean_output()

        self.pipe_directory = Path(
            tempfile.mkdtemp(
                prefix="vision_ai_live_"
            )
        )

        self.video_pipe = (
            self.pipe_directory
            / "video.raw"
        )

        self.audio_pipe = (
            self.pipe_directory
            / "audio.raw"
        )

        os.mkfifo(self.video_pipe)
        os.mkfifo(self.audio_pipe)

        playlist = (
            self.output_directory
            / "stream.m3u8"
        )

        segment_pattern = str(
            self.output_directory
            / "live_%06d.ts"
        )

        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-thread_queue_size",
            "64",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-video_size",
            f"{self.width}x{self.height}",
            "-framerate",
            f"{self.fps:.6f}",
            "-i",
            str(self.video_pipe),
            "-thread_queue_size",
            "512",
            "-f",
            "s16le",
            "-ar",
            str(self.sample_rate),
            "-ac",
            str(self.channels),
            "-i",
            str(self.audio_pipe),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-vf",
            (
                f"scale={self.output_width}:"
                f"{self.output_height}:"
                "flags=fast_bilinear,"
                "tpad=start_mode=clone:"
                f"start_duration={self.video_delay_seconds:.3f}"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-threads",
            "1",
            "-pix_fmt",
            "yuv420p",
            "-r",
            f"{self.fps:.6f}",
            "-g",
            str(max(1, int(round(self.fps)))),
            "-keyint_min",
            str(max(1, int(round(self.fps)))),
            "-sc_threshold",
            "0",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-ar",
            str(self.sample_rate),
            "-af",
            "aresample=async=1:first_pts=0",
            "-f",
            "hls",
            "-hls_time",
            "1",
            "-hls_list_size",
            "4",
            "-hls_delete_threshold",
            "2",
            "-hls_flags",
            "delete_segments+independent_segments+program_date_time+temp_file",
            "-hls_segment_filename",
            segment_pattern,
            str(playlist)
        ]

        try:

            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True
            )

            # O_RDWR evita el bloqueo de apertura de FIFO mientras
            # FFmpeg abre sus dos entradas.
            self.video_fd = os.open(
                self.video_pipe,
                os.O_RDWR
            )

            self.audio_fd = os.open(
                self.audio_pipe,
                os.O_RDWR
            )

        except (OSError, FileNotFoundError) as error:

            print(
                "[LIVE HLS] No se pudo iniciar: "
                f"{error}"
            )

            self.stop()
            return

        self.threads = [
            threading.Thread(
                target=self._video_loop,
                daemon=True
            ),
            threading.Thread(
                target=self._audio_loop,
                daemon=True
            ),
            threading.Thread(
                target=self._monitor_loop,
                daemon=True
            )
        ]

        for thread in self.threads:
            thread.start()

        print(
            "[LIVE HLS] Transmisión A/V iniciada "
            f"entrada={self.width}x{self.height} "
            f"salida={self.output_width}x"
            f"{self.output_height} "
            f"{self.fps:.1f} FPS "
            "ajuste_lipsync_video="
            f"{self.video_delay_seconds:.3f}s"
        )

    @staticmethod
    def _write_all(file_descriptor, data):

        view = memoryview(data)
        written = 0

        while written < len(view):

            count = os.write(
                file_descriptor,
                view[written:]
            )

            if count <= 0:
                raise BrokenPipeError(
                    "FIFO cerrada"
                )

            written += count

    def _video_loop(self):

        interval = 1.0 / self.fps
        deadline = time.monotonic()

        while self.running:

            with self.frame_lock:
                frame = (
                    self.latest_frame.copy()
                    if self.latest_frame
                    is not None
                    else None
                )

            if frame is None:
                time.sleep(0.02)
                deadline = time.monotonic()
                continue

            try:
                self._write_all(
                    self.video_fd,
                    frame.tobytes()
                )
            except (OSError, BrokenPipeError):
                break

            deadline += interval
            wait_seconds = (
                deadline
                - time.monotonic()
            )

            if wait_seconds > 0:
                time.sleep(wait_seconds)
            else:
                deadline = time.monotonic()

    def _audio_loop(self):

        last_timestamp = time.time()

        while self.running:

            if self.audio_buffer is None:
                time.sleep(0.05)
                continue

            chunks = self.audio_buffer.get_chunks(
                start_time=(
                    last_timestamp
                    + 0.000001
                )
            )

            if not chunks:
                time.sleep(0.01)
                continue

            for timestamp, data in chunks:

                if not self.running:
                    break

                try:
                    self._write_all(
                        self.audio_fd,
                        data
                    )
                except (
                    OSError,
                    BrokenPipeError
                ):
                    return

                last_timestamp = max(
                    last_timestamp,
                    float(timestamp)
                )

    def _monitor_loop(self):

        while self.running:

            if (
                self.process is not None
                and self.process.poll()
                is not None
            ):

                print(
                    "[LIVE HLS] FFmpeg terminó "
                    f"con código {self.process.returncode}"
                )
                self.running = False
                break

            time.sleep(1.0)

    def _clean_output(self):

        for pattern in (
            "live_*.ts",
            "live_*.ts.tmp",
            "stream.m3u8",
            "stream.m3u8.tmp"
        ):

            for path in (
                self.output_directory.glob(
                    pattern
                )
            ):

                try:
                    path.unlink()
                except OSError:
                    pass

    def stop(self):

        self.running = False

        for file_descriptor_name in (
            "video_fd",
            "audio_fd"
        ):

            file_descriptor = getattr(
                self,
                file_descriptor_name
            )

            if file_descriptor is not None:

                try:
                    os.close(file_descriptor)
                except OSError:
                    pass

                setattr(
                    self,
                    file_descriptor_name,
                    None
                )

        if (
            self.process is not None
            and self.process.poll() is None
        ):

            self.process.terminate()

            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()

        self.process = None

        if self.pipe_directory is not None:
            shutil.rmtree(
                self.pipe_directory,
                ignore_errors=True
            )

        self.pipe_directory = None
