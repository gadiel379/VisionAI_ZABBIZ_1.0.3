# -*- coding: utf-8 -*-

import re
import unicodedata
from difflib import SequenceMatcher


class ChannelValidator:

    def __init__(
        self,
        expected_name="",
        expected_station_id="",
        expected_virtual_channel="",
        expected_location="",
        station_similarity=0.72,
        location_similarity=0.54,
        **_
    ):
        self.expected_name = str(expected_name or "").strip()
        self.expected_station_id = str(
            expected_station_id or ""
        ).strip()
        self.expected_virtual_channel = str(
            expected_virtual_channel or ""
        ).strip()
        self.expected_location = str(
            expected_location or ""
        ).strip()

        self.station_similarity = float(station_similarity)
        self.location_similarity = float(location_similarity)

    def validate(self, text, visual_score=0.0):
        normalized = self._normalize(text)

        detected_channel = self._detect_expected_channel(
            normalized,
            self.expected_virtual_channel,
        )
        station_score = self._similarity_to_expected(
            normalized,
            self.expected_station_id,
        )
        location_score = self._similarity_to_expected(
            normalized,
            self.expected_location,
        )

        station_configured = bool(self.expected_station_id)
        channel_configured = bool(self.expected_virtual_channel)

        station_matches = bool(
            station_configured
            and station_score >= self.station_similarity
        )
        location_matches = bool(
            self.expected_location
            and location_score >= self.location_similarity
        )
        channel_matches = bool(
            channel_configured
            and detected_channel is not None
        )

        # La identificación legal debe coincidir con el distintivo y
        # el canal virtual configurados por el usuario. La ubicación
        # se conserva como dato informativo porque suele ser la parte
        # menos estable del OCR. Si uno de los dos campos principales
        # no está configurado, se valida solamente el disponible.
        required_matches = []

        if station_configured:
            required_matches.append(station_matches)
        if channel_configured:
            required_matches.append(channel_matches)

        valid = bool(
            required_matches
            and all(required_matches)
        )

        if valid:
            status = "correct"
        elif station_matches and not channel_matches:
            status = "channel_mismatch"
        elif channel_matches and not station_matches:
            status = "station_mismatch"
        else:
            status = "rejected_text_not_confirmed"

        return {
            "valid": valid,
            "score": round(float(visual_score) * 100.0, 2),
            "channel": self.expected_name,
            "virtual_channel": self.expected_virtual_channel,
            "detected_name": (
                self.expected_name if valid else None
            ),
            "detected_station_id": (
                self.expected_station_id
                if station_matches
                else None
            ),
            "detected_virtual_channel": (
                self.expected_virtual_channel
                if channel_matches
                else None
            ),
            "detected_location": (
                self.expected_location
                if location_matches
                else None
            ),
            "expected_name": self.expected_name,
            "expected_station_id": self.expected_station_id,
            "expected_virtual_channel":
                self.expected_virtual_channel,
            "expected_location": self.expected_location,
            "identification_status": status,
            "channel_matches": channel_matches,
            "station_matches": station_matches,
            "location_matches": location_matches,
            "station_similarity": round(station_score, 4),
            "location_similarity": round(location_score, 4),
            "text": normalized,
        }

    def _detect_expected_channel(self, text, expected_channel):
        expected = str(expected_channel or "").strip()
        if not expected or "." not in expected:
            return None

        major, minor = expected.split(".", 1)

        patterns = (
            rf"(?<!\d){re.escape(major)}\s*[.\-]\s*{re.escape(minor)}(?!\d)",
            rf"(?<!\d){re.escape(major)}\s+{re.escape(minor)}(?!\d)",
            rf"(?<!\d){re.escape(major + minor)}(?!\d)",
        )

        if any(re.search(pattern, text) for pattern in patterns):
            return expected

        compact = re.sub(r"[^0-9]", "", text)
        if major + minor in compact:
            return expected

        return None

    def _similarity_to_expected(self, recognized, expected):
        expected_normalized = self._normalize(expected)
        if not expected_normalized:
            return 0.0

        recognized_compact = re.sub(
            r"[^A-Z0-9]",
            "",
            recognized,
        )
        expected_compact = re.sub(
            r"[^A-Z0-9]",
            "",
            expected_normalized,
        )

        if not recognized_compact or not expected_compact:
            return 0.0

        if expected_compact in recognized_compact:
            return 1.0

        # Tolera TDT -> TOT y errores similares.
        expected_variants = {
            expected_compact,
            expected_compact.replace("TDT", "TOT"),
        }

        best = 0.0

        for variant in expected_variants:
            length = len(variant)

            if len(recognized_compact) <= length:
                best = max(
                    best,
                    SequenceMatcher(
                        None,
                        recognized_compact,
                        variant,
                    ).ratio(),
                )
                continue

            for index in range(
                len(recognized_compact) - length + 1
            ):
                fragment = recognized_compact[
                    index:index + length
                ]
                best = max(
                    best,
                    SequenceMatcher(
                        None,
                        fragment,
                        variant,
                    ).ratio(),
                )

        return best

    @staticmethod
    def _normalize(value):
        text = unicodedata.normalize(
            "NFKD",
            str(value or ""),
        )
        text = "".join(
            ch
            for ch in text
            if not unicodedata.combining(ch)
        )
        text = text.upper()
        text = re.sub(r"[^A-Z0-9.,\- ]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
