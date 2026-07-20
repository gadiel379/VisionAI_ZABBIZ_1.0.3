# -*- coding: utf-8 -*-

from statistics import median


class ClipBuilder:

    SHORT_EVENT_LIMIT = 10.0
    SHORT_CLIP_DURATION = 30.0

    PRE_SEGMENT_SECONDS = 10.0
    FAULT_SEGMENT_SECONDS = 5.0
    POST_SEGMENT_SECONDS = 10.0
    LONG_CLIP_DURATION = 30.0

    AUDIO_SAMPLE_RATE = 48000
    AUDIO_CHANNELS = 2
    AUDIO_SAMPLE_WIDTH = 2

    def __init__(self, fps):

        self.configured_fps = float(fps)

    @staticmethod
    def _merge(*groups):

        merged = []
        timestamps = set()

        for group in groups:

            for timestamp, data in group:

                timestamp = float(timestamp)
                key = round(timestamp, 6)

                if key in timestamps:
                    continue

                timestamps.add(key)

                merged.append(
                    (
                        timestamp,
                        data
                    )
                )

        merged.sort(
            key=lambda item: item[0]
        )

        return merged

    @staticmethod
    def _range(
        items,
        start_time,
        end_time
    ):

        return [
            item
            for item in items
            if (
                float(item[0]) >= start_time
                and float(item[0]) <= end_time
            )
        ]

    def _audio_for_video_segment(
        self,
        video_segment,
        available_audio
    ):

        if not video_segment:
            return []

        ordered_video = sorted(
            video_segment,
            key=lambda item: item[0]
        )

        first_video_timestamp = float(
            ordered_video[0][0]
        )

        intervals = [
            float(ordered_video[index][0])
            - float(ordered_video[index - 1][0])
            for index in range(
                1,
                len(ordered_video)
            )
            if (
                float(ordered_video[index][0])
                > float(ordered_video[index - 1][0])
            )
        ]

        frame_interval = (
            median(intervals)
            if intervals
            else 1.0 / max(
                1.0,
                self.configured_fps
            )
        )

        segment_end = (
            float(ordered_video[-1][0])
            + frame_interval
        )

        bytes_per_audio_frame = (
            self.AUDIO_CHANNELS
            * self.AUDIO_SAMPLE_WIDTH
        )

        selected = []

        for chunk_end, data in available_audio:

            if not data:
                continue

            chunk_end = float(chunk_end)

            audio_frames = (
                len(data)
                // bytes_per_audio_frame
            )

            if audio_frames <= 0:
                continue

            chunk_duration = (
                audio_frames
                / self.AUDIO_SAMPLE_RATE
            )

            chunk_start = (
                chunk_end
                - chunk_duration
            )

            overlap_start = max(
                first_video_timestamp,
                chunk_start
            )

            overlap_end = min(
                segment_end,
                chunk_end
            )

            if overlap_end <= overlap_start:
                continue

            start_frame = int(round(
                (
                    overlap_start
                    - chunk_start
                )
                * self.AUDIO_SAMPLE_RATE
            ))

            end_frame = int(round(
                (
                    overlap_end
                    - chunk_start
                )
                * self.AUDIO_SAMPLE_RATE
            ))

            start_byte = max(
                0,
                start_frame
                * bytes_per_audio_frame
            )

            end_byte = min(
                len(data),
                end_frame
                * bytes_per_audio_frame
            )

            sliced = data[
                start_byte:end_byte
            ]

            if sliced:
                selected.append(
                    (
                        overlap_end,
                        sliced
                    )
                )

        return selected

    @staticmethod
    def _calculate_effective_fps(
        frames,
        target_duration,
        fallback_fps
    ):

        if not frames:
            return float(fallback_fps)

        target_duration = float(
            target_duration
        )

        if target_duration <= 0:
            return float(fallback_fps)

        effective_fps = (
            len(frames)
            / target_duration
        )

        return max(
            1.0,
            min(
                60.0,
                effective_fps
            )
        )

    @staticmethod
    def _timeline_info(frames):

        if not frames:

            return {
                "first_timestamp": None,
                "last_timestamp": None,
                "captured_duration": 0.0,
                "frame_count": 0
            }

        ordered = sorted(
            frames,
            key=lambda item: item[0]
        )

        first_timestamp = float(
            ordered[0][0]
        )

        last_timestamp = float(
            ordered[-1][0]
        )

        return {
            "first_timestamp":
                first_timestamp,
            "last_timestamp":
                last_timestamp,
            "captured_duration": round(
                max(
                    0.0,
                    last_timestamp
                    - first_timestamp
                ),
                4
            ),
            "frame_count":
                len(ordered)
        }

    def build(
        self,
        session,
        event,
        post_frames,
        post_audio
    ):

        duration = float(
            event["duration_seconds"]
        )

        failure_start = float(
            event[
                "failure_started_timestamp"
            ]
        )

        recovery_time = float(
            event["ended_timestamp"]
        )

        if duration < self.SHORT_EVENT_LIMIT:

            post_seconds = (
                self.SHORT_CLIP_DURATION
                - self.PRE_SEGMENT_SECONDS
                - duration
            )

            post_seconds = max(
                self.POST_SEGMENT_SECONDS,
                post_seconds
            )

            pre_frames = self._range(
                session["pre_frames"],
                failure_start
                - self.PRE_SEGMENT_SECONDS,
                failure_start
            )

            fault_frames = self._range(
                session["fault_frames"],
                failure_start,
                recovery_time
            )

            selected_post_frames = self._range(
                post_frames,
                recovery_time,
                recovery_time + post_seconds
            )

            pre_audio = (
                self._audio_for_video_segment(
                    pre_frames,
                    session["pre_audio"]
                )
            )

            fault_audio = (
                self._audio_for_video_segment(
                    fault_frames,
                    session["fault_audio"]
                )
            )

            selected_post_audio = (
                self._audio_for_video_segment(
                    selected_post_frames,
                    post_audio
                )
            )

            video = self._merge(
                pre_frames,
                fault_frames,
                selected_post_frames
            )

            audio = self._merge(
                pre_audio,
                fault_audio,
                selected_post_audio
            )

            target_duration = (
                self.SHORT_CLIP_DURATION
            )

            effective_fps = (
                self._calculate_effective_fps(
                    video,
                    target_duration,
                    self.configured_fps
                )
            )

            return {
                "frames": video,
                "audio_chunks": audio,
                "mode":
                    "full_fault_30_seconds",
                "duration":
                    target_duration,
                "fps":
                    effective_fps,
                "timeline":
                    self._timeline_info(video)
            }

        pre_frames = self._range(
            session["pre_frames"],
            failure_start
            - self.PRE_SEGMENT_SECONDS,
            failure_start
        )

        start_frames = self._range(
            session["first_fault_frames"],
            failure_start,
            failure_start
            + self.FAULT_SEGMENT_SECONDS
        )

        end_frames = self._range(
            session["recent_fault_frames"],
            recovery_time
            - self.FAULT_SEGMENT_SECONDS,
            recovery_time
        )

        selected_post_frames = self._range(
            post_frames,
            recovery_time,
            recovery_time
            + float(
                session.get(
                    "post_seconds",
                    self.POST_SEGMENT_SECONDS
                )
            )
        )

        pre_audio = (
            self._audio_for_video_segment(
                pre_frames,
                session["pre_audio"]
            )
        )

        start_audio = (
            self._audio_for_video_segment(
                start_frames,
                session["first_fault_audio"]
            )
        )

        end_audio = (
            self._audio_for_video_segment(
                end_frames,
                session["recent_fault_audio"]
            )
        )

        selected_post_audio = (
            self._audio_for_video_segment(
                selected_post_frames,
                post_audio
            )
        )

        video = self._merge(
            pre_frames,
            start_frames,
            end_frames,
            selected_post_frames
        )

        audio = self._merge(
            pre_audio,
            start_audio,
            end_audio,
            selected_post_audio
        )

        target_duration = (
            self.LONG_CLIP_DURATION
        )

        effective_fps = (
            self._calculate_effective_fps(
                video,
                target_duration,
                self.configured_fps
            )
        )

        return {
            "frames": video,
            "audio_chunks": audio,
            "mode":
                "summary_30_seconds",
            "duration":
                target_duration,
            "fps":
                effective_fps,
            "timeline":
                self._timeline_info(video)
        }
