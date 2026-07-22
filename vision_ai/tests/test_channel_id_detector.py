# -*- coding: utf-8 -*-

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import cv2

from detectors.channel_id_detector import ChannelIdDetector


class Context:

    def __init__(self, frame):
        self.frame = frame


def main():

    detector = ChannelIdDetector()

    output_dir = (
        ROOT
        / "storage"
        / "channel_id_test"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    cap = cv2.VideoCapture(0)

    if not cap.isOpened():

        raise RuntimeError(
            "No se pudo abrir /dev/video0"
        )

    last_state = False

    try:

        while True:

            ok, frame = cap.read()

            if not ok or frame is None:

                time.sleep(0.1)
                continue

            result = detector.process(
                Context(frame)
            )

            detected = bool(
                result.get(
                    "alarm",
                    False
                )
            )

            if detected and not last_state:

                timestamp = time.strftime(
                    "%Y%m%d_%H%M%S"
                )

                frame_path = (
                    output_dir
                    / f"frame_{timestamp}.jpg"
                )

                roi_path = (
                    output_dir
                    / f"roi_{timestamp}.jpg"
                )

                mask_path = (
                    output_dir
                    / f"mask_{timestamp}.jpg"
                )

                roi = frame[
                    detector.roi_y:
                    detector.roi_y
                    + detector.roi_height,

                    detector.roi_x:
                    detector.roi_x
                    + detector.roi_width
                ]

                hsv = cv2.cvtColor(
                    roi,
                    cv2.COLOR_BGR2HSV
                )

                mask = cv2.inRange(
                    hsv,
                    detector.lower,
                    detector.upper
                )

                cv2.imwrite(
                    str(frame_path),
                    frame
                )

                cv2.imwrite(
                    str(roi_path),
                    roi
                )

                cv2.imwrite(
                    str(mask_path),
                    mask
                )

                print(
                    "[CHANNEL ID] Detectado"
                )

                print(
                    "Frame:",
                    frame_path
                )

                print(
                    "ROI:",
                    roi_path
                )

                print(
                    "Mask:",
                    mask_path
                )

            elif (
                not detected
                and last_state
            ):

                print(
                    "[CHANNEL ID] Desapareció"
                )

            last_state = detected

            time.sleep(0.05)

    except KeyboardInterrupt:

        print(
            "\nPrueba finalizada"
        )

    finally:

        cap.release()


if __name__ == "__main__":
    main()
