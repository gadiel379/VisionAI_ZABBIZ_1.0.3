# -*- coding: utf-8 -*-

import threading
from collections import deque


class AudioBuffer:

    def __init__(
        self,
        seconds=40,
        sample_rate=48000,
        channels=2,
        sample_width=2,
        chunk_frames=2048
    ):

        self.seconds = float(seconds)
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.sample_width = int(sample_width)
        self.chunk_frames = int(chunk_frames)

        chunks_per_second = (
            self.sample_rate
            / self.chunk_frames
        )

        max_chunks = int(
            self.seconds
            * chunks_per_second
        ) + 10

        self.chunks = deque(
            maxlen=max_chunks
        )

        self.lock = threading.Lock()

    def add(self, timestamp, data):

        if not data:
            return

        with self.lock:

            self.chunks.append(
                (
                    float(timestamp),
                    bytes(data)
                )
            )

    def get_chunks(
        self,
        start_time=None,
        end_time=None
    ):

        with self.lock:
            chunks = list(self.chunks)

        if (
            start_time is None
            and end_time is None
        ):
            return chunks

        selected = []

        for timestamp, data in chunks:

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
                    data
                )
            )

        return selected

    def clear(self):

        with self.lock:
            self.chunks.clear()

    def __len__(self):

        with self.lock:
            return len(self.chunks)
