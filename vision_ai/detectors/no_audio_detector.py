# -*- coding: utf-8 -*-

import time

from detectors.base_detector import BaseDetector
from events.event_types import EventTypes


class NoAudioDetector(BaseDetector):

    detector_type = EventTypes.NO_AUDIO

    def __init__(
        self,
        level_threshold_db=-55.0,
        confirmation_seconds=10.0
    ):
        self.level_threshold_db = float(
            level_threshold_db
        )

        self.confirmation_seconds = float(
            confirmation_seconds
        )

        self.silence_start_time = None

    def process(self, context):

        audio = getattr(
            context,
            "audio",
            None
        )

        if not isinstance(audio, dict):

            self.silence_start_time = None

            return self.result(
                alarm=False,
                confidence=0,
                details={
                    "reason": "audio_data_unavailable"
                }
            )

        try:

            left_db = float(
                audio.get(
                    "left_db",
                    -90.0
                )
            )

            right_db = float(
                audio.get(
                    "right_db",
                    -90.0
                )
            )

        except (TypeError, ValueError):

            self.silence_start_time = None

            return self.result(
                alarm=False,
                confidence=0,
                details={
                    "reason": "invalid_audio_data"
                }
            )

        highest_channel_db = max(
            left_db,
            right_db
        )

        no_audio = (
            highest_channel_db
            <= self.level_threshold_db
        )

        now = time.time()

        if no_audio:

            if self.silence_start_time is None:

                self.silence_start_time = now

            duration = (
                now
                - self.silence_start_time
            )

        else:

            self.silence_start_time = None
            duration = 0.0

        alarm = (
            no_audio
            and duration
            >= self.confirmation_seconds
        )

        silence_depth = (
            self.level_threshold_db
            - highest_channel_db
        )

        confidence = min(
            100.0,
            max(
                0.0,
                50.0
                + silence_depth * 2.0
            )
        )

        return self.result(
            alarm=alarm,
            confidence=confidence,
            details={
                "left_db": round(
                    left_db,
                    2
                ),
                "right_db": round(
                    right_db,
                    2
                ),
                "highest_channel_db": round(
                    highest_channel_db,
                    2
                ),
                "duration": round(
                    duration,
                    2
                ),
                "level_threshold_db":
                    self.level_threshold_db,
                "confirmation_seconds":
                    self.confirmation_seconds,
                "failure_started_timestamp":
                    self.silence_start_time
            }
        )
