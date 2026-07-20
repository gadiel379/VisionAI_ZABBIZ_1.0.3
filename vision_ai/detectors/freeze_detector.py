# -*- coding: utf-8 -*-

import time

import cv2
import numpy as np

from detectors.base_detector import BaseDetector
from events.event_types import EventTypes


class FreezeDetector(BaseDetector):

    detector_type = EventTypes.FREEZE

    def __init__(
        self,
        difference_threshold=0.30,
        static_regions_ratio=0.90,
        recovery_difference_threshold=2.0,
        recovery_changed_regions_ratio=0.30,
        confirmation_seconds=10.0,
        recovery_seconds=2.0,
        analysis_width=320,
        analysis_height=180,
        grid_rows=3,
        grid_columns=3
    ):
        self.difference_threshold = float(
            difference_threshold
        )

        self.static_regions_ratio = float(
            static_regions_ratio
        )

        self.recovery_difference_threshold = float(
            recovery_difference_threshold
        )

        self.recovery_changed_regions_ratio = float(
            recovery_changed_regions_ratio
        )

        self.confirmation_seconds = float(
            confirmation_seconds
        )

        self.recovery_seconds = float(
            recovery_seconds
        )

        self.analysis_width = int(
            analysis_width
        )

        self.analysis_height = int(
            analysis_height
        )

        self.grid_rows = int(
            grid_rows
        )

        self.grid_columns = int(
            grid_columns
        )

        self.previous_frame = None
        self.freeze_reference_frame = None

        self.freeze_start_time = None
        self.recovery_start_time = None

        self.alarm_active = False

    def process(self, context):

        frame = context.frame

        if frame is None:

            self._reset()

            return self.result(
                alarm=False,
                confidence=0,
                details={
                    "reason": "frame_none"
                }
            )

        gray = self._prepare_frame(
            frame
        )

        if self.previous_frame is None:

            self.previous_frame = gray.copy()

            return self.result(
                alarm=False,
                confidence=0,
                details={
                    "reason": "initial_frame"
                }
            )

        consecutive_differences = (
            self._calculate_region_differences(
                self.previous_frame,
                gray
            )
        )

        self.previous_frame = gray.copy()

        static_regions = sum(
            difference
            <= self.difference_threshold
            for difference
            in consecutive_differences
        )

        total_regions = len(
            consecutive_differences
        )

        static_ratio = (
            static_regions / total_regions
            if total_regions
            else 0.0
        )

        is_static = (
            static_ratio
            >= self.static_regions_ratio
        )

        now = time.time()

        freeze_duration = 0.0
        recovery_duration = 0.0
        changed_regions = 0
        changed_ratio = 0.0
        recovery_differences = []

        if not self.alarm_active:

            self.recovery_start_time = None

            if is_static:

                if self.freeze_start_time is None:

                    self.freeze_start_time = now

                    self.freeze_reference_frame = (
                        gray.copy()
                    )

                freeze_duration = (
                    now
                    - self.freeze_start_time
                )

                if (
                    freeze_duration
                    >= self.confirmation_seconds
                ):

                    self.alarm_active = True

            else:

                self.freeze_start_time = None
                self.freeze_reference_frame = None

        else:

            freeze_duration = (
                now
                - self.freeze_start_time
                if self.freeze_start_time
                else 0.0
            )

            if self.freeze_reference_frame is not None:

                recovery_differences = (
                    self._calculate_region_differences(
                        self.freeze_reference_frame,
                        gray
                    )
                )

                changed_regions = sum(
                    difference
                    >= self.recovery_difference_threshold
                    for difference
                    in recovery_differences
                )

                changed_ratio = (
                    changed_regions / total_regions
                    if total_regions
                    else 0.0
                )

            movement_recovered = (
                changed_ratio
                >= self.recovery_changed_regions_ratio
            )

            if movement_recovered:

                if self.recovery_start_time is None:

                    self.recovery_start_time = now

                recovery_duration = (
                    now
                    - self.recovery_start_time
                )

                if (
                    recovery_duration
                    >= self.recovery_seconds
                ):

                    self.alarm_active = False
                    self.freeze_start_time = None
                    self.recovery_start_time = None
                    self.freeze_reference_frame = None

            else:

                self.recovery_start_time = None

        confidence = min(
            100.0,
            static_ratio * 100.0
        )

        return self.result(
            alarm=self.alarm_active,
            confidence=confidence,
            details={
                "mean_difference": round(
                    float(
                        np.mean(
                            consecutive_differences
                        )
                    ),
                    4
                ),
                "difference_threshold":
                    self.difference_threshold,
                "static_regions":
                    static_regions,
                "total_regions":
                    total_regions,
                "static_ratio_percent": round(
                    static_ratio * 100.0,
                    2
                ),
                "required_static_ratio_percent": round(
                    self.static_regions_ratio
                    * 100.0,
                    2
                ),
                "changed_regions":
                    changed_regions,
                "changed_ratio_percent": round(
                    changed_ratio * 100.0,
                    2
                ),
                "required_changed_ratio_percent": round(
                    self.recovery_changed_regions_ratio
                    * 100.0,
                    2
                ),
                "recovery_difference_threshold":
                    self.recovery_difference_threshold,
                "duration": round(
                    freeze_duration,
                    2
                ),
                "recovery_duration": round(
                    recovery_duration,
                    2
                ),
                "confirmation_seconds":
                    self.confirmation_seconds,
                "recovery_seconds":
                    self.recovery_seconds,
                "grid_rows":
                    self.grid_rows,
                "grid_columns":
                    self.grid_columns,
                "region_differences": [
                    round(value, 4)
                    for value
                    in consecutive_differences
                ],
                "recovery_region_differences": [
                    round(value, 4)
                    for value
                    in recovery_differences
                ],
                "failure_started_timestamp":
                    self.freeze_start_time
            }
        )

    def _prepare_frame(self, frame):

        resized = cv2.resize(
            frame,
            (
                self.analysis_width,
                self.analysis_height
            )
        )

        gray = cv2.cvtColor(
            resized,
            cv2.COLOR_BGR2GRAY
        )

        return cv2.GaussianBlur(
            gray,
            (5, 5),
            0
        )

    def suppress_for_pure_black(self):
        """
        Reinicia el estado de congelamiento cuando BlackDetector ha
        clasificado el frame como negro puro. Evita que una misma
        falla genere primero BLACK y después FREEZE.
        """

        self._reset()

        return self.result(
            alarm=False,
            confidence=0,
            details={
                "reason": "suppressed_by_pure_black",
                "duration": 0.0,
                "failure_started_timestamp": None
            }
        )

    def _calculate_region_differences(
        self,
        previous_frame,
        current_frame
    ):

        region_height = (
            self.analysis_height
            // self.grid_rows
        )

        region_width = (
            self.analysis_width
            // self.grid_columns
        )

        differences = []

        for row in range(
            self.grid_rows
        ):

            for column in range(
                self.grid_columns
            ):

                y1 = row * region_height
                x1 = column * region_width

                y2 = (
                    self.analysis_height
                    if row
                    == self.grid_rows - 1
                    else (
                        row + 1
                    ) * region_height
                )

                x2 = (
                    self.analysis_width
                    if column
                    == self.grid_columns - 1
                    else (
                        column + 1
                    ) * region_width
                )

                previous_region = (
                    previous_frame[
                        y1:y2,
                        x1:x2
                    ]
                )

                current_region = (
                    current_frame[
                        y1:y2,
                        x1:x2
                    ]
                )

                difference = cv2.absdiff(
                    previous_region,
                    current_region
                )

                differences.append(
                    float(
                        np.mean(
                            difference
                        )
                    )
                )

        return differences

    def _reset(self):

        self.previous_frame = None
        self.freeze_reference_frame = None
        self.freeze_start_time = None
        self.recovery_start_time = None
        self.alarm_active = False
