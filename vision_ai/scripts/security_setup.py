#!/usr/bin/env python3
"""Configura localmente la contraseña de recuperación de SuperAdmin."""

import getpass
import os
from pathlib import Path

import yaml
from werkzeug.security import generate_password_hash


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "integrations.yaml"


def load_config():
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def save_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    owner = None
    if CONFIG_PATH.exists():
        stat = CONFIG_PATH.stat()
        owner = (stat.st_uid, stat.st_gid)
    temporary = CONFIG_PATH.with_suffix(".yaml.tmp")
    with temporary.open("w", encoding="utf-8") as file:
        yaml.safe_dump(config, file, allow_unicode=True, sort_keys=False)
    os.chmod(temporary, 0o600)
    if owner is not None:
        os.chown(temporary, owner[0], owner[1])
    os.replace(temporary, CONFIG_PATH)


def main():
    print("Configuración local de SuperAdmin")
    password = getpass.getpass("Nueva contraseña de SuperAdmin: ")
    confirmation = getpass.getpass("Confirmar contraseña: ")
    if len(password) < 6:
        raise SystemExit("La contraseña debe tener mínimo 6 caracteres.")
    if password != confirmation:
        raise SystemExit("La confirmación no coincide.")
    config = load_config()
    security = config.setdefault("security", {})
    security.setdefault("username", "Admin")
    security.setdefault("password_hash", "")
    security["superadmin_password_hash"] = generate_password_hash(password)
    save_config(config)
    print("Contraseña de SuperAdmin guardada correctamente.")


if __name__ == "__main__":
    main()
