# -*- coding: utf-8 -*-

import json
from datetime import datetime
from pathlib import Path

import cv2


class ChannelIdEventManager:

    def __init__(
        self,
        base_path="storage/events",
        capture_id="capture_1",
        completed_event_callback=None,
    ):
        self.base_path = Path(base_path)
        self.completed_event_callback = (
            completed_event_callback
        )
        self.capture_id = str(capture_id).strip() or "capture_1"
        self.base_path.mkdir(
            parents=True,
            exist_ok=True,
        )

    def save(
        self,
        frame,
        banner,
        white_mask,
        ocr_ready,
        detection,
        roi=None,
    ):
        now = datetime.now()
        base_id = now.strftime("%Y%m%d_%H%M%S")

        # Se conserva el identificador histórico de capture_1. Para el
        # segundo pipeline se agrega una raíz distinta, evitando que dos
        # identificaciones simultáneas intenten escribir en la misma carpeta.
        if self.capture_id == "capture_2":
            base_id = f"{base_id}_c2"

        folder = self.base_path / base_id

        suffix = 1
        while folder.exists():
            folder = (
                self.base_path
                / f"{base_id}_{suffix:02d}"
            )
            suffix += 1

        folder.mkdir(
            parents=True,
            exist_ok=True,
        )

        paths = {
            "snapshot": folder / "snapshot.jpg",
            "banner": folder / "banner.jpg",
            "white_mask": folder / "white_mask.jpg",
            "ocr_ready": folder / "ocr_ready.jpg",
            "roi": folder / "roi.jpg",
            "json": folder / "event.json",
        }

        cv2.imwrite(str(paths["snapshot"]), frame)
        cv2.imwrite(str(paths["banner"]), banner)
        cv2.imwrite(str(paths["white_mask"]), white_mask)
        cv2.imwrite(str(paths["ocr_ready"]), ocr_ready)

        if roi is not None:
            cv2.imwrite(str(paths["roi"]), roi)

        event = {
            "id": folder.name,
            "capture_id": self.capture_id,
            "type": "channel_id",
            "time": now.isoformat(),
            "timestamp": now.isoformat(),
            "channel":
                detection.get("channel"),
            "virtual_channel":
                detection.get("virtual_channel"),
            "expected_name":
                detection.get("expected_name"),
            "expected_station_id":
                detection.get(
                    "expected_station_id"
                ),
            "expected_virtual_channel":
                detection.get(
                    "expected_virtual_channel"
                ),
            "expected_location":
                detection.get(
                    "expected_location"
                ),
            "detected_name":
                detection.get("detected_name"),
            "detected_station_id":
                detection.get(
                    "detected_station_id"
                ),
            "detected_virtual_channel":
                detection.get(
                    "detected_virtual_channel"
                ),
            "detected_location":
                detection.get(
                    "detected_location"
                ),
            "identification_status":
                detection.get(
                    "identification_status"
                ),
            "channel_matches":
                detection.get(
                    "channel_matches",
                    False,
                ),
            "station_matches":
                detection.get(
                    "station_matches",
                    False,
                ),
            "location_matches":
                detection.get(
                    "location_matches",
                    False,
                ),
            "station_similarity":
                detection.get(
                    "station_similarity",
                    0.0,
                ),
            "location_similarity":
                detection.get(
                    "location_similarity",
                    0.0,
                ),
            "text":
                detection.get("text", ""),
            "score":
                detection.get("score", 0.0),
            "bbox":
                detection.get("bbox"),
            "color_ratio":
                detection.get("color_ratio"),
            "white_ratio":
                detection.get("white_ratio"),
            "solidity":
                detection.get("solidity"),
            "aspect_ratio":
                detection.get("aspect_ratio"),
            "duration": 0.0,
            "media_type": "image",
            "snapshot": str(paths["snapshot"]),
            "banner": str(paths["banner"]),
            "white_mask": str(paths["white_mask"]),
            "ocr_ready": str(paths["ocr_ready"]),
            "roi": str(paths["roi"]),
            "json": str(paths["json"]),
            "telegram": {
                "sent": False,
                "status": "pending",
            },
            "zabbix": {
                "sent": False,
                "status": "pending",
            },
        }

        paths["json"].write_text(
            json.dumps(
                event,
                indent=4,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        print(
            "[CHANNEL ID] "
            f"esperado={event['expected_virtual_channel']} "
            f"detectado={event['detected_virtual_channel']} "
            f"estado={event['identification_status']} "
            f"carpeta={folder}"
        )

        if self.completed_event_callback is not None:
            try:
                self.completed_event_callback(event)
            except Exception as error:
                print(
                    "[CHANNEL ID] No se pudo encolar "
                    "la notificación de Telegram: "
                    f"{error}"
                )

        return event
