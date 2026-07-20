from detectors.base_detector import BaseDetector


class SignalDetector(BaseDetector):

    def detect(self, frame):

        return {
            "alarm": False,
            "type": "signal"
        }
