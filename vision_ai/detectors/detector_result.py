# -*- coding: utf-8 -*-

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class DetectorResult:

    alarm: bool
    event_type: str
    confidence: float = 0.0
    details: Dict[str, Any] = field(
        default_factory=dict
    )
    bbox: Optional[list] = None

    def __post_init__(self):

        self.alarm = bool(
            self.alarm
        )

        self.event_type = str(
            self.event_type
        )

        try:

            self.confidence = float(
                self.confidence
            )

        except (TypeError, ValueError):

            self.confidence = 0.0

        self.confidence = max(
            0.0,
            min(
                100.0,
                self.confidence
            )
        )

        if not isinstance(
            self.details,
            dict
        ):

            self.details = {}

    def to_dict(self):

        result = {
            "alarm": self.alarm,
            "type": self.event_type,
            "confidence": round(
                self.confidence,
                2
            ),
            "details": self.details
        }

        if self.bbox is not None:

            result["bbox"] = self.bbox

        return result
