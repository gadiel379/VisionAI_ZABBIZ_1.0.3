# -*- coding: utf-8 -*-

import os
import subprocess
import wave

import cv2


class Recorder:

    def __init__(
        self,
        sample_rate=48000,
        channels=2,
        sample_width=2,
        audio_sync_delay_seconds=None
    ):
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.sample_width = int(sample_width)

        if audio_sync_delay_seconds is None:

            audio_sync_delay_seconds = (
                os.environ.get(
                    "VISION_AI_AUDIO_SYNC_DELAY_SECONDS",
                    "0.500"
                )
            )

        try:

            self.audio_sync_delay_seconds = (
                float(
                    audio_sync_delay_seconds
                )
            )

        except (TypeError, ValueError):

            self.audio_sync_delay_seconds = 0.500

        self.audio_sync_delay_seconds = max(
            -2.0,
            min(
                2.0,
                self.audio_sync_delay_seconds
            )
        )

    def save_clip(
        self,
        frames,
        folder,
        fps=10,
        audio_chunks=None,
        target_duration=None
    ):
        frames = list(frames or [])
        audio_chunks = list(audio_chunks or [])

        print("\n===== RECORDER FFMPEG =====")
        print("Frames recibidos:", len(frames))
        print("Chunks de audio:", len(audio_chunks))
        print("FPS efectivo:", fps)
        print("Carpeta:", folder)

        if not frames:
            print("[RECORDER] Buffer de video vacío")
            return None

        os.makedirs(
            folder,
            exist_ok=True
        )

        temporary_audio = os.path.join(
            folder,
            "audio_temp.wav"
        )

        final_path = os.path.join(
            folder,
            "clip.mp4"
        )

        self._remove_file(final_path)
        self._remove_file(temporary_audio)

        effective_fps = self._validate_fps(fps)

        video_start_timestamp = float(
            frames[0][0]
        )

        audio_start_timestamp = (
            self._get_audio_start_timestamp(
                audio_chunks
            )
        )

        audio_offset_seconds = 0.0

        if audio_start_timestamp is not None:
            audio_offset_seconds = (
                audio_start_timestamp
                - video_start_timestamp
            )

        print(
            "Inicio video:",
            round(video_start_timestamp, 6)
        )

        print(
            "Inicio audio:",
            (
                round(audio_start_timestamp, 6)
                if audio_start_timestamp is not None
                else "N/A"
            )
        )

        print(
            "Desfase inicial A/V:",
            round(audio_offset_seconds, 4),
            "segundos"
        )

        corrected_audio_offset_seconds = (
            audio_offset_seconds
            + self.audio_sync_delay_seconds
        )

        print(
            "Corrección fija de lip sync:",
            round(
                self.audio_sync_delay_seconds,
                4
            ),
            "segundos"
        )

        print(
            "Desfase A/V aplicado:",
            round(
                corrected_audio_offset_seconds,
                4
            ),
            "segundos"
        )

        audio_saved = self._save_audio(
            audio_chunks,
            temporary_audio
        )

        success = self._encode_with_ffmpeg(
            frames=frames,
            fps=effective_fps,
            audio_path=(
                temporary_audio
                if audio_saved
                else None
            ),
            output_path=final_path,
            target_duration=target_duration,
            audio_offset_seconds=
                corrected_audio_offset_seconds
        )

        self._remove_file(
            temporary_audio
        )

        if not success:
            print(
                "[RECORDER] No se pudo crear clip.mp4"
            )
            return None

        print("Destino:", final_path)
        print(
            "Tamaño:",
            os.path.getsize(final_path),
            "bytes"
        )
        print("===========================\n")

        return final_path

    def _encode_with_ffmpeg(
        self,
        frames,
        fps,
        audio_path,
        output_path,
        target_duration,
        audio_offset_seconds
    ):
        first_frame = frames[0][1]

        if first_frame is None:
            return False

        height, width = first_frame.shape[:2]

        command = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",

            "-f",
            "rawvideo",

            "-pix_fmt",
            "bgr24",

            "-video_size",
            f"{width}x{height}",

            "-framerate",
            f"{fps:.6f}",

            "-i",
            "pipe:0"
        ]

        if audio_path is not None:

            command.extend([
                "-i",
                audio_path,

                "-map",
                "0:v:0",

                "-map",
                "1:a:0",

                "-c:v",
                "libx264",

                "-preset",
                "veryfast",

                "-tune",
                "zerolatency",

                "-crf",
                "22",

                "-pix_fmt",
                "yuv420p",

                "-c:a",
                "aac",

                "-b:a",
                "128k",

                "-af",
                self._build_audio_filter(
                    audio_offset_seconds
                )
            ])

        else:

            command.extend([
                "-map",
                "0:v:0",

                "-c:v",
                "libx264",

                "-preset",
                "veryfast",

                "-tune",
                "zerolatency",

                "-crf",
                "22",

                "-pix_fmt",
                "yuv420p",

                "-an"
            ])

        command.extend([
            "-movflags",
            "+faststart"
        ])

        if target_duration is not None:

            command.extend([
                "-t",
                f"{float(target_duration):.3f}"
            ])

        command.append(
            output_path
        )

        process = None

        try:

            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                bufsize=0
            )

            for _, frame in frames:

                if frame is None:
                    continue

                if (
                    frame.shape[1] != width
                    or frame.shape[0] != height
                ):
                    frame = cv2.resize(
                        frame,
                        (width, height)
                    )

                if not frame.flags[
                    "C_CONTIGUOUS"
                ]:
                    frame = frame.copy()

                try:
                    process.stdin.write(
                        frame.tobytes()
                    )

                except BrokenPipeError:
                    break

            process.stdin.close()

            stderr = process.stderr.read().decode(
                "utf-8",
                errors="replace"
            )

            return_code = process.wait()

            if return_code != 0:

                print(
                    "[RECORDER] Error FFmpeg:",
                    stderr
                )

                return False

        except FileNotFoundError:

            print(
                "[RECORDER] FFmpeg no está instalado"
            )

            return False

        except Exception as error:

            print(
                "[RECORDER] Error enviando frames:",
                error
            )

            if (
                process is not None
                and process.poll() is None
            ):
                process.kill()
                process.wait()

            return False

        return (
            os.path.exists(output_path)
            and os.path.getsize(output_path) > 0
        )

    def _save_audio(
        self,
        audio_chunks,
        path
    ):
        if not audio_chunks:

            print(
                "[RECORDER] Buffer de audio vacío"
            )

            return False

        raw_audio = b"".join(
            data
            for _, data in audio_chunks
            if data
        )

        if not raw_audio:
            return False

        with wave.open(path, "wb") as wav_file:

            wav_file.setnchannels(
                self.channels
            )

            wav_file.setsampwidth(
                self.sample_width
            )

            wav_file.setframerate(
                self.sample_rate
            )

            wav_file.writeframes(
                raw_audio
            )

        return (
            os.path.exists(path)
            and os.path.getsize(path) > 44
        )

    def _get_audio_start_timestamp(
        self,
        audio_chunks
    ):
        if not audio_chunks:
            return None

        first_timestamp, first_data = (
            audio_chunks[0]
        )

        try:
            first_timestamp = float(
                first_timestamp
            )

        except (TypeError, ValueError):
            return None

        if not first_data:
            return first_timestamp

        bytes_per_audio_frame = (
            self.channels
            * self.sample_width
        )

        if bytes_per_audio_frame <= 0:
            return first_timestamp

        audio_frames = (
            len(first_data)
            / bytes_per_audio_frame
        )

        chunk_duration = (
            audio_frames
            / self.sample_rate
        )

        return (
            first_timestamp
            - chunk_duration
        )

    def _build_audio_filter(
        self,
        audio_offset_seconds
    ):
        try:
            offset = float(
                audio_offset_seconds
            )

        except (TypeError, ValueError):
            offset = 0.0

        # El audio comienza antes que el video.
        # Se elimina el excedente inicial.
        if offset < -0.001:

            trim_seconds = abs(offset)

            return (
                f"atrim=start={trim_seconds:.6f},"
                "asetpts=PTS-STARTPTS,"
                "aresample=async=1:first_pts=0,"
                "apad"
            )

        # El audio comienza después que el video.
        # Se agrega silencio al inicio.
        if offset > 0.001:

            delay_ms = max(
                0,
                int(round(offset * 1000.0))
            )

            delays = "|".join(
                str(delay_ms)
                for _ in range(
                    self.channels
                )
            )

            return (
                f"adelay={delays},"
                "aresample=async=1:first_pts=0,"
                "apad"
            )

        return (
            "aresample=async=1:first_pts=0,"
            "apad"
        )

    @staticmethod
    def _validate_fps(fps):

        try:
            fps = float(fps)

        except (TypeError, ValueError):
            fps = 10.0

        return max(
            1.0,
            min(
                60.0,
                fps
            )
        )

    @staticmethod
    def _remove_file(path):

        try:

            if os.path.exists(path):
                os.remove(path)

        except OSError:
            pass
