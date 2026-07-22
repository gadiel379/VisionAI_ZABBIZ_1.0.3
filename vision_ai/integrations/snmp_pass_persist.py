#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Backend pass_persist del árbol SNMP de Vision AI."""

import json
import sys
import time
from pathlib import Path


BASE = "1.3.6.1.4.1.8072.9999.1"
CAPTURE_FIELDS = (
    ("station_id", "string"),
    ("name", "string"),
    ("channel", "string"),
    ("location", "string"),
    ("enabled", "integer"),
    ("status", "integer"),
    ("black", "integer"),
    ("no_audio", "integer"),
    ("digitalization", "integer"),
    ("frozen", "integer"),
    ("channel_id", "integer"),
)


def oid_key(oid):
    return tuple(int(part) for part in oid.strip(".").split("."))


def _capture_values(data, capture_number, stale):
    capture_id = f"capture_{capture_number}"
    capture = (data.get("captures", {}) or {}).get(capture_id, {}) or {}
    enabled = int(capture.get("enabled", 0) or 0)

    if stale:
        capture = dict(capture)
        capture["status"] = 1 if enabled else 0
        for field in ("black", "no_audio", "digitalization", "frozen", "channel_id"):
            capture[field] = 0

    values = {}
    for field_number, (field_name, value_type) in enumerate(CAPTURE_FIELDS, 1):
        default = "" if value_type == "string" else 0
        values[f"{BASE}.2.{capture_number}.{field_number}"] = (
            value_type,
            capture.get(field_name, default),
        )
    return values


def load_values(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        data = {}

    updated_epoch = int(data.get("updated_epoch", 0) or 0)
    stale = not updated_epoch or time.time() - updated_epoch > 15.0

    values = {
        BASE + ".1.1": ("integer", 0 if stale else data.get("service_status", 0)),
        BASE + ".1.2": ("integer", data.get("cpu_basis_points", 0)),
        BASE + ".1.3": ("integer", data.get("ram_basis_points", 0)),
        BASE + ".1.4": ("integer", data.get("temperature_decicelsius", 0)),
        BASE + ".1.5": ("integer", data.get("disk_used_basis_points", 0)),
        BASE + ".1.6": ("integer", data.get("disk_total_mb", 0)),
        BASE + ".1.7": ("integer", data.get("disk_free_mb", 0)),
        BASE + ".1.8": ("integer", data.get("updated_epoch", 0)),
    }
    values.update(_capture_values(data, 1, stale))
    values.update(_capture_values(data, 2, stale))
    return values


def reply(oid, item):
    value_type, value = item
    print("." + oid.lstrip("."), flush=True)
    print(value_type, flush=True)
    print(str(value).replace("\n", " "), flush=True)


def main():
    if len(sys.argv) != 2:
        return 2
    metrics_path = sys.argv[1]

    while True:
        command = sys.stdin.readline()
        if not command:
            break
        command = command.strip().lower()

        if command == "ping":
            print("PONG", flush=True)
            continue

        if command not in ("get", "getnext"):
            print("NONE", flush=True)
            continue

        requested = sys.stdin.readline().strip().lstrip(".")
        values = load_values(metrics_path)

        if command == "get":
            item = values.get(requested)
            if item is None:
                print("NONE", flush=True)
            else:
                reply(requested, item)
            continue

        requested_key = oid_key(requested)
        candidates = sorted(values, key=oid_key)
        selected = next(
            (oid for oid in candidates if oid_key(oid) > requested_key),
            None,
        )
        if selected is None:
            print("NONE", flush=True)
        else:
            reply(selected, values[selected])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
