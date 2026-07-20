# -*- coding: utf-8 -*-

import time
from pathlib import Path

import yaml

from detectors.base_detector import BaseDetector
from events.event_types import EventTypes
from channel_id.banner_detector import BannerDetector
from channel_id.text_extractor import ChannelTextExtractor
from channel_id.ocr_reader import ChannelOcrReader
from channel_id.validator import ChannelValidator
from events.channel_id_event_manager import ChannelIdEventManager


class ChannelIdDetector(BaseDetector):

    detector_type = EventTypes.CHANNEL_ID

    def __init__(
        self,
        confirmation_seconds=0.5,
        disappearance_seconds=2.0,
        processing_interval_seconds=0.25,
        capture_id="capture_1",
        capture_config_path=None,
        roi_x=0,
        roi_y=0,
        roi_width=320,
        roi_height=100,
        completed_event_callback=None,
        **_
    ):
        self.capture_id = str(capture_id).strip() or "capture_1"

        self.project_root = (
            Path(__file__).resolve().parent.parent
        )

        self.capture_config_path = Path(
            capture_config_path
            or (
                "config/templates/"
                + self.capture_id
                + "/config.yaml"
            )
        )

        if not self.capture_config_path.is_absolute():
            self.capture_config_path = (
                self.project_root
                / self.capture_config_path
            )

        config = self._load_capture_config()

        self.expected_name = str(
            config.get("name", "")
        ).strip()
        self.expected_station_id = str(
            config.get("station_id", "")
        ).strip()
        self.expected_virtual_channel = str(
            config.get("virtual_channel", "")
        ).strip()
        self.expected_location = str(
            config.get("location", "")
        ).strip()

        roi = config.get("roi") or {}

        self.confirmation_seconds = float(
            config.get(
                "confirmation_seconds",
                confirmation_seconds,
            )
        )
        self.disappearance_seconds = float(
            config.get(
                "disappearance_seconds",
                disappearance_seconds,
            )
        )
        self.processing_interval_seconds = max(
            0.10,
            float(
                config.get(
                    "processing_interval_seconds",
                    processing_interval_seconds,
                )
            ),
        )

        self.banner_detector = BannerDetector(
            roi_x=int(roi.get("x", roi_x)),
            roi_y=int(roi.get("y", roi_y)),
            roi_width=int(roi.get("width", roi_width)),
            roi_height=int(roi.get("height", roi_height)),
        )

        self.text_extractor = ChannelTextExtractor()
        self.ocr_reader = ChannelOcrReader()
        self.validator = ChannelValidator(
            expected_name=self.expected_name,
            expected_station_id=self.expected_station_id,
            expected_virtual_channel=
                self.expected_virtual_channel,
            expected_location=self.expected_location,
        )
        self.event_manager = ChannelIdEventManager(
            capture_id=self.capture_id,
            completed_event_callback=(
                completed_event_callback
            )
        )

        self.last_processing_time = 0.0
        self.detect_start_time = None
        self.missing_start_time = None
        self.visible = False
        self.last_result = self._empty_result()

    def process(self, context):
        frame = getattr(context, "small_frame", None)
        if frame is None:
            frame = getattr(context, "frame", None)

        if frame is None:
            self._reset()
            return self.last_result

        now = time.monotonic()
        if (
            now - self.last_processing_time
            < self.processing_interval_seconds
        ):
            return self.last_result

        self.last_processing_time = now

        candidate = self.banner_detector.detect(frame)
        state_now = time.monotonic()

        saved_event = None
        detection = None

        if candidate is not None:
            self.missing_start_time = None

            if self.detect_start_time is None:
                self.detect_start_time = state_now

            if (
                state_now - self.detect_start_time
                >= self.confirmation_seconds
                and not self.visible
            ):
                extracted = self.text_extractor.extract(
                    candidate["banner"]
                )
                text = self.ocr_reader.read(
                    extracted["ocr_ready"]
                )

                validation = self.validator.validate(
                    text=text,
                    visual_score=candidate[
                        "visual_score"
                    ],
                )

                if validation["valid"]:
                    detection = {
                        **validation,
                        "bbox": candidate["bbox"],
                        "banner": candidate["banner"],
                        "roi": candidate["roi"],
                        "white_mask":
                            extracted["white_mask"],
                        "ocr_ready":
                            extracted["ocr_ready"],
                        "color_ratio":
                            candidate["color_ratio"],
                        "white_ratio":
                            candidate["white_ratio"],
                        "solidity":
                            candidate["solidity"],
                        "aspect_ratio":
                            candidate["aspect_ratio"],
                    }

                    self.visible = True
                    saved_event = self.event_manager.save(
                        frame=frame,
                        banner=detection["banner"],
                        white_mask=
                            detection["white_mask"],
                        ocr_ready=
                            detection["ocr_ready"],
                        detection=detection,
                        roi=detection["roi"],
                    )
                else:
                    self.detect_start_time = None
            elif self.visible:
                self.detect_start_time = None

        else:
            self.detect_start_time = None

            if self.visible:
                if self.missing_start_time is None:
                    self.missing_start_time = state_now

                if (
                    state_now - self.missing_start_time
                    >= self.disappearance_seconds
                ):
                    self.visible = False
                    self.missing_start_time = None
            else:
                self.missing_start_time = None

        self.last_result = self.result(
            alarm=False,
            confidence=(
                detection.get("score", 0.0)
                if detection
                else (
                    candidate.get("score", 0.0)
                    if candidate
                    else 0.0
                )
            ),
            bbox=(
                candidate.get("bbox")
                if candidate
                else None
            ),
            details={
                "valid": detection is not None,
                "visual_candidate":
                    candidate is not None,
                "visible": self.visible,
                "event_saved":
                    saved_event is not None,
                "event": saved_event,
                "capture_id": self.capture_id,
                "expected_name":
                    self.expected_name,
                "expected_station_id":
                    self.expected_station_id,
                "expected_virtual_channel":
                    self.expected_virtual_channel,
                "expected_location":
                    self.expected_location,
                "detected_virtual_channel": (
                    detection.get(
                        "detected_virtual_channel"
                    )
                    if detection
                    else None
                ),
                "identification_status": (
                    detection.get(
                        "identification_status"
                    )
                    if detection
                    else (
                        "visual_candidate"
                        if candidate
                        else "not_detected"
                    )
                ),
                "text": (
                    detection.get("text", "")
                    if detection
                    else ""
                ),
            },
        )

        return self.last_result

    def _load_capture_config(self):
        # Fuente principal: channels.yaml. Este es el archivo que
        # actualiza la interfaz cuando el usuario configura una
        # capturadora. Así se evita validar contra una plantilla vieja.
        channels_path = (
            self.project_root
            / "config"
            / "channels.yaml"
        )

        if channels_path.exists():
            try:
                channels = yaml.safe_load(
                    channels_path.read_text(
                        encoding="utf-8"
                    )
                ) or {}

                capture = (
                    channels.get("captures", {})
                    .get(self.capture_id, {})
                )

                if capture:
                    return {
                        "name": capture.get(
                            "channel_name",
                            ""
                        ),
                        "station_id": capture.get(
                            "station_id",
                            ""
                        ),
                        "virtual_channel": capture.get(
                            "channel_number",
                            ""
                        ),
                        "location": capture.get(
                            "location",
                            ""
                        ),
                    }
            except (OSError, yaml.YAMLError):
                pass

        # Compatibilidad: solo se usa si channels.yaml no contiene
        # la capturadora solicitada.
        if self.capture_config_path.exists():
            try:
                loaded = yaml.safe_load(
                    self.capture_config_path.read_text(
                        encoding="utf-8"
                    )
                ) or {}
                if isinstance(loaded, dict):
                    return loaded
            except (OSError, yaml.YAMLError):
                pass

        return {}

    def _empty_result(self):
        return self.result(
            alarm=False,
            confidence=0.0,
            details={
                "valid": False,
                "visual_candidate": False,
                "visible": False,
                "event_saved": False,
                "capture_id": self.capture_id,
                "identification_status":
                    "not_detected",
            },
        )

    def _reset(self):
        self.detect_start_time = None
        self.missing_start_time = None
        self.visible = False
        self.last_result = self._empty_result()
