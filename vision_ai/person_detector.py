from ai.detector import Detector


class PersonDetector:

    def __init__(self):
        self.detector = Detector()

    def detect(self, frame):

        detections = self.detector.detect(frame)

        for obj in detections:

            if obj["label"] == "person":

                return {
                    "alarm": True,
                    "type": "person",
                    "confidence": obj["confidence"],
                    "bbox": obj["bbox"],
                    "details": obj
                }

        return {
            "alarm": False
        }
