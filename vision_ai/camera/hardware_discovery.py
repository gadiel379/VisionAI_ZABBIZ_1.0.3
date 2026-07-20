# -*- coding: utf-8 -*-

"""Descubrimiento y emparejamiento estable de capturadoras USB.

La identidad operativa es el puerto fisico USB (bus + devpath). El nombre,
fabricante y serie solamente se muestran como informacion. Video y audio se
aceptan como un solo equipo unicamente cuando proceden del mismo padre USB.
"""

import re
import subprocess
from pathlib import Path


class CaptureHardwareDiscovery:

    def __init__(self, sys_root="/sys", dev_root="/dev", maximum_devices=2):
        self.sys_root = Path(sys_root)
        self.dev_root = Path(dev_root)
        self.maximum_devices = int(maximum_devices)

    @staticmethod
    def _read(path, default=""):
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return default

    def _usb_parent(self, path):
        try:
            current = path.resolve()
        except OSError:
            return None

        for candidate in (current, *current.parents):
            if (candidate / "idVendor").exists() and (candidate / "idProduct").exists():
                return candidate
        return None

    def _identity(self, usb_parent):
        bus = self._read(usb_parent / "busnum")
        devpath = self._read(usb_parent / "devpath")
        if not bus or not devpath:
            return None
        clean_path = re.sub(r"[^0-9.-]", "", devpath)
        return f"usb-{bus}-{clean_path}"

    def _audio_cards(self):
        result = {}
        sound_root = self.sys_root / "class" / "sound"
        for card_path in sound_root.glob("card[0-9]*"):
            usb_parent = self._usb_parent(card_path / "device")
            if usb_parent is None:
                continue
            hardware_id = self._identity(usb_parent)
            if not hardware_id:
                continue
            number = card_path.name[4:]
            pcm = self.dev_root / "snd" / f"pcmC{number}D0c"
            if not pcm.exists():
                continue
            result[hardware_id] = {
                "audio_device": f"plughw:{number},0",
                "audio_card": int(number),
                "audio_pcm": str(pcm),
            }
        return result

    def _format_supported(self, video_device):
        try:
            completed = subprocess.run(
                ["v4l2-ctl", "-d", video_device, "--list-formats-ext"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
                check=False,
            )
            output = completed.stdout or ""
            if completed.returncode != 0 or not output.strip():
                return True
        except (OSError, subprocess.TimeoutExpired):
            return True

        has_mjpg = "MJPG" in output or "Motion-JPEG" in output
        has_720 = "1280x720" in output
        return bool(has_mjpg and has_720)

    def discover(self):
        audio_by_hardware = self._audio_cards()
        devices = []
        video_root = self.sys_root / "class" / "video4linux"

        for video_path in sorted(video_root.glob("video[0-9]*")):
            # UVC suele publicar index0 (captura) e index1 (metadatos).
            index = self._read(video_path / "index", "0")
            if index != "0":
                continue

            usb_parent = self._usb_parent(video_path / "device")
            if usb_parent is None:
                continue
            hardware_id = self._identity(usb_parent)
            audio = audio_by_hardware.get(hardware_id)
            if not hardware_id or not audio:
                continue

            video_device = str(self.dev_root / video_path.name)
            if not self._format_supported(video_device):
                continue

            product = self._read(usb_parent / "product", "Capturadora USB")
            manufacturer = self._read(usb_parent / "manufacturer")
            serial = self._read(usb_parent / "serial")
            bus = self._read(usb_parent / "busnum")
            devpath = self._read(usb_parent / "devpath")
            port_label = f"USB bus {bus}, puerto {devpath}"
            # Etiqueta breve para los dos selectores del dashboard. El puerto
            # continúa siendo la identidad interna, pero no se muestra aquí.
            display_label = (
                f"{product} - {serial}"
                if serial
                else product
            )

            devices.append({
                "hardware_id": hardware_id,
                "label": display_label or "Capturadora USB",
                "port_label": port_label,
                "video_device": video_device,
                "audio_device": audio["audio_device"],
                "audio_pcm": audio["audio_pcm"],
                "manufacturer": manufacturer,
                "product": product,
                "serial": serial,
                "vendor_id": self._read(usb_parent / "idVendor"),
                "product_id": self._read(usb_parent / "idProduct"),
                "available": True,
            })

        devices.sort(key=lambda item: item["hardware_id"])
        return devices[:self.maximum_devices]

    def resolve(self, configured_capture):
        devices = self.discover()
        selected_id = str(configured_capture.get("hardware_id", "")).strip()
        legacy_video = str(configured_capture.get("video_device", "")).strip()

        if selected_id:
            for device in devices:
                if device["hardware_id"] == selected_id:
                    return device

        # Migracion segura de la configuracion anterior: identifica el equipo
        # que actualmente corresponde al /dev/videoN guardado.
        for device in devices:
            if device["video_device"] == legacy_video:
                return device
        return None
