# -*- coding: utf-8 -*-

"""Pipeline completo e independiente para una capturadora lógica."""

import threading
import time
from datetime import datetime

import cv2

from audio.audio_buffer import AudioBuffer
from audio.audio_monitor import AudioMonitor
from camera.buffer import VideoBuffer
from camera.camera import Camera
from camera.stream import CameraStream
from core.frame_context import FrameContext
from detectors.monitor_engine import MonitorEngine
from events.event_clip_manager import EventClipManager
from events.event_engine import EventEngine
from events.recorder import Recorder
from utils.video_watermark import VideoWatermark


class CapturePipeline:

    def __init__(
        self,
        capture_id,
        channel_config,
        hardware,
        dashboard,
        telegram_notifier,
        zabbix_notifier,
        width=1280,
        height=720,
        camera_fps=20.0,
        preview_fps=15.0,
        evidence_fps=10.0,
    ):
        self.capture_id = str(capture_id)
        self.channel_config = dict(channel_config)
        self.hardware = dict(hardware)
        self.dashboard = dashboard
        self.telegram_notifier = telegram_notifier
        self.zabbix_notifier = zabbix_notifier
        self.preview_fps = float(preview_fps)
        self.evidence_fps = float(evidence_fps)
        self.processing_fps = max(1.0, float(camera_fps))
        self.stop_event = threading.Event()
        self.preview_lock = threading.Lock()
        self.latest_preview_frame = None
        self.threads = []

        self.audio_buffer = AudioBuffer(
            seconds=40, sample_rate=48000, channels=2,
            sample_width=2, chunk_frames=2048,
        )
        self.audio_monitor = AudioMonitor(
            device=self.hardware["audio_device"],
            sample_rate=48000, channels=2, chunk_frames=2048,
            audio_buffer=self.audio_buffer,
        )
        self.dashboard.register_capture(self.capture_id, self.audio_monitor)

        self.watermark = self._watermark()
        self.preview_watermark = self._watermark()
        self.monitor = MonitorEngine(
            capture_id=self.capture_id,
            channel_id_event_callback=self._notify_channel_id,
        )
        self.event_engine = EventEngine(capture_id=self.capture_id)
        self.recorder = Recorder(sample_rate=48000, channels=2, sample_width=2)
        self.video_buffer = VideoBuffer(seconds=40, fps=self.evidence_fps)
        self.clip_manager = EventClipManager(
            video_buffer=self.video_buffer,
            audio_buffer=self.audio_buffer,
            recorder=self.recorder,
            event_engine=self.event_engine,
            fps=self.evidence_fps,
            completed_event_callback=self.telegram_notifier.notify_completed_event,
        )
        self.camera = Camera(
            self.hardware["video_device"], int(width), int(height), self.processing_fps
        )
        self.stream = CameraStream(self.camera)

    def _watermark(self):
        return VideoWatermark(
            station=self.channel_config.get("station_id", ""),
            channel_name=self.channel_config.get("channel_name", ""),
            channel_number=self.channel_config.get("channel_number", ""),
            location=self.channel_config.get("location", ""),
            margin_x=15,
            margin_y=15,
            opacity=0.68,
        )

    def _notify_channel_id(self, event):
        self.telegram_notifier.notify_channel_id_event(event)
        self.zabbix_notifier.notify_channel_id_event(event)

    def start(self):
        self.audio_monitor.start()
        self.stream.start()
        self.dashboard.set_capture_status(self.capture_id, "INICIANDO")
        self.threads = [
            threading.Thread(target=self._preview_loop, name=f"preview-{self.capture_id}", daemon=True),
            threading.Thread(target=self._evidence_loop, name=f"evidence-{self.capture_id}", daemon=True),
            threading.Thread(target=self._detector_loop, name=f"detectors-{self.capture_id}", daemon=True),
        ]
        for thread in self.threads:
            thread.start()
        print(
            f"[PIPELINE] {self.capture_id} iniciado "
            f"video={self.hardware['video_device']} audio={self.hardware['audio_device']} "
            f"hardware={self.hardware['hardware_id']}"
        )

    def _wait_deadline(self, deadline, interval):
        deadline += interval
        remaining = deadline - time.monotonic()
        if remaining > 0:
            self.stop_event.wait(remaining)
            return deadline
        return time.monotonic()

    def _preview_loop(self):
        interval = 1.0 / self.preview_fps
        deadline = time.monotonic()
        while not self.stop_event.is_set():
            frame = self.stream.read()
            if frame is None:
                self.dashboard.set_capture_status(self.capture_id, "SIN VIDEO")
                self.stop_event.wait(0.05)
                deadline = time.monotonic()
                continue
            try:
                preview = cv2.resize(frame, (640, 360))
                preview = self.preview_watermark.apply(preview, timestamp=datetime.now())
                self.dashboard.update_frame(self.capture_id, preview)
                with self.preview_lock:
                    self.latest_preview_frame = preview.copy()
            except Exception as error:
                print(f"[DASHBOARD PREVIEW] {self.capture_id}: {error}")
            deadline = self._wait_deadline(deadline, interval)

    def _evidence_loop(self):
        interval = 1.0 / self.evidence_fps
        deadline = time.monotonic()
        while not self.stop_event.is_set():
            with self.preview_lock:
                frame = (
                    self.latest_preview_frame.copy()
                    if self.latest_preview_frame is not None else None
                )
            if frame is not None:
                try:
                    self.video_buffer.add(frame)
                except Exception as error:
                    print(f"[EVIDENCE BUFFER] {self.capture_id}: {error}")
            deadline = self._wait_deadline(deadline, interval)

    def _detector_loop(self):
        interval = 1.0 / self.processing_fps
        deadline = time.monotonic()
        while not self.stop_event.is_set():
            frame = self.stream.read()
            if frame is None:
                self.stop_event.wait(0.02)
                deadline = time.monotonic()
                continue
            try:
                now = time.time()
                frame_datetime = datetime.now()
                small_clean = cv2.resize(frame, (640, 360))
                evidence_frame = self.watermark.apply(
                    small_clean.copy(), timestamp=frame_datetime
                )
                ia_frame = cv2.resize(frame, (416, 416))
                context = FrameContext(
                    camera=self.channel_config.get("channel_name", self.capture_id),
                    frame=frame,
                    small_frame=small_clean,
                    ia_frame=ia_frame,
                    detections=[],
                    timestamp=frame_datetime,
                    audio=self.audio_monitor.get_levels(),
                )
                context.detections = self.monitor.process(context)
                actions = self.event_engine.update(context.detections, evidence_frame)
                for action in actions:
                    self.dashboard.update_event(action["event"])
                    self.zabbix_notifier.notify_event_action(action)
                self.clip_manager.process_actions(actions, now)
                self.clip_manager.update(now)
                self.zabbix_notifier.update_capture_frame(self.capture_id)
            except Exception as error:
                print(f"[PIPELINE] Error en {self.capture_id}: {error}")
            deadline = self._wait_deadline(deadline, interval)

    def stop(self):
        self.stop_event.set()
        self.dashboard.set_capture_status(self.capture_id, "OFFLINE")
        for thread in self.threads:
            thread.join(timeout=2)
        self.audio_monitor.stop()
        self.stream.stop()
        self.camera.release()
        print(f"[PIPELINE] {self.capture_id} detenido")

