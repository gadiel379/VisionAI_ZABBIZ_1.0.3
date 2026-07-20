# -*- coding: utf-8 -*-

from pathlib import Path
from typing import Any, Dict

import yaml


class DetectorConfig:

    DEFAULT_PATH = (
        Path(__file__).resolve().parent.parent
        / "config"
        / "detectors.yaml"
    )

    def __init__(self, config_path=None):

        self.config_path = Path(
            config_path or self.DEFAULT_PATH
        )

        self.data = {}

        self.load()

    def load(self):

        if not self.config_path.exists():

            raise FileNotFoundError(
                "No existe el archivo de configuración: "
                f"{self.config_path}"
            )

        with self.config_path.open(
            "r",
            encoding="utf-8"
        ) as config_file:

            loaded_data = yaml.safe_load(
                config_file
            )

        if loaded_data is None:
            loaded_data = {}

        if not isinstance(
            loaded_data,
            dict
        ):

            raise ValueError(
                "detectors.yaml debe contener "
                "un diccionario YAML válido"
            )

        self.data = loaded_data

    def get_detector(
        self,
        detector_name: str
    ) -> Dict[str, Any]:

        detector_config = self.data.get(
            detector_name,
            {}
        )

        if not isinstance(
            detector_config,
            dict
        ):

            raise ValueError(
                "La configuración del detector "
                f"'{detector_name}' no es válida"
            )

        return dict(
            detector_config
        )

    def is_enabled(
        self,
        detector_name: str,
        default=False
    ) -> bool:

        detector_config = self.get_detector(
            detector_name
        )

        return bool(
            detector_config.get(
                "enabled",
                default
            )
        )

    def get(
        self,
        detector_name: str,
        parameter_name: str,
        default=None
    ):

        detector_config = self.get_detector(
            detector_name
        )

        return detector_config.get(
            parameter_name,
            default
        )
