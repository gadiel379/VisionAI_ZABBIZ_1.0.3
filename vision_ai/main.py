# -*- coding: utf-8 -*-

"""Vision AI: hasta dos pipelines USB independientes."""

import signal
import time
from pathlib import Path

import yaml

from camera.hardware_discovery import CaptureHardwareDiscovery
from core.capture_pipeline import CapturePipeline
from integrations.telegram_notifier import TelegramNotifier
from integrations.zabbix_snmp_notifier import ZabbixSnmpNotifier
from utils.config import Config
from web.dashboard import Dashboard


PROJECT_ROOT = Path(__file__).resolve().parent


def load_channels():
    path = PROJECT_ROOT / "config" / "channels.yaml"
    with path.open("r", encoding="utf-8") as file:
        configuration = yaml.safe_load(file) or {}
    captures = configuration.setdefault("captures", {})
    captures.setdefault("capture_1", {})
    captures.setdefault("capture_2", {})
    return configuration


def save_resolved_hardware(configuration, resolved):
    """Migra /dev/videoN a identidad estable sin tocar datos del canal."""
    changed = False
    for capture_id, hardware in resolved.items():
        capture = configuration["captures"][capture_id]
        values = {
            "hardware_id": hardware["hardware_id"],
            "video_device": hardware["video_device"],
            "audio_device": hardware["audio_device"],
        }
        for key, value in values.items():
            if capture.get(key) != value:
                capture[key] = value
                changed = True
    if not changed:
        return
    path = PROJECT_ROOT / "config" / "channels.yaml"
    temporary = path.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(configuration, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def main():
    cfg = Config()
    channels = load_channels()
    discovery = CaptureHardwareDiscovery(maximum_devices=2)
    available = discovery.discover()
    print(f"[HARDWARE] Capturadoras USB completas detectadas: {len(available)}")
    for item in available:
        print(
            f"[HARDWARE] {item['hardware_id']} video={item['video_device']} "
            f"audio={item['audio_device']} {item['label']}"
        )

    resolved = {}
    used = set()
    for capture_id in ("capture_1", "capture_2"):
        capture = channels["captures"][capture_id]
        if not capture.get("enabled", False):
            continue
        hardware = discovery.resolve(capture)
        if hardware is None:
            print(f"[PIPELINE] {capture_id} sin hardware USB disponible/asignado")
            continue
        if hardware["hardware_id"] in used:
            print(f"[PIPELINE] {capture_id} rechazado: hardware físico duplicado")
            continue
        used.add(hardware["hardware_id"])
        resolved[capture_id] = hardware

    save_resolved_hardware(channels, resolved)

    zabbix = ZabbixSnmpNotifier(project_root=PROJECT_ROOT)
    telegram = TelegramNotifier(project_root=PROJECT_ROOT)
    dashboard = Dashboard(
        audio_monitor=None,
        zabbix_notifier=zabbix,
        host="0.0.0.0",
        port=5000,
    )

    pipelines = []
    for capture_id in ("capture_1", "capture_2"):
        capture = channels["captures"][capture_id]
        if not capture.get("enabled", False):
            dashboard.set_capture_status(capture_id, "DESHABILITADA")
            continue
        hardware = resolved.get(capture_id)
        if hardware is None:
            dashboard.set_capture_status(capture_id, "SIN CAPTURADORA")
            continue
        pipeline = CapturePipeline(
            capture_id=capture_id,
            channel_config=capture,
            hardware=hardware,
            dashboard=dashboard,
            telegram_notifier=telegram,
            zabbix_notifier=zabbix,
            width=cfg.get("camera", "width"),
            height=cfg.get("camera", "height"),
            camera_fps=cfg.get("camera", "fps"),
            preview_fps=15.0,
            evidence_fps=10.0,
        )
        pipelines.append(pipeline)

    for pipeline in pipelines:
        pipeline.start()
    dashboard.start()

    stopping = False

    def request_stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    try:
        while not stopping:
            time.sleep(0.5)
    finally:
        for pipeline in reversed(pipelines):
            pipeline.stop()
        dashboard.stop()
        telegram.stop()
        zabbix.stop()
        print("Sistema detenido")


if __name__ == "__main__":
    main()

