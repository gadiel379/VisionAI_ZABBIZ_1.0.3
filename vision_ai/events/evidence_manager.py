import os
import json
import cv2
from datetime import datetime


class EvidenceManager:

    def __init__(self, base_path="storage"):

        self.base_path = base_path

        self.events_path = os.path.join(
            base_path,
            "events"
        )

        os.makedirs(
            self.events_path,
            exist_ok=True
        )

    def get_event_folder(self, event_id):

        folder = os.path.join(
            self.events_path,
            event_id
        )

        os.makedirs(
        folder,
        exist_ok=True
        )

        return folder

    def save_snapshot(self, frame, event_id):

        folder = self.get_event_folder(
            event_id
        )

        path = os.path.join(
            folder,
            "snapshot.jpg"
        )

        cv2.imwrite(
            path,
            frame
        )

        return path

    def save_ai_snapshot(
        self,
        frame,
        event_id,
        bbox,
        label,
        confidence
    ):

        image = frame.copy()


        if bbox:

            x1, y1, x2, y2 = bbox


            cv2.rectangle(
                image,
                (x1, y1),
                (x2, y2),
                (0,255,0),
                2
            )


            text = (
                f"{label} "
                f"{confidence*100:.1f}%"
            )


            cv2.putText(
                image,
                text,
                (x1, y1-10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0,255,0),
                2
            )


        folder = self.get_event_folder(
              event_id
        )


        path = os.path.join(
            folder,
            "snapshot_ai.jpg"
        )


        cv2.imwrite(
            path,
            image
        )


        return path

    def save_json(self, data, event_id):

        folder = self.get_event_folder(
            event_id
        )

        path = os.path.join(
            folder,
            "event.json"
        )

        with open(path, "w") as file:

            json.dump(
                data,
                file,
                indent=4,
                default=str
            )

        return path
