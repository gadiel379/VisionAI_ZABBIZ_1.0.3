from collections import deque
import threading
import time


class VideoBuffer:

    def __init__(self, seconds, fps):

        self.seconds = float(seconds)
        self.configured_fps = float(fps)

        # Límite de seguridad para memoria. La retención efectiva se
        # controla por timestamp, no por el FPS solicitado a V4L2.
        # Algunas capturadoras ignoran CAP_PROP_FPS y entregan más
        # cuadros que el valor configurado.
        maximum_expected_fps = max(
            30.0,
            self.configured_fps
        )

        self.max_frames = int(
            self.seconds
            * maximum_expected_fps
            * 1.25
        ) + 10

        self.frames = deque(
            maxlen=self.max_frames
        )

        self.lock = threading.Lock()

    def add(self, frame):

        timestamp = time.time()
        oldest_allowed = (
            timestamp
            - self.seconds
        )

        with self.lock:

            self.frames.append(
                (
                    timestamp,
                    frame.copy()
                )
            )

            while (
                self.frames
                and self.frames[0][0]
                < oldest_allowed
            ):

                self.frames.popleft()

    def get_frames(
        self,
        start_time=None,
        end_time=None
    ):

        with self.lock:
            frames = list(self.frames)

        if (
            start_time is None
            and end_time is None
        ):
            return frames

        selected = []

        for timestamp, frame in frames:

            if (
                start_time is not None
                and timestamp < start_time
            ):
                continue

            if (
                end_time is not None
                and timestamp > end_time
            ):
                continue

            selected.append(
                (
                    timestamp,
                    frame
                )
            )

        return selected

    def clear(self):

        with self.lock:
            self.frames.clear()

    def __len__(self):

        with self.lock:
            return len(self.frames)
