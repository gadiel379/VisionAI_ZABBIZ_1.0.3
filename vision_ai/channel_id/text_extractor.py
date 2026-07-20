# -*- coding: utf-8 -*-

import cv2
import numpy as np


class ChannelTextExtractor:

    def __init__(self, scale=5.0):
        self.scale = float(scale)

    def extract(self, banner):
        if banner is None or banner.size == 0:
            raise ValueError("Banner vacío")

        enlarged = cv2.resize(
            banner,
            None,
            fx=self.scale,
            fy=self.scale,
            interpolation=cv2.INTER_CUBIC,
        )

        hsv = cv2.cvtColor(enlarged, cv2.COLOR_BGR2HSV)

        white_mask = cv2.inRange(
            hsv,
            np.array([0, 0, 140], dtype=np.uint8),
            np.array([179, 150, 255], dtype=np.uint8),
        )

        white_mask = cv2.morphologyEx(
            white_mask,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(
                cv2.MORPH_RECT,
                (2, 2),
            ),
        )
        white_mask = cv2.morphologyEx(
            white_mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(
                cv2.MORPH_RECT,
                (3, 3),
            ),
        )

        # La máscara HSV funciona bien sobre fondos oscuros, pero en
        # RED5 el degradado claro del rótulo se confunde con las letras.
        # Tesseract obtiene una lectura estable de RED2 y RED5 usando
        # directamente el recorte ampliado en escala de grises.
        ocr_ready = cv2.cvtColor(
            enlarged,
            cv2.COLOR_BGR2GRAY,
        )

        return {
            "white_mask": white_mask,
            "ocr_ready": ocr_ready,
        }
