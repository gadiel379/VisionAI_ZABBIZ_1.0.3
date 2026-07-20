from dataclasses import dataclass
from datetime import datetime


@dataclass
class FrameContext:

    camera: str

    frame: any

    small_frame: any

    ia_frame: any

    detections: list

    timestamp: datetime

    audio: any = None
