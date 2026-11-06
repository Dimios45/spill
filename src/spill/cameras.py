from __future__ import annotations

import threading
import time

import numpy as np

from .types import CAMERAS, Frame, SafetyError


class Cameras:
    def __init__(self, serials, *, mock=False):
        self.serials, self.mock = serials, mock
        self.frames = {}
        self.intrinsics = {}
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.pipelines = []
        self.threads = []
        self.error = ""

    def start(self):
        if self.mock:
            self._spawn(self._mock)
            return
        import pyrealsense2 as rs
        from openpi_control.cameras import sdk_serial_for_asic

        try:
            for name in CAMERAS:
                pipe, config = rs.pipeline(), rs.config()
                # Match Karma's operator-facing ASIC serial convention.
                config.enable_device(sdk_serial_for_asic(self.serials[name]))
                config.enable_stream(rs.stream.color, 848, 480, rs.format.rgb8, 30)
                profile = pipe.start(config)
                self.pipelines.append(pipe)
                intr = (
                    profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
                )
                self.intrinsics[name] = dict(
                    width=intr.width,
                    height=intr.height,
                    matrix=[[intr.fx, 0, intr.ppx], [0, intr.fy, intr.ppy], [0, 0, 1]],
                    distortion=list(intr.coeffs),
                    model=str(intr.model),
                )
                self._spawn(self._capture, name, pipe)
        except BaseException:
            self.close()
            raise

    def _spawn(self, function, *args):
        thread = threading.Thread(target=function, args=args, daemon=True)
        thread.start()
        self.threads.append(thread)

    def _capture(self, name, pipe):
        previous = -1
        try:
            while not self.stop_event.is_set():
                try:
                    frames = pipe.wait_for_frames(timeout_ms=300)
                except RuntimeError:
                    continue  # stale timestamps cause the supervisor to stop
                frame = frames.get_color_frame()
                if not frame or frame.get_frame_number() <= previous:
                    continue
                previous = frame.get_frame_number()
                rgb = np.asanyarray(frame.get_data()).copy()
                rgb.flags.writeable = False
                with self.lock:
                    self.frames[name] = Frame(
                        rgb, time.monotonic(), previous, frame.get_timestamp()
                    )
        except Exception as exc:
            self.error = f"{name}: {type(exc).__name__}: {exc}"

    def _mock(self):
        import cv2

        seq = 0
        while not self.stop_event.is_set():
            now = time.monotonic()
            seq += 1
            frames = {}
            for i, name in enumerate(CAMERAS):
                rgb = np.full((480, 848, 3), 35 + i * 25, np.uint8)
                cv2.putText(
                    rgb,
                    f"MOCK / {name} / {seq}",
                    (30, 100),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (230, 230, 230),
                    2,
                )
                frames[name] = Frame(rgb, now, seq)
            with self.lock:
                self.frames = frames
            self.stop_event.wait(1 / 30)

    def latest(self):
        if self.error:
            raise SafetyError(self.error)
        with self.lock:
            return dict(self.frames)

    def wait_ready(self, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.latest()) == 3:
                return
            time.sleep(0.02)
        raise SafetyError("Three cameras did not become ready")

    def close(self):
        self.stop_event.set()
        for pipe in self.pipelines:
            try:
                pipe.stop()
            except Exception:
                pass
        for thread in self.threads:
            thread.join(timeout=1)
