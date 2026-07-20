# -*- coding: utf-8 -*-

import cv2
import numpy as np


class BannerDetector:
    """
    Detector especializado para las identificaciones Televisa.

    Usa una ROI fija en la esquina superior izquierda y busca un
    rectángulo con las dimensiones observadas en RED2 y RED5.

    Resolución de análisis esperada:
        640 x 360

    La entrada 1280 x 720 se analiza a 640 x 360. La ROI cubre
    la esquina superior izquierda y admite tanto los rótulos
    angostos observados inicialmente como la identificación legal
    ancha mostrada por Las Estrellas.
    """

    def __init__(
        self,
        roi_x=0,
        roi_y=0,
        roi_width=320,
        roi_height=100,
        minimum_width=105,
        maximum_width=285,
        minimum_height=25,
        maximum_height=80,
        minimum_aspect_ratio=2.0,
        maximum_aspect_ratio=8.0,
        maximum_candidate_x=75,
        maximum_candidate_y=45,
        minimum_color_ratio=0.28,
        minimum_white_ratio=0.015,
        maximum_white_ratio=0.30,
        fallback_x=34,
        fallback_y=20,
        fallback_width=141,
        fallback_height=40,
        fallback_minimum_color_ratio=0.45,
        fallback_minimum_white_ratio=0.025,
        fallback_maximum_white_ratio=0.75,
        **_
    ):
        self.roi_x = int(roi_x)
        self.roi_y = int(roi_y)
        self.roi_width = int(roi_width)
        self.roi_height = int(roi_height)

        self.minimum_width = int(minimum_width)
        self.maximum_width = int(maximum_width)
        self.minimum_height = int(minimum_height)
        self.maximum_height = int(maximum_height)
        self.minimum_aspect_ratio = float(minimum_aspect_ratio)
        self.maximum_aspect_ratio = float(maximum_aspect_ratio)
        self.maximum_candidate_x = int(maximum_candidate_x)
        self.maximum_candidate_y = int(maximum_candidate_y)
        self.minimum_color_ratio = float(minimum_color_ratio)
        self.minimum_white_ratio = float(minimum_white_ratio)
        self.maximum_white_ratio = float(maximum_white_ratio)

        self.fallback_x = int(fallback_x)
        self.fallback_y = int(fallback_y)
        self.fallback_width = int(fallback_width)
        self.fallback_height = int(fallback_height)
        self.fallback_minimum_color_ratio = float(
            fallback_minimum_color_ratio
        )
        self.fallback_minimum_white_ratio = float(
            fallback_minimum_white_ratio
        )
        self.fallback_maximum_white_ratio = float(
            fallback_maximum_white_ratio
        )

        self.lower_magenta = np.array([118, 45, 35], dtype=np.uint8)
        self.upper_magenta = np.array([179, 255, 255], dtype=np.uint8)

        self.lower_red_orange = np.array([0, 70, 45], dtype=np.uint8)
        self.upper_red_orange = np.array([28, 255, 255], dtype=np.uint8)

    def detect(self, frame):
        roi = self._extract_roi(frame)
        if roi is None:
            return None

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        magenta_mask = cv2.inRange(
            hsv,
            self.lower_magenta,
            self.upper_magenta,
        )
        red_orange_mask = cv2.inRange(
            hsv,
            self.lower_red_orange,
            self.upper_red_orange,
        )
        color_mask = cv2.bitwise_or(
            magenta_mask,
            red_orange_mask,
        )

        color_mask = cv2.morphologyEx(
            color_mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(
                cv2.MORPH_RECT,
                (11, 5),
            ),
            iterations=2,
        )

        contours, _ = cv2.findContours(
            color_mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        candidates = []

        for contour in contours:
            x, y, width, height = cv2.boundingRect(contour)

            if not self.minimum_width <= width <= self.maximum_width:
                continue
            if not self.minimum_height <= height <= self.maximum_height:
                continue
            if x > self.maximum_candidate_x:
                continue
            if y > self.maximum_candidate_y:
                continue

            aspect_ratio = width / float(height)
            if not (
                self.minimum_aspect_ratio
                <= aspect_ratio
                <= self.maximum_aspect_ratio
            ):
                continue

            x1 = max(0, x - 6)
            y1 = max(0, y - 5)
            x2 = min(roi.shape[1], x + width + 6)
            y2 = min(roi.shape[0], y + height + 5)

            banner = roi[y1:y2, x1:x2].copy()
            if banner.size == 0:
                continue

            banner_hsv = cv2.cvtColor(
                banner,
                cv2.COLOR_BGR2HSV,
            )
            banner_magenta = cv2.inRange(
                banner_hsv,
                self.lower_magenta,
                self.upper_magenta,
            )
            banner_red_orange = cv2.inRange(
                banner_hsv,
                self.lower_red_orange,
                self.upper_red_orange,
            )
            banner_color = cv2.bitwise_or(
                banner_magenta,
                banner_red_orange,
            )

            white_mask = cv2.inRange(
                banner_hsv,
                np.array([0, 0, 150], dtype=np.uint8),
                np.array([179, 140, 255], dtype=np.uint8),
            )

            total = float(banner_color.size)
            if total <= 0:
                continue

            color_ratio = cv2.countNonZero(banner_color) / total
            white_ratio = cv2.countNonZero(white_mask) / total

            if color_ratio < self.minimum_color_ratio:
                continue
            if not (
                self.minimum_white_ratio
                <= white_ratio
                <= self.maximum_white_ratio
            ):
                continue

            contour_area = float(cv2.contourArea(contour))
            rectangle_area = float(width * height)
            solidity = (
                contour_area / rectangle_area
                if rectangle_area > 0
                else 0.0
            )

            score = (
                min(color_ratio / 0.62, 1.0) * 0.42
                + min(white_ratio / 0.11, 1.0) * 0.28
                + min(solidity / 0.85, 1.0) * 0.18
                + (
                    1.0
                    if 2.4 <= aspect_ratio <= 6.8
                    else 0.70
                ) * 0.12
            )

            candidates.append({
                "score": round(score * 100.0, 2),
                "visual_score": round(score, 6),
                "banner": banner,
                "roi": roi.copy(),
                "bbox": [
                    self.roi_x + x1,
                    self.roi_y + y1,
                    self.roi_x + x2,
                    self.roi_y + y2,
                ],
                "color_ratio": round(color_ratio, 6),
                "white_ratio": round(white_ratio, 6),
                "solidity": round(solidity, 6),
                "aspect_ratio": round(aspect_ratio, 3),
            })

        # La identificación legal aparece siempre en la misma posición.
        # Esta ventana contiene solamente las dos líneas de texto y
        # evita incluir la parte clara del degradado o el fondo del
        # programa. Se prefiere sobre el contorno de color porque el
        # fondo puede contener rojo o magenta y unirse con el rótulo.
        fixed_candidate = self._fixed_position_candidate(
            roi
        )

        if fixed_candidate is not None:
            return fixed_candidate

        if not candidates:
            return None

        return max(candidates, key=lambda item: item["score"])

    def _fixed_position_candidate(self, roi):
        roi_height, roi_width = roi.shape[:2]

        x1 = max(0, self.fallback_x)
        y1 = max(0, self.fallback_y)
        x2 = min(
            roi_width,
            self.fallback_x + self.fallback_width,
        )
        y2 = min(
            roi_height,
            self.fallback_y + self.fallback_height,
        )

        if x2 <= x1 or y2 <= y1:
            return None

        banner = roi[y1:y2, x1:x2].copy()
        if banner.size == 0:
            return None

        banner_hsv = cv2.cvtColor(
            banner,
            cv2.COLOR_BGR2HSV,
        )

        magenta_mask = cv2.inRange(
            banner_hsv,
            self.lower_magenta,
            self.upper_magenta,
        )
        red_orange_mask = cv2.inRange(
            banner_hsv,
            self.lower_red_orange,
            self.upper_red_orange,
        )
        color_mask = cv2.bitwise_or(
            magenta_mask,
            red_orange_mask,
        )

        white_mask = cv2.inRange(
            banner_hsv,
            np.array([0, 0, 150], dtype=np.uint8),
            np.array([179, 140, 255], dtype=np.uint8),
        )

        total = float(color_mask.size)
        if total <= 0:
            return None

        color_ratio = cv2.countNonZero(color_mask) / total
        white_ratio = cv2.countNonZero(white_mask) / total

        if color_ratio < self.fallback_minimum_color_ratio:
            return None
        if not (
            self.fallback_minimum_white_ratio
            <= white_ratio
            <= self.fallback_maximum_white_ratio
        ):
            return None

        aspect_ratio = (
            banner.shape[1] / float(banner.shape[0])
        )

        score = (
            min(
                color_ratio
                / self.fallback_minimum_color_ratio,
                1.0,
            ) * 0.65
            + min(white_ratio / 0.08, 1.0) * 0.35
        )

        return {
            "score": round(score * 100.0, 2),
            "visual_score": round(score, 6),
            "banner": banner,
            "roi": roi.copy(),
            "bbox": [
                self.roi_x + x1,
                self.roi_y + y1,
                self.roi_x + x2,
                self.roi_y + y2,
            ],
            "color_ratio": round(color_ratio, 6),
            "white_ratio": round(white_ratio, 6),
            "solidity": round(color_ratio, 6),
            "aspect_ratio": round(aspect_ratio, 3),
            "fallback": True,
        }

    def _extract_roi(self, frame):
        if frame is None:
            return None

        height, width = frame.shape[:2]

        x1 = max(0, self.roi_x)
        y1 = max(0, self.roi_y)
        x2 = min(width, self.roi_x + self.roi_width)
        y2 = min(height, self.roi_y + self.roi_height)

        if x2 <= x1 or y2 <= y1:
            return None

        return frame[y1:y2, x1:x2]
