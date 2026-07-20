# -*- coding: utf-8 -*-

import queue
import threading

from events.clip_builder import ClipBuilder


class EventClipManager:

    PRE_BUFFER_SECONDS = 10.0
    RECENT_FAULT_SECONDS = 5.0
    POST_BUFFER_SECONDS = 10.0
    TARGET_CLIP_SECONDS = 30.0

    def __init__(
        self,
        video_buffer,
        audio_buffer,
        recorder,
        event_engine,
        fps,
        completed_event_callback=None
    ):

        self.video_buffer = video_buffer
        self.audio_buffer = audio_buffer
        self.recorder = recorder
        self.event_engine = event_engine

        self.completed_event_callback = (
            completed_event_callback
        )

        self.fps = float(fps)

        self.builder = ClipBuilder(
            fps=self.fps
        )

        self.sessions = {}

        self.encoding_queue = queue.Queue()

        self.encoding_thread = threading.Thread(
            target=self._encoding_loop,
            daemon=True
        )

        self.encoding_thread.start()

    @staticmethod
    def _append_unique(
        destination,
        new_items
    ):

        existing = {
            round(
                float(item[0]),
                6
            )
            for item in destination
        }

        for item in new_items:

            key = round(
                float(item[0]),
                6
            )

            if key in existing:
                continue

            destination.append(item)
            existing.add(key)

        destination.sort(
            key=lambda item: item[0]
        )

    @staticmethod
    def _keep_recent(
        items,
        seconds,
        end_time
    ):

        start_time = (
            end_time
            - seconds
        )

        return [
            item
            for item in items
            if item[0] >= start_time
        ]

    def _media_duration(
        self,
        items
    ):

        if not items:
            return 0.0

        ordered = sorted(
            items,
            key=lambda item: item[0]
        )

        if len(ordered) == 1:
            return 1.0 / max(
                1.0,
                self.fps
            )

        return max(
            0.0,
            float(ordered[-1][0])
            - float(ordered[0][0])
            + (1.0 / max(1.0, self.fps))
        )

    def process_actions(
        self,
        actions,
        now
    ):

        for action in actions:

            event = action["event"]

            if action["action"] == "started":

                self._start_session(
                    event,
                    now
                )

            elif action["action"] == "recovered":

                self._recover_session(
                    event
                )

    def _start_session(
        self,
        event,
        now
    ):

        event_type = event["type"]

        failure_start = float(
            event[
                "failure_started_timestamp"
            ]
        )

        pre_start = (
            failure_start
            - self.PRE_BUFFER_SECONDS
        )

        pre_frames = (
            self.video_buffer.get_frames(
                start_time=pre_start,
                end_time=failure_start
            )
        )

        pre_audio = (
            self.audio_buffer.get_chunks(
                start_time=pre_start,
                end_time=failure_start
            )
        )

        fault_frames = (
            self.video_buffer.get_frames(
                start_time=failure_start,
                end_time=now
            )
        )

        fault_audio = (
            self.audio_buffer.get_chunks(
                start_time=failure_start,
                end_time=now
            )
        )

        self.sessions[event_type] = {
            "event": event,
            "failure_start":
                failure_start,
            "pre_frames":
                pre_frames,
            "pre_audio":
                pre_audio,
            "fault_frames":
                list(fault_frames),
            "fault_audio":
                list(fault_audio),
            "first_fault_frames":
                list(fault_frames),
            "first_fault_audio":
                list(fault_audio),
            "recent_fault_frames":
                list(fault_frames),
            "recent_fault_audio":
                list(fault_audio),
            "last_video_time":
                fault_frames[-1][0]
                if fault_frames
                else now,
            "last_audio_time":
                fault_audio[-1][0]
                if fault_audio
                else now,
            "recovered_timestamp":
                None,
            "post_deadline":
                None
        }

    def _append_fault_data(
        self,
        session,
        end_time
    ):

        new_frames = (
            self.video_buffer.get_frames(
                start_time=(
                    session[
                        "last_video_time"
                    ]
                    + 0.000001
                ),
                end_time=end_time
            )
        )

        if new_frames:

            self._append_unique(
                session["fault_frames"],
                new_frames
            )

            self._append_unique(
                session[
                    "first_fault_frames"
                ],
                new_frames
            )

            self._append_unique(
                session[
                    "recent_fault_frames"
                ],
                new_frames
            )

            session[
                "last_video_time"
            ] = new_frames[-1][0]

        new_audio = (
            self.audio_buffer.get_chunks(
                start_time=(
                    session[
                        "last_audio_time"
                    ]
                    + 0.000001
                ),
                end_time=end_time
            )
        )

        if new_audio:

            self._append_unique(
                session["fault_audio"],
                new_audio
            )

            self._append_unique(
                session[
                    "first_fault_audio"
                ],
                new_audio
            )

            self._append_unique(
                session[
                    "recent_fault_audio"
                ],
                new_audio
            )

            session[
                "last_audio_time"
            ] = new_audio[-1][0]

        first_end = (
            session["failure_start"]
            + 5.0
        )

        session[
            "first_fault_frames"
        ] = [
            item
            for item in session[
                "first_fault_frames"
            ]
            if item[0] <= first_end
        ]

        session[
            "first_fault_audio"
        ] = [
            item
            for item in session[
                "first_fault_audio"
            ]
            if item[0] <= first_end
        ]

        session[
            "recent_fault_frames"
        ] = self._keep_recent(
            session[
                "recent_fault_frames"
            ],
            self.RECENT_FAULT_SECONDS,
            end_time
        )

        session[
            "recent_fault_audio"
        ] = self._keep_recent(
            session[
                "recent_fault_audio"
            ],
            self.RECENT_FAULT_SECONDS,
            end_time
        )

        elapsed = (
            end_time
            - session["failure_start"]
        )

        if elapsed >= 10.0:

            session["fault_frames"] = []
            session["fault_audio"] = []

    def _recover_session(
        self,
        event
    ):

        session = self.sessions.get(
            event["type"]
        )

        if session is None:
            return

        recovery_time = float(
            event["ended_timestamp"]
        )

        self._append_fault_data(
            session,
            recovery_time
        )

        duration = float(
            event["duration_seconds"]
        )

        pre_duration = min(
            self.PRE_BUFFER_SECONDS,
            self._media_duration(
                session["pre_frames"]
            )
        )

        missing_pre_seconds = max(
            0.0,
            self.PRE_BUFFER_SECONDS
            - pre_duration
        )

        if duration < 10.0:

            # Caso defensivo: si algún detector confirma un evento
            # menor de 10 segundos, se conserva toda la falla y se
            # completa el clip de 30 segundos con video posterior.
            post_seconds = max(
                self.POST_BUFFER_SECONDS,
                self.TARGET_CLIP_SECONDS
                - pre_duration
                - duration
            )

        else:

            post_seconds = (
                self.POST_BUFFER_SECONDS
                + missing_pre_seconds
            )

        session["event"] = event

        session[
            "recovered_timestamp"
        ] = recovery_time

        session["post_deadline"] = (
            recovery_time
            + post_seconds
        )

        session["post_seconds"] = (
            post_seconds
        )

        if missing_pre_seconds > 0.05:

            print(
                "[EVENT CLIP MANAGER] "
                "Prebuffer incompleto: "
                f"{pre_duration:.2f}s; "
                "se compensará con "
                f"{post_seconds:.2f}s posteriores"
            )

    def update(
        self,
        now
    ):

        for session in (
            self.sessions.values()
        ):

            if (
                session[
                    "recovered_timestamp"
                ]
                is None
            ):

                self._append_fault_data(
                    session,
                    now
                )

        self._finalize_ready_sessions(
            now
        )

    def _finalize_ready_sessions(
        self,
        now
    ):

        completed = []

        for event_type, session in (
            list(
                self.sessions.items()
            )
        ):

            deadline = session.get(
                "post_deadline"
            )

            if deadline is None:
                continue

            if now < deadline:
                continue

            recovery_time = float(
                session[
                    "recovered_timestamp"
                ]
            )

            post_frames = (
                self.video_buffer.get_frames(
                    start_time=recovery_time,
                    end_time=deadline
                )
            )

            post_audio = (
                self.audio_buffer.get_chunks(
                    start_time=recovery_time,
                    end_time=deadline
                )
            )

            self.encoding_queue.put(
                (
                    session,
                    post_frames,
                    post_audio
                )
            )

            print(
                "[EVENT CLIP MANAGER] "
                "Clip enviado a codificación "
                "en segundo plano: "
                f"{session['event']['id']}"
            )

            completed.append(
                event_type
            )

        for event_type in completed:

            self.sessions.pop(
                event_type,
                None
            )

    def _encoding_loop(self):

        while True:

            task = self.encoding_queue.get()

            try:

                session, post_frames, post_audio = (
                    task
                )

                self._encode_session(
                    session,
                    post_frames,
                    post_audio
                )

            except Exception as error:

                print(
                    "[EVENT CLIP MANAGER] "
                    "Error codificando clip: "
                    f"{error}"
                )

            finally:

                self.encoding_queue.task_done()

    def _encode_session(
        self,
        session,
        post_frames,
        post_audio
    ):

        result = self.builder.build(
            session=session,
            event=session["event"],
            post_frames=post_frames,
            post_audio=post_audio
        )

        effective_fps = float(
            result.get(
                "fps",
                self.fps
            )
        )

        clip_path = (
            self.recorder.save_clip(
                result["frames"],
                session[
                    "event"
                ]["folder"],
                fps=effective_fps,
                audio_chunks=
                    result["audio_chunks"],
                target_duration=
                    result["duration"]
            )
        )

        self.event_engine.attach_clip(
            session["event"],
            clip_path,
            result["mode"],
            result["duration"]
        )

        event_details = (
            session["event"][
                "details"
            ]
        )

        event_details[
            "expected_clip_duration_seconds"
        ] = result["duration"]

        event_details[
            "effective_video_fps"
        ] = round(
            effective_fps,
            4
        )

        timeline = result.get(
            "timeline",
            {}
        )

        event_details[
            "video_frame_count"
        ] = timeline.get(
            "frame_count",
            len(
                result["frames"]
            )
        )

        event_details[
            "video_first_timestamp"
        ] = timeline.get(
            "first_timestamp"
        )

        event_details[
            "video_last_timestamp"
        ] = timeline.get(
            "last_timestamp"
        )

        event_details[
            "video_captured_duration_seconds"
        ] = timeline.get(
            "captured_duration",
            0.0
        )

        self.event_engine.evidence.save_json(
            session["event"],
            session["event"]["id"]
        )

        print(
            "[EVENT CLIP MANAGER] "
            f"Clip finalizado: "
            f"{clip_path}"
        )

        print(
            "[EVENT CLIP MANAGER] "
            f"FPS efectivo: "
            f"{effective_fps:.4f}"
        )

        if self.completed_event_callback is not None:

            try:

                self.completed_event_callback(
                    session["event"]
                )

            except Exception as error:

                print(
                    "[EVENT CLIP MANAGER] "
                    "No se pudo encolar la "
                    "notificación final: "
                    f"{error}"
                )
