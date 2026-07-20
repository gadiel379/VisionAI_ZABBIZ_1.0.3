# -*- coding: utf-8 -*-

import time

import cv2
import numpy as np

from detectors.base_detector import BaseDetector
from events.event_types import EventTypes


class BlackDetector(BaseDetector):

    detector_type = EventTypes.BLACK

    def __init__(
        self,
        luminance_threshold=12,
        black_ratio_threshold=98.0,
        confirmation_seconds=5.0,
        graphic_luminance_threshold=30,
        minimum_graphic_ratio=0.20
    ):

        self.luminance_threshold = float(
            luminance_threshold
        )

        self.black_ratio_threshold = float(
            black_ratio_threshold
        )

        self.confirmation_seconds = float(
            confirmation_seconds
        )

        self.graphic_luminance_threshold = float(
            graphic_luminance_threshold
        )

        self.minimum_graphic_ratio = float(
            minimum_graphic_ratio
        )

        self.black_start_time = None

    def process(self, context):

        frame = context.frame

        if frame is None:

            self.black_start_time = None

            return self.result(
                alarm=False,
                confidence=0,
                details={
                    "reason": "frame_none"
                }
            )

        gray = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2GRAY
        )

        mean_luminance = float(
            np.mean(gray)
        )

        black_pixels = np.count_nonzero(
            gray
            <= self.luminance_threshold
        )

        black_ratio = (
            black_pixels
            / gray.size
        ) * 100.0

        dark_background = (
            black_ratio
            >= self.black_ratio_threshold
        )

        graphic_pixels = np.count_nonzero(
            gray
            > self.graphic_luminance_threshold
        )

        graphic_ratio = (
            graphic_pixels
            / gray.size
        ) * 100.0

        has_significant_graphics = (
            graphic_ratio
            >= self.minimum_graphic_ratio
        )

        # Solo se considera negro real cuando predomina el negro y no
        # existe contenido visual significativo. Si quedan logotipos,
        # textos o gráficos, FreezeDetector decide temporalmente si
        # están activos o congelados.
        is_pure_black = (
            dark_background
            and not has_significant_graphics
        )

        if is_pure_black:
            classification = "pure_black"
        elif dark_background:
            classification = "black_with_graphics"
        else:
            classification = "not_black"

        now = time.time()

        if is_pure_black:

            if self.black_start_time is None:

                self.black_start_time = now

            duration = (
                now
                - self.black_start_time
            )

        else:

            self.black_start_time = None
            duration = 0.0

        alarm = (
            is_pure_black
            and duration
            >= self.confirmation_seconds
        )

        return self.result(
            alarm=alarm,
            confidence=min(
                black_ratio,
                100.0
            ),
            details={
                "mean_luminance": round(
                    mean_luminance,
                    2
                ),
                "black_ratio": round(
                    black_ratio,
                    2
                ),
                "graphic_ratio": round(
                    graphic_ratio,
                    4
                ),
                "dark_background":
                    dark_background,
                "has_significant_graphics":
                    has_significant_graphics,
                "classification":
                    classification,
                "duration": round(
                    duration,
                    2
                ),
                "luminance_threshold":
                    self.luminance_threshold,
                "black_ratio_threshold":
                    self.black_ratio_threshold,
                "confirmation_seconds":
                    self.confirmation_seconds,
                "graphic_luminance_threshold":
                    self.graphic_luminance_threshold,
                "minimum_graphic_ratio":
                    self.minimum_graphic_ratio,
                "failure_started_timestamp":
                    self.black_start_time
            }
        )
