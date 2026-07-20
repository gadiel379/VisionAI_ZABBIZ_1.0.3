# -*- coding: utf-8 -*-

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from detectors.detector_result import (
    DetectorResult
)


class BaseDetector(ABC):

    detector_type = "unknown"

    @abstractmethod
    def process(
        self,
        context
    ) -> Dict[str, Any]:

        raise NotImplementedError(
            f"{self.__class__.__name__} "
            "debe implementar process(context)"
        )

    def result(
        self,
        alarm=False,
        confidence=0.0,
        details=None,
        bbox: Optional[list] = None
    ):

        return DetectorResult(
            alarm=alarm,
            event_type=self.detector_type,
            confidence=confidence,
            details=details or {},
            bbox=bbox
        ).to_dict()
