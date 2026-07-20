from detectors.base_detector import BaseDetector


class AudioDetector(BaseDetector):

    def detect(self, frame):

        return {
            "alarm": False,
            "type": "audio"
        }
