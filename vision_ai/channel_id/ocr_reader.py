# -*- coding: utf-8 -*-

import re

import cv2
import pytesseract


class ChannelOcrReader:

    def read(self, image):
        results = []

        # Lectura general de las dos líneas. Es la ruta principal
        # utilizada por RED2 y RED5.
        for config in (
            "--oem 3 --psm 6",
            "--oem 3 --psm 11",
        ):
            normalized = self._run_tesseract(
                image,
                config,
            )

            if normalized:
                results.append(normalized)

        # En FORO el logotipo circular de FGR queda detrás de la
        # primera línea y dificulta la lectura completa. Se procesa
        # por separado la mitad superior con varios umbrales. Esta
        # segunda ruta recupera el distintivo y el canal; los
        # resultados se combinan con la lectura general.
        if image is not None and getattr(image, "size", 0) > 0:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(
                    image,
                    cv2.COLOR_BGR2GRAY,
                )
            else:
                gray = image

            first_line_height = max(
                1,
                int(gray.shape[0] * 0.48),
            )
            first_line = gray[:first_line_height, :]

            for threshold in (170, 180, 190, 200):
                _, binary = cv2.threshold(
                    first_line,
                    threshold,
                    255,
                    cv2.THRESH_BINARY_INV,
                )

                normalized = self._run_tesseract(
                    binary,
                    "--oem 3 --psm 7",
                )

                if normalized:
                    results.append(normalized)

        # Se combinan los resultados porque una pasada puede leer la
        # ubicación y otra el distintivo/canal. ChannelValidator exige
        # que distintivo y canal coincidan con la configuración antes
        # de aceptar el evento.
        unique_results = []

        for result in results:
            if result not in unique_results:
                unique_results.append(result)

        return " ".join(unique_results)

    def _run_tesseract(self, image, config):
        try:
            text = pytesseract.image_to_string(
                image,
                config=(
                    config
                    + " -c tessedit_char_whitelist="
                    + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,-_ "
                ),
            )
        except Exception:
            return ""

        return self.normalize(text)

    @staticmethod
    def normalize(text):
        text = str(text or "").upper()
        text = text.replace("\n", " ")
        text = re.sub(r"[^A-Z0-9.,\- ]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
