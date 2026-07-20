from detectors.base_detector import BaseDetector
from ai.detector import Detector


class PersonDetector(BaseDetector):

    def __init__(self):

        self.detector = Detector()

    def process(self, context):

        detecciones = self.detector.detect(
            context.ia_frame
        )

        context.detections = detecciones

        return detecciones
