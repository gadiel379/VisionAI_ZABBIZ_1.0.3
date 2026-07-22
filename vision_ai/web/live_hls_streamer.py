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
        self.lifecycle_lock = threading.RLock()
        self.latest_frame = None

        self.running = False
        self.process = None
        self.video_fd = None
        self.audio_fd = None
        self.threads = []

        self.pipe_directory = None
        self.video_pipe = None
        self.audio_pipe = None
        self.generation = 0
        self.first_start = True
        self.session_stop_event = None

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

    def clear_frame(self):

        with self.frame_lock:
            self.latest_frame = None

    def has_frame(self):

        with self.frame_lock:
            return self.latest_frame is not None

    def start(self):

        with self.lifecycle_lock:
            self._start_locked()

    def _start_locked(self):

        if self.running:
            return

        self.running = True

        self.output_directory.mkdir(
            parents=True,
            exist_ok=True
        )

        if self.first_start:
            self._clean_output()
            self.first_start = False

        self.generation += 1
        generation = self.generation
        session_stop_event = threading.Event()
        self.session_stop_event = session_stop_event

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
            / f"live_g{generation}_%06d.ts"
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
            "-hls_start_number_source",
            "epoch",
            "-hls_delete_threshold",
            "2",
            "-hls_flags",
            (
                "delete_segments+independent_segments+program_date_time+"
                "temp_file+discont_start"
            ),
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

            # El cursor se fija cuando las dos entradas de la nueva sesion
            # ya estan abiertas. De esta forma nunca se vuelca en FFmpeg el
            # audio acumulado mientras se cerraba la generacion anterior.
            audio_start_timestamp = time.time()

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
                args=(session_stop_event, self.video_fd),
                daemon=True
            ),
            threading.Thread(
                target=self._audio_loop,
                args=(
                    session_stop_event,
                    self.audio_fd,
                    audio_start_timestamp,
                ),
                daemon=True
            ),
            threading.Thread(
                target=self._monitor_loop,
                args=(session_stop_event, self.process, generation),
                daemon=True
            )
        ]

        for thread in self.threads:
            thread.start()

        threading.Thread(
            target=self._cleanup_previous_generations,
            args=(generation,),
            daemon=True,
        ).start()

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
    def _write_all(file_descriptor, data, session_stop_event=None):

        view = memoryview(data)
        written = 0

        while written < len(view):

            if (
                session_stop_event is not None
                and session_stop_event.is_set()
            ):
                raise BrokenPipeError("Sesion HLS cerrada")

            count = os.write(
                file_descriptor,
                view[written:]
            )

            if count <= 0:
                raise BrokenPipeError(
                    "FIFO cerrada"
                )

            written += count

    def _video_loop(self, session_stop_event, video_fd):

        interval = 1.0 / self.fps
        deadline = time.monotonic()

        while not session_stop_event.is_set():

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
                    video_fd,
                    frame.tobytes(),
                    session_stop_event,
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

    def _audio_loop(
        self,
        session_stop_event,
        audio_fd,
        audio_start_timestamp,
    ):

        last_timestamp = float(audio_start_timestamp)

        while not session_stop_event.is_set():

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

                if session_stop_event.is_set():
                    break

                try:
                    self._write_all(
                        audio_fd,
                        data,
                        session_stop_event,
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

    def _monitor_loop(self, session_stop_event, process, generation):

        while not session_stop_event.is_set():

            if (
                process is not None
                and process.poll()
                is not None
            ):

                print(
                    "[LIVE HLS] FFmpeg terminó "
                    f"con código {process.returncode} "
                    f"en generacion {generation}"
                )
                session_stop_event.set()
                with self.lifecycle_lock:
                    if self.process is process:
                        self.running = False
                break

            time.sleep(1.0)

    def _clean_output(self):

        for pattern in (
            "live_*.ts",
            "live_*.ts.tmp",
            "live_g*.ts",
            "live_g*.ts.tmp",
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

    def _cleanup_previous_generations(self, generation):

        playlist = self.output_directory / "stream.m3u8"
        marker = f"live_g{generation}_"
        deadline = time.monotonic() + 5.0

        while self.running and time.monotonic() < deadline:
            try:
                if marker in playlist.read_text(encoding="utf-8"):
                    break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            return

        for path in self.output_directory.glob("live_g*.ts*"):
            if marker in path.name:
                continue
            try:
                path.unlink()
            except OSError:
                pass

    def restart(self):

        with self.lifecycle_lock:
            self._stop_locked()
            self._start_locked()

        print(
            "[LIVE HLS] Nueva linea de tiempo A/V iniciada "
            "despues de reconexion USB"
        )

    def stop(self):

        with self.lifecycle_lock:
            self._stop_locked()

    def _stop_locked(self):

        self.running = False

        session_stop_event = self.session_stop_event
        self.session_stop_event = None
        if session_stop_event is not None:
            session_stop_event.set()

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

        old_threads = self.threads
        self.threads = []

        current_thread = threading.current_thread()
        for thread in old_threads:
            if thread is current_thread:
                continue
            if thread.is_alive():
                thread.join(timeout=2)

        if self.pipe_directory is not None:
            shutil.rmtree(
                self.pipe_directory,
                ignore_errors=True
            )

        self.pipe_directory = None
