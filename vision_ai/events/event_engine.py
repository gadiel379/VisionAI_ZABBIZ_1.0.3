import os
import time
from datetime import datetime
from pathlib import Path

import yaml

from events.evidence_manager import EvidenceManager
from events.event_types import EventTypes


class EventEngine:

    def __init__(
        self,
        target=EventTypes.PERSON,
        min_confidence=0.70,
        required_frames=3,
        capture_id="capture_1"
    ):
        self.target = target

        self.min_confidence = float(
            min_confidence
        )

        self.required_frames = int(
            required_frames
        )

        self.capture_id = str(
            capture_id
        )

        self.channels_config_path = (
            Path(__file__).resolve().parent.parent
            / "config"
            / "channels.yaml"
        )

        self.person_counter = 0
        self.active_events = {}

        self.evidence = EvidenceManager()

    def _load_signal_metadata(self):

        channel_config = {}

        try:

            with self.channels_config_path.open(
                "r",
                encoding="utf-8"
            ) as file:

                configuration = (
                    yaml.safe_load(file)
                    or {}
                )

            channel_config = (
                configuration.get(
                    "captures",
                    {}
                ).get(
                    self.capture_id,
                    {}
                )
                or {}
            )

        except (
            OSError,
            AttributeError,
            TypeError,
            yaml.YAMLError
        ) as error:

            print(
                "[EVENT ENGINE] "
                "No se pudo leer channels.yaml: "
                f"{error}"
            )

        channel_name = str(
            channel_config.get(
                "channel_name",
                ""
            )
            or ""
        )

        return {
            "capture_id": self.capture_id,
            "channel": channel_name,
            "channel_name": channel_name,
            "station_id": str(
                channel_config.get(
                    "station_id",
                    ""
                )
                or ""
            ),
            "virtual_channel": str(
                channel_config.get(
                    "channel_number",
                    ""
                )
                or ""
            ),
            "location": str(
                channel_config.get(
                    "location",
                    ""
                )
                or ""
            )
        }

    @staticmethod
    def _confidence_percent(value):

        try:
            confidence = float(value)

        except (TypeError, ValueError):
            return 0.0

        if confidence <= 1.0:
            confidence *= 100.0

        return round(
            max(
                0.0,
                min(
                    100.0,
                    confidence
                )
            ),
            2
        )

    def _normalize_detection(
        self,
        detection
    ):

        if not isinstance(
            detection,
            dict
        ):
            return None

        if "alarm" in detection:

            if not detection.get(
                "alarm",
                False
            ):
                return None

            return {
                "type": detection.get(
                    "type",
                    "unknown"
                ),
                "confidence":
                    self._confidence_percent(
                        detection.get(
                            "confidence",
                            0
                        )
                    ),
                "details": dict(
                    detection.get(
                        "details",
                        {}
                    )
                ),
                "bbox": detection.get(
                    "bbox"
                )
            }

        label = detection.get(
            "label"
        )

        if label != self.target:
            return None

        try:

            raw_confidence = float(
                detection.get(
                    "confidence",
                    0
                )
            )

        except (TypeError, ValueError):
            return None

        if (
            raw_confidence
            < self.min_confidence
        ):
            return None

        return {
            "type": label,
            "confidence":
                self._confidence_percent(
                    raw_confidence
                ),
            "details": dict(
                detection.get(
                    "details",
                    {}
                )
            ),
            "bbox": detection.get(
                "bbox"
            )
        }

    def _create_event(
        self,
        detection,
        frame
    ):

        confirmed_timestamp = time.time()

        details = dict(
            detection.get(
                "details",
                {}
            )
        )

        failure_started_timestamp = (
            details.get(
                "failure_started_timestamp",
                confirmed_timestamp
            )
        )

        try:

            failure_started_timestamp = float(
                failure_started_timestamp
            )

        except (TypeError, ValueError):

            failure_started_timestamp = (
                confirmed_timestamp
            )

        base_event_id = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        event_id_root = (
            base_event_id
            if self.capture_id == "capture_1"
            else f"{base_event_id}_c2"
        )
        event_id = event_id_root
        suffix = 1
        while (Path("storage/events") / event_id).exists():
            event_id = f"{event_id_root}_{suffix:02d}"
            suffix += 1

        folder = (
            self.evidence.get_event_folder(
                event_id
            )
        )

        signal = (
            self._load_signal_metadata()
        )

        event = {
            "id": event_id,
            "folder": folder,
            "capture_id": signal[
                "capture_id"
            ],
            "channel": signal[
                "channel"
            ],
            "channel_name": signal[
                "channel_name"
            ],
            "station_id": signal[
                "station_id"
            ],
            "virtual_channel": signal[
                "virtual_channel"
            ],
            "location": signal[
                "location"
            ],
            "signal": dict(signal),
            "type": detection["type"],
            "status": "active",
            "confidence":
                detection["confidence"],
            "details": details,
            "bbox": detection.get(
                "bbox"
            ),
            "failure_started_timestamp":
                failure_started_timestamp,
            "failure_started_at":
                datetime.fromtimestamp(
                    failure_started_timestamp
                ),
            "confirmed_timestamp":
                confirmed_timestamp,
            "confirmed_at":
                datetime.fromtimestamp(
                    confirmed_timestamp
                ),
            "ended_timestamp": None,
            "ended_at": None,
            "duration_seconds": None,
            "snapshot": None,
            "snapshot_ai": None,
            "clip": None,
            "telegram": {
                "attempted": False,
                "sent": False,
                "status": "pending"
            },
            "json": os.path.join(
                folder,
                "event.json"
            )
        }

        if frame is not None:

            event["snapshot"] = (
                self.evidence.save_snapshot(
                    frame,
                    event_id
                )
            )

            event["snapshot_ai"] = (
                self.evidence.save_ai_snapshot(
                    frame,
                    event_id,
                    event["bbox"],
                    event["type"],
                    event["confidence"]
                    / 100.0
                )
            )

        self.evidence.save_json(
            event,
            event_id
        )

        self.active_events[
            event["type"]
        ] = event

        print(
            "[EVENT ENGINE] "
            f"Inicio: {event['type']} "
            f"id={event['id']}"
        )

        return event

    def _recover_event(
        self,
        event_type
    ):

        event = self.active_events.pop(
            event_type
        )

        ended_timestamp = time.time()

        duration_seconds = (
            ended_timestamp
            - event[
                "failure_started_timestamp"
            ]
        )

        event["status"] = "recovered"

        event["ended_timestamp"] = (
            ended_timestamp
        )

        event["ended_at"] = (
            datetime.fromtimestamp(
                ended_timestamp
            )
        )

        event["duration_seconds"] = round(
            max(
                0.0,
                duration_seconds
            ),
            2
        )

        event["details"][
            "total_duration_seconds"
        ] = event[
            "duration_seconds"
        ]

        self.evidence.save_json(
            event,
            event["id"]
        )

        print(
            "[EVENT ENGINE] "
            f"Recuperación: "
            f"{event['type']} "
            f"duración="
            f"{event['duration_seconds']}s"
        )

        return event

    def update(
        self,
        detections,
        frame=None
    ):

        normalized = {}

        for detection in (
            detections or []
        ):

            result = (
                self._normalize_detection(
                    detection
                )
            )

            if result is None:
                continue

            normalized[
                result["type"]
            ] = result

        actions = []

        for event_type, detection in (
            normalized.items()
        ):

            if (
                event_type
                not in self.active_events
            ):

                event = self._create_event(
                    detection,
                    frame
                )

                actions.append(
                    {
                        "action": "started",
                        "event": event
                    }
                )

            else:

                active_event = (
                    self.active_events[
                        event_type
                    ]
                )

                active_event["confidence"] = (
                    detection["confidence"]
                )

                current_details = dict(
                    detection.get(
                        "details",
                        {}
                    )
                )

                current_details.pop(
                    "failure_started_timestamp",
                    None
                )

                active_event[
                    "details"
                ].update(
                    current_details
                )

        for event_type in list(
            self.active_events.keys()
        ):

            if event_type not in normalized:

                event = self._recover_event(
                    event_type
                )

                actions.append(
                    {
                        "action": "recovered",
                        "event": event
                    }
                )

        return actions

    def attach_clip(
        self,
        event,
        clip_path,
        clip_mode,
        clip_duration
    ):

        event["clip"] = clip_path

        event["details"][
            "clip_mode"
        ] = clip_mode

        event["details"][
            "clip_duration_seconds"
        ] = round(
            float(clip_duration),
            2
        )

        self.evidence.save_json(
            event,
            event["id"]
        )
