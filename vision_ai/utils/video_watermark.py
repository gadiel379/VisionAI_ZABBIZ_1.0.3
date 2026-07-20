# -*- coding: utf-8 -*-

from datetime import datetime

import cv2


class VideoWatermark:
    """Marca de agua única para dashboard, clips y evidencias."""

    def __init__(
        self,
        station="XHTP-TDT",
        channel_name="RED2",
        channel_number="2.1",
        location="Mérida, Yucatán",
        margin_x=15,
        margin_y=15,
        left_shift=65,
        down_shift=2,
        opacity=None,
    ):
        # opacity se conserva por compatibilidad con llamadas anteriores,
        # pero no se utiliza porque la marca no lleva fondo.
        self.station = str(station).strip()
        self.channel_name = str(channel_name).strip()
        self.channel_number = str(channel_number).strip()
        self.location = str(location).strip()
        self.margin_x = int(margin_x)
        self.margin_y = int(margin_y)
        self.left_shift = max(0, int(left_shift))
        self.down_shift = int(down_shift)

        self.font = cv2.FONT_HERSHEY_DUPLEX
        self.font_scale = 0.38
        self.text_thickness = 1
        self.outline_thickness = 2
        self.line_gap = 4

    def _build_lines(self, current_time):
        first_line_values = (
            self.station,
            self.channel_name,
            self.channel_number,
        )

        first_line = " | ".join(
            value for value in first_line_values if value
        )

        return [
            line
            for line in (
                first_line,
                self.location,
                current_time.strftime("%d/%m/%Y %H:%M:%S"),
            )
            if line
        ]

    def apply(self, frame, timestamp=None):
        if frame is None:
            return None

        output = frame.copy()

        current_time = (
            timestamp
            if isinstance(timestamp, datetime)
            else datetime.now()
        )

        lines = self._build_lines(current_time)

        if not lines:
            return output

        frame_height, frame_width = output.shape[:2]

        text_metrics = [
            cv2.getTextSize(
                line,
                self.font,
                self.font_scale,
                self.text_thickness,
            )
            for line in lines
        ]

        total_height = sum(
            text_size[1] + baseline
            for text_size, baseline in text_metrics
        )

        total_height += self.line_gap * max(0, len(lines) - 1)

        effective_margin_y = max(
            0,
            self.margin_y + self.down_shift,
        )

        cursor_y = min(
            frame_height - effective_margin_y,
            effective_margin_y + total_height,
        )

        for line, (text_size, baseline) in reversed(
            list(zip(lines, text_metrics))
        ):
            text_width, text_height = text_size

            text_x = max(
                self.margin_x,
                frame_width
                - self.margin_x
                - self.left_shift
                - text_width,
            )

            cv2.putText(
                output,
                line,
                (text_x, cursor_y),
                self.font,
                self.font_scale,
                (0, 0, 0),
                self.outline_thickness,
                cv2.LINE_AA,
            )

            cv2.putText(
                output,
                line,
                (text_x, cursor_y),
                self.font,
                self.font_scale,
                (255, 255, 255),
                self.text_thickness,
                cv2.LINE_AA,
            )

            cursor_y -= (
                text_height
                + baseline
                + self.line_gap
            )

        return output
