#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
import time
from pathlib import Path


BASE = "1.3.6.1.4.1.8072.9999.1"


def oid_key(oid):
    return tuple(int(part) for part in oid.strip(".").split("."))


def load_values(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        data = {}
    updated_epoch = int(data.get("updated_epoch", 0) or 0)
    stale = not updated_epoch or time.time() - updated_epoch > 15.0
    if stale:
        data["service_status"] = 0
        data["capture_1_state"] = 4
        data["capture_2_state"] = 4
    event = data.get("last_event", {}) or {}
    values = {
        BASE + ".1.1": ("integer", data.get("service_status", 0)),
        BASE + ".1.2": ("integer", data.get("cpu_basis_points", 0)),
        BASE + ".1.3": ("integer", data.get("ram_basis_points", 0)),
        BASE + ".1.4": ("integer", data.get("temperature_decicelsius", 0)),
        BASE + ".1.5": ("integer", data.get("disk_used_basis_points", 0)),
        BASE + ".1.6": ("integer", data.get("disk_total_mb", 0)),
        BASE + ".1.7": ("integer", data.get("disk_free_mb", 0)),
        BASE + ".1.8": ("integer", data.get("updated_epoch", 0)),
        BASE + ".2.1": ("integer", data.get("capture_1_state", 0)),
        BASE + ".2.2": ("integer", data.get("capture_2_state", 0)),
        BASE + ".3.1": ("string", event.get("event_id", "")),
        BASE + ".3.2": ("integer", event.get("state", 0)),
        BASE + ".3.3": ("integer", event.get("type_code", 0)),
        BASE + ".3.4": ("string", event.get("type_name", "")),
        BASE + ".3.5": ("string", event.get("channel", "")),
        BASE + ".3.6": ("string", event.get("station_id", "")),
        BASE + ".3.7": ("string", event.get("virtual_channel", "")),
        BASE + ".3.8": ("string", event.get("capture_id", "")),
        BASE + ".3.9": ("string", event.get("started_at", "")),
        BASE + ".3.10": ("string", event.get("ended_at", "")),
        BASE + ".3.11": ("integer", event.get("duration_centiseconds", 0)),
        BASE + ".3.12": ("integer", event.get("event_epoch", 0)),
    }
    return values


def reply(oid, item):
    value_type, value = item
    print(oid, flush=True)
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
        selected = next((oid for oid in candidates if oid_key(oid) > requested_key), None)
        if selected is None:
            print("NONE", flush=True)
        else:
            reply(selected, values[selected])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
