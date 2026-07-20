# -*- coding: utf-8 -*-

import time

from detectors.black_detector import (
    BlackDetector
)

from detectors.no_audio_detector import (
    NoAudioDetector
)

from detectors.freeze_detector import (
    FreezeDetector
)

from detectors.artifact_detector import (
    ArtifactDetector
)

from detectors.channel_id_detector import (
    ChannelIdDetector
)

from utils.detector_config import (
    DetectorConfig
)


class MonitorEngine:

    def __init__(
        self,
        channel_id_event_callback=None,
        capture_id="capture_1",
    ):

        self.config = DetectorConfig()
        self.detectors = []
        self.channel_id_event_callback = (
            channel_id_event_callback
        )
        self.capture_id = str(capture_id).strip() or "capture_1"
        self.audio_confirmation_seconds = 10.0
        self.freeze_confirmation_seconds = 10.0
        self.freeze_confirmation_tolerance = 0.25
        self.freeze_candidate_grace_seconds = 0.75
        self._recent_freeze_candidate = None
        self._recent_freeze_candidate_seen = None
        self._combined_freeze_active = False
        self._post_freeze_silence_start = None

        self._load_detectors()

    def _load_detectors(self):

        if self.config.is_enabled(
            "black",
            default=True
        ):
            config = self.config.get_detector(
                "black"
            )

            self.detectors.append(
                BlackDetector(
                    luminance_threshold=
                        config.get(
                            "luminance_threshold",
                            12
                        ),
                    black_ratio_threshold=
                        config.get(
                            "black_ratio_threshold",
                            98.0
                        ),
                    confirmation_seconds=
                        config.get(
                            "confirmation_seconds",
                            5.0
                        ),
                    graphic_luminance_threshold=
                        config.get(
                            "graphic_luminance_threshold",
                            30
                        ),
                    minimum_graphic_ratio=
                        config.get(
                            "minimum_graphic_ratio",
                            0.20
                        )
                )
            )

        if self.config.is_enabled(
            "audio",
            default=False
        ):
            config = self.config.get_detector(
                "audio"
            )

            self.audio_confirmation_seconds = float(
                config.get(
                    "confirmation_seconds",
                    10.0
                )
            )

            self.detectors.append(
                NoAudioDetector(
                    level_threshold_db=
                        config.get(
                            "level_threshold_db",
                            -55.0
                        ),
                    confirmation_seconds=
                        self.audio_confirmation_seconds
                )
            )

        if self.config.is_enabled(
            "freeze",
            default=False
        ):
            config = self.config.get_detector(
                "freeze"
            )

            self.freeze_confirmation_seconds = float(
                config.get(
                    "confirmation_seconds",
                    10.0
                )
            )

            self.detectors.append(
                FreezeDetector(
                    difference_threshold=
                        config.get(
                            "difference_threshold",
                            0.30
                        ),
                    static_regions_ratio=
                        config.get(
                            "static_regions_ratio",
                            0.90
                        ),
                    recovery_difference_threshold=
                        config.get(
                            "recovery_difference_threshold",
                            2.0
                        ),
                    recovery_changed_regions_ratio=
                        config.get(
                            "recovery_changed_regions_ratio",
                            0.30
                        ),
                    confirmation_seconds=
                        self.freeze_confirmation_seconds,
                    recovery_seconds=
                        config.get(
                            "recovery_seconds",
                            2.0
                        ),
                    analysis_width=
                        config.get(
                            "analysis_width",
                            320
                        ),
                    analysis_height=
                        config.get(
                            "analysis_height",
                            180
                        ),
                    grid_rows=
                        config.get(
                            "grid_rows",
                            3
                        ),
                    grid_columns=
                        config.get(
                            "grid_columns",
                            3
                        )
                )
            )

        if self.config.is_enabled(
            "artifact",
            default=False
        ):
            config = self.config.get_detector(
                "artifact"
            )

            self.detectors.append(
                ArtifactDetector(
                    block_sizes=tuple(
                        config.get(
                            "block_sizes",
                            [8, 16]
                        )
                    ),
                    alignment_threshold=
                        config.get(
                            "alignment_threshold",
                            1.22
                        ),
                    temporal_increase_threshold=
                        config.get(
                            "temporal_increase_threshold",
                            0.22
                        ),
                    minimum_boundary_strength=
                        config.get(
                            "minimum_boundary_strength",
                            4.0
                        ),
                    affected_regions_ratio=
                        config.get(
                            "affected_regions_ratio",
                            0.25
                        ),
                    confirmation_seconds=
                        config.get(
                            "confirmation_seconds",
                            3.0
                        ),
                    recovery_seconds=
                        config.get(
                            "recovery_seconds",
                            2.0
                        ),
                    baseline_seconds=
                        config.get(
                            "baseline_seconds",
                            4.0
                        ),
                    analysis_width=
                        config.get(
                            "analysis_width",
                            320
                        ),
                    analysis_height=
                        config.get(
                            "analysis_height",
                            180
                        ),
                    grid_rows=
                        config.get(
                            "grid_rows",
                            4
                        ),
                    grid_columns=
                        config.get(
                            "grid_columns",
                            4
                        )
                )
            )

        if self.config.is_enabled(
            "channel_id",
            default=False
        ):
            config = self.config.get_detector(
                "channel_id"
            )

            self.detectors.append(
                ChannelIdDetector(
                    channels=config.get(
                        "channels",
                        {
                            "2.1": "RED2",
                            "2.2": "FORO",
                            "5.1": "RED5",
                            "9.1": "NU9VE",
                        }
                    ),
                    confirmation_seconds=
                        config.get(
                            "confirmation_seconds",
                            0.5
                        ),
                    disappearance_seconds=
                        config.get(
                            "disappearance_seconds",
                            2.0
                        ),
                    minimum_score=
                        config.get(
                            "minimum_score",
                            65.0
                        ),
                    roi_x=config.get(
                        "roi_x",
                        0
                    ),
                    roi_y=config.get(
                        "roi_y",
                        0
                    ),
                    roi_width=config.get(
                        "roi_width",
                        320
                    ),
                    roi_height=config.get(
                        "roi_height",
                        100
                    ),
                    processing_interval_seconds=
                        config.get(
                            "processing_interval_seconds",
                            0.25
                        ),
                    capture_id=self.capture_id,
                    capture_config_path=(
                        "config/templates/"
                        + self.capture_id
                        + "/config.yaml"
                    ),
                    template_directory=
                        config.get(
                            "template_directory",
                            "config/templates/red2"
                        ),
                    template_threshold=
                        config.get(
                            "template_threshold",
                            0.62
                        ),
                    generic_threshold=
                        config.get(
                            "generic_threshold",
                            0.62
                        ),
                    supported_virtual_channels=
                        config.get(
                            "supported_virtual_channels",
                            [
                                "2.1",
                                "2.2",
                                "5.1",
                                "9.1",
                            ]
                        ),
                    ocr_required=config.get(
                        "ocr_required",
                        False
                    ),
                    completed_event_callback=(
                        self.channel_id_event_callback
                    )
                )
            )

    def process(self, context):

        alarm_events = []
        detector_results = {}
        pure_black_candidate = False

        for detector in self.detectors:

            if (
                detector.detector_type == "freeze"
                and pure_black_candidate
            ):
                result = (
                    detector.suppress_for_pure_black()
                )
            else:
                result = detector.process(
                    context
                )

            if isinstance(result, dict):
                detector_results[
                    detector.detector_type
                ] = result

            if detector.detector_type == "black":
                details = (
                    result.get("details", {})
                    if isinstance(result, dict)
                    else {}
                )

                pure_black_candidate = (
                    details.get("classification")
                    == "pure_black"
                )

            if (
                detector.detector_type
                == "channel_id"
            ):
                continue

            if isinstance(
                result,
                list
            ):
                alarm_events.extend(
                    result
                )

            elif (
                isinstance(result, dict)
                and result.get(
                    "alarm",
                    False
                )
            ):
                alarm_events.append(
                    result
                )

        return self._apply_freeze_audio_policy(
            alarm_events,
            detector_results,
        )

    def _apply_freeze_audio_policy(
        self,
        alarm_events,
        detector_results=None,
    ):
        """Coordina congelamiento y silencio como una sola falla."""

        detector_results = detector_results or {}
        now_monotonic = time.monotonic()
        now_timestamp = time.time()

        raw_freeze = detector_results.get("freeze")
        raw_no_audio = detector_results.get("no_audio")

        self._remember_freeze_candidate(
            raw_freeze,
            now_monotonic,
        )

        freeze_event = self._qualified_freeze_event(
            raw_freeze,
            now_monotonic,
        )

        no_audio_event = (
            raw_no_audio
            if isinstance(raw_no_audio, dict)
            and raw_no_audio.get("alarm", False)
            else None
        )

        freeze_candidate_active = (
            self._freeze_candidate_is_active(raw_freeze)
        )

        other_events = [
            event
            for event in alarm_events
            if isinstance(event, dict)
            and event.get("type")
            not in {"freeze", "no_audio"}
        ]

        if (
            freeze_event is not None
            and no_audio_event is not None
        ):
            self._combined_freeze_active = True
            self._post_freeze_silence_start = None
            other_events.append(
                self._build_combined_freeze(
                    freeze_event,
                    no_audio_event,
                )
            )
            return other_events

        if self._combined_freeze_active:
            self._combined_freeze_active = False

            if no_audio_event is not None:
                self._post_freeze_silence_start = now_timestamp
            else:
                self._post_freeze_silence_start = None

            # La ausencia de freeze permite a EventEngine cerrar el evento.
            return other_events

        # El silencio puede alcanzar sus 10 s antes que la imagen fija si
        # ambos defectos no comenzaron exactamente al mismo tiempo. Mientras
        # el candidato FREEZE siga avanzando, se retiene NO_AUDIO para evitar
        # abrir dos eventos. Si el candidato se rompe antes de confirmarse,
        # NO_AUDIO se libera inmediatamente conservando su inicio real.
        if (
            no_audio_event is not None
            and freeze_candidate_active
        ):
            return other_events

        # Imagen fija con audio presente: contenido editorial normal.
        if no_audio_event is None:
            self._post_freeze_silence_start = None
            return other_events

        # Si el video ya se recuperó, el silencio debe mantenerse otros 10 s
        # antes de convertirse en una nueva alarma independiente NO_AUDIO.
        if self._post_freeze_silence_start is not None:
            post_duration = (
                now_timestamp
                - self._post_freeze_silence_start
            )

            if post_duration < self.audio_confirmation_seconds:
                return other_events

            no_audio_event = dict(no_audio_event)
            audio_details = dict(
                no_audio_event.get("details", {})
            )
            audio_details[
                "failure_started_timestamp"
            ] = self._post_freeze_silence_start
            audio_details["duration"] = round(
                post_duration,
                2,
            )
            audio_details[
                "reconfirmed_after_freeze"
            ] = True
            no_audio_event["details"] = audio_details

        other_events.append(no_audio_event)
        return other_events

    @staticmethod
    def _freeze_candidate_is_active(freeze_result):
        if not isinstance(freeze_result, dict):
            return False

        details = freeze_result.get("details", {})

        if details.get("reason") in {
            "suppressed_by_pure_black",
            "frame_none",
            "initial_frame",
        }:
            return False

        try:
            duration = float(details.get("duration", 0.0))
            static_ratio = float(
                details.get("static_ratio_percent", 0.0)
            )
            required_ratio = float(
                details.get(
                    "required_static_ratio_percent",
                    100.0,
                )
            )
        except (TypeError, ValueError):
            return False

        return (
            duration > 0.0
            and static_ratio >= required_ratio
        )

    def _remember_freeze_candidate(
        self,
        freeze_result,
        now_monotonic,
    ):
        if not isinstance(freeze_result, dict):
            return

        details = freeze_result.get("details", {})

        if details.get("reason") == "suppressed_by_pure_black":
            self._recent_freeze_candidate = None
            self._recent_freeze_candidate_seen = None
            return

        try:
            duration = float(details.get("duration", 0.0))
            static_ratio = float(
                details.get("static_ratio_percent", 0.0)
            )
            required_ratio = float(
                details.get(
                    "required_static_ratio_percent",
                    100.0,
                )
            )
        except (TypeError, ValueError):
            return

        minimum_duration = max(
            0.0,
            self.freeze_confirmation_seconds
            - self.freeze_confirmation_tolerance,
        )

        if (
            static_ratio >= required_ratio
            and duration >= minimum_duration
        ):
            self._recent_freeze_candidate = dict(freeze_result)
            self._recent_freeze_candidate["details"] = dict(details)
            self._recent_freeze_candidate_seen = now_monotonic

    def _qualified_freeze_event(
        self,
        raw_freeze,
        now_monotonic,
    ):
        if (
            isinstance(raw_freeze, dict)
            and raw_freeze.get("alarm", False)
        ):
            return raw_freeze

        if (
            self._recent_freeze_candidate is None
            or self._recent_freeze_candidate_seen is None
        ):
            return None

        if (
            now_monotonic
            - self._recent_freeze_candidate_seen
            > self.freeze_candidate_grace_seconds
        ):
            self._recent_freeze_candidate = None
            self._recent_freeze_candidate_seen = None
            return None

        qualified = dict(self._recent_freeze_candidate)
        qualified["alarm"] = True
        qualified["details"] = dict(
            qualified.get("details", {})
        )
        qualified["details"][
            "confirmation_boundary_tolerance_seconds"
        ] = self.freeze_confirmation_tolerance
        return qualified

    @staticmethod
    def _build_combined_freeze(
        freeze_event,
        no_audio_event,
    ):
        combined_freeze = dict(freeze_event)
        freeze_details = dict(
            freeze_event.get("details", {})
        )
        audio_details = dict(
            no_audio_event.get("details", {})
        )

        start_candidates = []

        for details in (freeze_details, audio_details):
            try:
                value = float(
                    details.get("failure_started_timestamp")
                )
            except (TypeError, ValueError):
                continue
            start_candidates.append(value)

        if start_candidates:
            freeze_details[
                "failure_started_timestamp"
            ] = max(start_candidates)

        freeze_details.update({
            "requires_no_audio": True,
            "audio_gate_active": True,
            "audio_gate": {
                "left_db": audio_details.get("left_db"),
                "right_db": audio_details.get("right_db"),
                "highest_channel_db": audio_details.get(
                    "highest_channel_db"
                ),
                "level_threshold_db": audio_details.get(
                    "level_threshold_db"
                ),
                "confirmation_seconds": audio_details.get(
                    "confirmation_seconds"
                ),
            },
        })

        combined_freeze["details"] = freeze_details
        return combined_freeze
