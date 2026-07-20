# -*- coding: utf-8 -*-

import time
from collections import deque

import cv2
import numpy as np

from detectors.base_detector import BaseDetector
from events.event_types import EventTypes


class ArtifactDetector(BaseDetector):
    """Detecta digitalización con validación espacial y temporal ligera.

    Los argumentos del detector regional anterior se conservan en el
    constructor para mantener compatibilidad con MonitorEngine y con el
    archivo config/detectors.yaml existente. La medición temporal evita que
    cintillos y gráficos estáticos se confundan con macrobloques dañados, sin
    recuperar el análisis regional que retrasaba el video del dashboard.
    """

    detector_type = EventTypes.ARTIFACT

    def __init__(
        self,
        block_sizes=(8, 16),
        alignment_threshold=1.22,
        temporal_increase_threshold=0.22,
        minimum_boundary_strength=4.0,
        affected_regions_ratio=0.25,
        confirmation_seconds=3.0,
        recovery_seconds=2.0,
        baseline_seconds=4.0,
        analysis_width=320,
        analysis_height=180,
        grid_rows=4,
        grid_columns=4,
        macroblock_excess_threshold=3.0,
        macroblock_temporal_excess_threshold=2.0,
        macroblock_min_temporal_change=1.0,
        macroblock_max_temporal_change=45.0,
        macroblock_evidence_frames=4,
        macroblock_evidence_window_seconds=2.0,
        macroblock_hold_seconds=2.0,
    ):
        self.block_sizes = tuple(
            int(value)
            for value in block_sizes
            if int(value) > 1
        )

        if not self.block_sizes:
            self.block_sizes = (8, 16)

        # Se conservan para compatibilidad y trazabilidad del JSON.
        self.alignment_threshold = float(alignment_threshold)
        self.temporal_increase_threshold = float(
            temporal_increase_threshold
        )
        self.minimum_boundary_strength = float(
            minimum_boundary_strength
        )
        self.affected_regions_ratio = float(
            affected_regions_ratio
        )
        self.grid_rows = int(grid_rows)
        self.grid_columns = int(grid_columns)

        self.confirmation_seconds = float(
            confirmation_seconds
        )
        self.recovery_seconds = float(recovery_seconds)
        self.baseline_seconds = max(
            0.0,
            float(baseline_seconds),
        )

        self.analysis_width = int(analysis_width)
        self.analysis_height = int(analysis_height)

        self.macroblock_excess_threshold = float(
            macroblock_excess_threshold
        )
        self.macroblock_temporal_excess_threshold = float(
            macroblock_temporal_excess_threshold
        )
        self.macroblock_min_temporal_change = float(
            macroblock_min_temporal_change
        )
        self.macroblock_max_temporal_change = float(
            macroblock_max_temporal_change
        )
        self.macroblock_evidence_frames = max(
            1,
            int(macroblock_evidence_frames),
        )
        self.macroblock_evidence_window_seconds = max(
            0.1,
            float(macroblock_evidence_window_seconds),
        )
        self.macroblock_hold_seconds = max(
            0.0,
            float(macroblock_hold_seconds),
        )

        self._macroblock_indices = (
            self._build_macroblock_indices()
        )

        self.warmup_started_at = None
        self.previous_gray = None

        self.corruption_evidence_times = deque()
        self.last_corruption_evidence_time = None

        self.artifact_start_time = None
        self.recovery_start_time = None
        self.alarm_active = False

    def process(self, context):
        frame = context.frame

        if frame is None:
            self._reset_runtime()
            return self.result(
                alarm=False,
                confidence=0.0,
                details={
                    "reason": "frame_none",
                    "decision_model": (
                        "macroblock_temporal_validation_v5"
                    ),
                },
            )

        now = time.time()
        gray = self._prepare_frame(frame)
        metrics = self._global_macroblock_metrics(
            gray,
            self.previous_gray,
        )

        if self.warmup_started_at is None:
            self.warmup_started_at = now

        warmup_elapsed = now - self.warmup_started_at

        if warmup_elapsed < self.baseline_seconds:
            self.previous_gray = gray
            self.corruption_evidence_times.clear()
            self.last_corruption_evidence_time = None

            return self.result(
                alarm=False,
                confidence=0.0,
                details={
                    "reason": "warming_up",
                    "warmup_elapsed": round(
                        warmup_elapsed,
                        2,
                    ),
                    "warmup_seconds": self.baseline_seconds,
                    "decision_model": (
                        "macroblock_temporal_validation_v5"
                    ),
                    "analysis_mode": "global_single_pass",
                    "macroblock_boundary_excess": round(
                        metrics["boundary_excess"],
                        4,
                    ),
                    "global_temporal_change": round(
                        metrics["temporal_change"],
                        4,
                    ),
                    "macroblock_temporal_boundary_excess": round(
                        metrics["temporal_boundary_excess"],
                        4,
                    ),
                },
            )

        macroblock_candidate = (
            metrics["boundary_excess"]
            >= self.macroblock_excess_threshold
            and metrics["temporal_boundary_excess"]
            >= self.macroblock_temporal_excess_threshold
            and metrics["temporal_change"]
            >= self.macroblock_min_temporal_change
            and metrics["temporal_change"]
            <= self.macroblock_max_temporal_change
        )

        if macroblock_candidate:
            self.corruption_evidence_times.append(now)

        evidence_limit = (
            now
            - self.macroblock_evidence_window_seconds
        )

        while (
            self.corruption_evidence_times
            and self.corruption_evidence_times[0]
            < evidence_limit
        ):
            self.corruption_evidence_times.popleft()

        evidence_count = len(
            self.corruption_evidence_times
        )

        evidence_ready = (
            macroblock_candidate
            and evidence_count
            >= self.macroblock_evidence_frames
        )

        if evidence_ready:
            self.last_corruption_evidence_time = now

        artifact_detected = (
            self.last_corruption_evidence_time
            is not None
            and now - self.last_corruption_evidence_time
            <= self.macroblock_hold_seconds
        )

        artifact_duration = 0.0
        recovery_duration = 0.0

        if artifact_detected:
            self.recovery_start_time = None

            if self.artifact_start_time is None:
                self.artifact_start_time = now

            artifact_duration = (
                now - self.artifact_start_time
            )

            if (
                artifact_duration
                >= self.confirmation_seconds
            ):
                self.alarm_active = True

        elif self.alarm_active:
            if self.recovery_start_time is None:
                self.recovery_start_time = now

            recovery_duration = (
                now - self.recovery_start_time
            )

            if recovery_duration >= self.recovery_seconds:
                self.alarm_active = False
                self.artifact_start_time = None
                self.recovery_start_time = None
                self.corruption_evidence_times.clear()
                self.last_corruption_evidence_time = None

        else:
            self.artifact_start_time = None
            self.recovery_start_time = None

        self.previous_gray = gray

        confidence = self._confidence(
            metrics=metrics,
            evidence_count=evidence_count,
            artifact_detected=artifact_detected,
        )

        evidence_progress = min(
            evidence_count
            / self.macroblock_evidence_frames,
            1.0,
        )

        return self.result(
            alarm=self.alarm_active,
            confidence=confidence,
            details={
                "decision_model": (
                    "macroblock_temporal_validation_v5"
                ),
                "analysis_mode": "global_single_pass",
                "legacy_regional_analysis_enabled": False,
                "macroblock_candidate": bool(
                    macroblock_candidate
                ),
                "macroblock_detected": bool(
                    artifact_detected
                ),
                "macroblock_boundary_excess": round(
                    metrics["boundary_excess"],
                    4,
                ),
                "macroblock_boundary_excess_threshold": (
                    self.macroblock_excess_threshold
                ),
                "macroblock_temporal_boundary_excess": round(
                    metrics["temporal_boundary_excess"],
                    4,
                ),
                "macroblock_temporal_excess_threshold": (
                    self.macroblock_temporal_excess_threshold
                ),
                "macroblock_temporal_aligned_strength": round(
                    metrics["temporal_aligned_strength"],
                    4,
                ),
                "macroblock_temporal_neighbor_strength": round(
                    metrics["temporal_neighbor_strength"],
                    4,
                ),
                "macroblock_temporal_block_size": int(
                    metrics["temporal_block_size"]
                ),
                "static_graphic_rejected": bool(
                    metrics["boundary_excess"]
                    >= self.macroblock_excess_threshold
                    and metrics["temporal_boundary_excess"]
                    < self.macroblock_temporal_excess_threshold
                ),
                "macroblock_aligned_strength": round(
                    metrics["aligned_strength"],
                    4,
                ),
                "macroblock_neighbor_strength": round(
                    metrics["neighbor_strength"],
                    4,
                ),
                "macroblock_block_size": int(
                    metrics["block_size"]
                ),
                "global_temporal_change": round(
                    metrics["temporal_change"],
                    4,
                ),
                "macroblock_min_temporal_change": (
                    self.macroblock_min_temporal_change
                ),
                "macroblock_max_temporal_change": (
                    self.macroblock_max_temporal_change
                ),
                "macroblock_evidence_count": evidence_count,
                "macroblock_required_evidence_frames": (
                    self.macroblock_evidence_frames
                ),
                "macroblock_evidence_progress_percent": round(
                    evidence_progress * 100.0,
                    2,
                ),
                "macroblock_evidence_window_seconds": (
                    self.macroblock_evidence_window_seconds
                ),
                "macroblock_hold_seconds": (
                    self.macroblock_hold_seconds
                ),
                "duration": round(artifact_duration, 2),
                "recovery_duration": round(
                    recovery_duration,
                    2,
                ),
                "confirmation_seconds": (
                    self.confirmation_seconds
                ),
                "recovery_seconds": self.recovery_seconds,
                "block_sizes": list(self.block_sizes),
                "analysis_width": self.analysis_width,
                "analysis_height": self.analysis_height,
                "failure_started_timestamp": (
                    self.artifact_start_time
                ),
            },
        )

    def _prepare_frame(self, frame):
        resized = cv2.resize(
            frame,
            (
                self.analysis_width,
                self.analysis_height,
            ),
        )

        gray = cv2.cvtColor(
            resized,
            cv2.COLOR_BGR2GRAY,
        )

        return gray.astype(np.float32)

    def _build_macroblock_indices(self):
        indices = []

        vertical_limit = self.analysis_width - 1
        horizontal_limit = self.analysis_height - 1

        for block_size in self.block_sizes:
            aligned_vertical = np.array(
                [
                    index - 1
                    for index in range(
                        block_size,
                        self.analysis_width,
                        block_size,
                    )
                    if index - 1 < vertical_limit
                ],
                dtype=np.int32,
            )

            aligned_horizontal = np.array(
                [
                    index - 1
                    for index in range(
                        block_size,
                        self.analysis_height,
                        block_size,
                    )
                    if index - 1 < horizontal_limit
                ],
                dtype=np.int32,
            )

            if (
                aligned_vertical.size == 0
                or aligned_horizontal.size == 0
            ):
                continue

            neighbor_vertical = np.unique(
                np.concatenate(
                    (
                        np.clip(
                            aligned_vertical - 1,
                            0,
                            vertical_limit - 1,
                        ),
                        np.clip(
                            aligned_vertical + 1,
                            0,
                            vertical_limit - 1,
                        ),
                    )
                )
            )

            neighbor_horizontal = np.unique(
                np.concatenate(
                    (
                        np.clip(
                            aligned_horizontal - 1,
                            0,
                            horizontal_limit - 1,
                        ),
                        np.clip(
                            aligned_horizontal + 1,
                            0,
                            horizontal_limit - 1,
                        ),
                    )
                )
            )

            indices.append({
                "block_size": block_size,
                "aligned_vertical": aligned_vertical,
                "aligned_horizontal": aligned_horizontal,
                "neighbor_vertical": neighbor_vertical,
                "neighbor_horizontal": neighbor_horizontal,
            })

        return indices

    def _global_macroblock_metrics(
        self,
        gray,
        previous_gray,
    ):
        best = {
            "boundary_excess": 0.0,
            "aligned_strength": 0.0,
            "neighbor_strength": 0.0,
            "temporal_change": 0.0,
            "block_size": 0,
            "temporal_boundary_excess": 0.0,
            "temporal_aligned_strength": 0.0,
            "temporal_neighbor_strength": 0.0,
            "temporal_block_size": 0,
        }

        vertical = np.abs(
            gray[:, 1:] - gray[:, :-1]
        )
        horizontal = np.abs(
            gray[1:, :] - gray[:-1, :]
        )

        for item in self._macroblock_indices:
            aligned_strength = (
                float(
                    np.mean(
                        vertical[
                            :,
                            item["aligned_vertical"],
                        ]
                    )
                )
                + float(
                    np.mean(
                        horizontal[
                            item["aligned_horizontal"],
                            :,
                        ]
                    )
                )
            ) / 2.0

            neighbor_strength = (
                float(
                    np.mean(
                        vertical[
                            :,
                            item["neighbor_vertical"],
                        ]
                    )
                )
                + float(
                    np.mean(
                        horizontal[
                            item["neighbor_horizontal"],
                            :,
                        ]
                    )
                )
            ) / 2.0

            boundary_excess = max(
                0.0,
                aligned_strength - neighbor_strength,
            )

            if boundary_excess > best["boundary_excess"]:
                best.update({
                    "boundary_excess": boundary_excess,
                    "aligned_strength": aligned_strength,
                    "neighbor_strength": neighbor_strength,
                    "block_size": item["block_size"],
                })

        if previous_gray is not None:
            temporal_difference = np.abs(
                gray - previous_gray
            )
            best["temporal_change"] = float(
                np.mean(temporal_difference)
            )

            temporal_vertical = np.abs(
                temporal_difference[:, 1:]
                - temporal_difference[:, :-1]
            )
            temporal_horizontal = np.abs(
                temporal_difference[1:, :]
                - temporal_difference[:-1, :]
            )

            for item in self._macroblock_indices:
                temporal_aligned_strength = (
                    float(
                        np.mean(
                            temporal_vertical[
                                :,
                                item["aligned_vertical"],
                            ]
                        )
                    )
                    + float(
                        np.mean(
                            temporal_horizontal[
                                item["aligned_horizontal"],
                                :,
                            ]
                        )
                    )
                ) / 2.0

                temporal_neighbor_strength = (
                    float(
                        np.mean(
                            temporal_vertical[
                                :,
                                item["neighbor_vertical"],
                            ]
                        )
                    )
                    + float(
                        np.mean(
                            temporal_horizontal[
                                item["neighbor_horizontal"],
                                :,
                            ]
                        )
                    )
                ) / 2.0

                temporal_boundary_excess = max(
                    0.0,
                    temporal_aligned_strength
                    - temporal_neighbor_strength,
                )

                if (
                    temporal_boundary_excess
                    > best["temporal_boundary_excess"]
                ):
                    best.update({
                        "temporal_boundary_excess": (
                            temporal_boundary_excess
                        ),
                        "temporal_aligned_strength": (
                            temporal_aligned_strength
                        ),
                        "temporal_neighbor_strength": (
                            temporal_neighbor_strength
                        ),
                        "temporal_block_size": item[
                            "block_size"
                        ],
                    })

        return best

    def _confidence(
        self,
        metrics,
        evidence_count,
        artifact_detected,
    ):
        boundary_score = min(
            35.0,
            max(
                0.0,
                metrics["boundary_excess"]
                / max(
                    self.macroblock_excess_threshold,
                    0.001,
                )
                * 35.0,
            ),
        )

        temporal_boundary_score = min(
            30.0,
            max(
                0.0,
                metrics["temporal_boundary_excess"]
                / max(
                    self.macroblock_temporal_excess_threshold,
                    0.001,
                )
                * 30.0,
            ),
        )

        evidence_score = min(
            evidence_count
            / self.macroblock_evidence_frames,
            1.0,
        ) * 20.0

        hold_score = 15.0 if artifact_detected else 0.0

        return min(
            100.0,
            boundary_score
            + temporal_boundary_score
            + evidence_score
            + hold_score,
        )

    def _reset_runtime(self):
        self.warmup_started_at = None
        self.previous_gray = None
        self.corruption_evidence_times.clear()
        self.last_corruption_evidence_time = None
        self.artifact_start_time = None
        self.recovery_start_time = None
        self.alarm_active = False
