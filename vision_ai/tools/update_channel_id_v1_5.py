# -*- coding: utf-8 -*-

from pathlib import Path
import yaml

path = Path(
    "/home/gadiel/vision_ai/config/detectors.yaml"
)

with path.open("r", encoding="utf-8") as file:
    config = yaml.safe_load(file) or {}

config["channel_id"] = {
    "enabled": True,
    "capture_id": "capture_1",
    "capture_config_path":
        "config/templates/capture_1/config.yaml",
    "confirmation_seconds": 0.75,
    "disappearance_seconds": 2.0,
    "processing_interval_seconds": 1.0,
    "roi_x": 0,
    "roi_y": 0,
    "roi_width": 200,
    "roi_height": 80,
}

temporary = path.with_suffix(".yaml.tmp")

with temporary.open("w", encoding="utf-8") as file:
    yaml.safe_dump(
        config,
        file,
        allow_unicode=True,
        sort_keys=False,
    )

temporary.replace(path)

print(
    "Se actualizó únicamente channel_id "
    "sin modificar los demás detectores."
)
