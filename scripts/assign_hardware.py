#!/usr/bin/env python3
"""Asigna hasta dos capturadoras completas sin cruzar video y audio."""

from pathlib import Path

import yaml

from camera.hardware_discovery import CaptureHardwareDiscovery


ROOT = Path(
    __import__("os").environ.get(
        "VISIONAI_PROJECT_ROOT",
        str(Path(__file__).resolve().parent.parent / "vision_ai"),
    )
).resolve()
CONFIG = ROOT / "config" / "channels.yaml"


def main():
    configuration = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    captures = configuration.setdefault("captures", {})
    discovery = CaptureHardwareDiscovery(maximum_devices=2)
    devices = discovery.discover()
    available = {item["hardware_id"]: item for item in devices}
    used = set()
    changed = False

    # Primero conserva cualquier asignación estable que siga conectada.
    for capture_id in ("capture_1", "capture_2"):
        capture = captures.setdefault(capture_id, {})
        if not capture.get("enabled", False):
            continue
        selected = available.get(str(capture.get("hardware_id", "")))
        if selected is None:
            legacy_video = str(capture.get("video_device", ""))
            selected = next(
                (item for item in devices if item["video_device"] == legacy_video),
                None,
            )
        if selected is None or selected["hardware_id"] in used:
            continue
        used.add(selected["hardware_id"])
        for key in ("hardware_id", "video_device", "audio_device"):
            if capture.get(key) != selected[key]:
                capture[key] = selected[key]
                changed = True

    # Si es una instalación nueva y no coincidieron los nombres /dev/videoN,
    # usa los puertos USB de forma determinista. La capturadora 1 conserva la
    # prioridad del segundo puerto y la capturadora 2 la del primero, igual que
    # la instalación de referencia. El dashboard permite invertirlas después.
    remaining = [item for item in devices if item["hardware_id"] not in used]
    unresolved = [
        capture_id
        for capture_id in ("capture_1", "capture_2")
        if captures.get(capture_id, {}).get("enabled", False)
        and str(captures[capture_id].get("hardware_id", "")) not in available
    ]
    if len(remaining) == 2 and unresolved == ["capture_1", "capture_2"]:
        remaining = [remaining[1], remaining[0]]

    for capture_id, selected in zip(unresolved, remaining):
        capture = captures[capture_id]
        if selected["hardware_id"] in used:
            continue
        used.add(selected["hardware_id"])
        for key in ("hardware_id", "video_device", "audio_device"):
            if capture.get(key) != selected[key]:
                capture[key] = selected[key]
                changed = True

    if changed:
        temporary = CONFIG.with_suffix(".yaml.tmp")
        temporary.write_text(
            yaml.safe_dump(configuration, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        temporary.replace(CONFIG)

    print(f"Capturadoras completas detectadas: {len(devices)}")
    for capture_id in ("capture_1", "capture_2"):
        capture = captures.get(capture_id, {})
        print(
            f"{capture_id}: hardware={capture.get('hardware_id', '')} "
            f"video={capture.get('video_device', '')} "
            f"audio={capture.get('audio_device', '')}"
        )


if __name__ == "__main__":
    main()
