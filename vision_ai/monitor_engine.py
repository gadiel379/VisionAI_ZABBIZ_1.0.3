from detectors.person_detector import PersonDetector
from detectors.freeze_detector import FreezeDetector
from detectors.black_detector import BlackDetector
from detectors.signal_detector import SignalDetector
from detectors.channel_id_detector import ChannelIdDetector
from detectors.artifact_detector import ArtifactDetector
from detectors.audio_detector import AudioDetector


class MonitorEngine:

    def __init__(self):

        self.detectors = [

            PersonDetector(),

            FreezeDetector(),

            BlackDetector(),

            SignalDetector(),

            ChannelIdDetector(),

            ArtifactDetector(),

            AudioDetector()

        ]

    def detect(self, frame):

        alarms = []

        for detector in self.detectors:

            result = detector.detect(frame)

            if result["alarm"]:

                alarms.append(result)

        return alarms
