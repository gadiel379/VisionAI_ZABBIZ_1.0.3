# -*- coding: utf-8 -*-

from pathlib import Path

import yaml


PROJECT = Path("/home/gadiel/vision_ai")
PATH = PROJECT / "config" / "detectors.yaml"


def main():
    if not PATH.exists():
        raise SystemExit(
            f"No existe: {PATH}"
        )

    with PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        config = yaml.safe_load(file) or {}

    config["channel_id"] = {
        "enabled": True,
        "capture_id": "capture_1",
        "capture_config_path":
            "config/templates/capture_1/config.yaml",
        "channels": {
            "2.1": "RED2",
            "2.2": "FORO",
            "5.1": "RED5",
            "9.1": "NU9VE",
        },
        "supported_virtual_channels": [
            "2.1",
            "2.2",
            "5.1",
            "9.1",
        ],
        "confirmation_seconds": 0.75,
        "disappearance_seconds": 2.0,
        "processing_interval_seconds": 1.0,
        "roi_x": 0,
        "roi_y": 0,
        "roi_width": 320,
        "roi_height": 100,
    }

    temporary = PATH.with_suffix(
        ".yaml.tmp"
    )

    with temporary.open(
        "w",
        encoding="utf-8",
    ) as file:
        yaml.safe_dump(
            config,
            file,
            allow_unicode=True,
            sort_keys=False,
        )

    temporary.replace(PATH)

    print(
        "Sección channel_id actualizada "
        "sin modificar los demás detectores."
    )


if __name__ == "__main__":
    main()
