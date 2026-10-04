"""CONJ-3: webcam capture.

FrameSource owns the camera and hands out (frame, timestamp) pairs. Timestamps
come from time.monotonic() at read time and are the clock every downstream
stage uses. Frames are mirrored here, once, so the whole pipeline works in
selfie coordinates.
"""

import logging
import time

import cv2

log = logging.getLogger("conjure.camera")


class CameraError(RuntimeError):
    pass


class FpsCounter:
    """Exponential moving average of the frame rate."""

    def __init__(self, smoothing):
        self.smoothing = smoothing
        self.fps = 0.0
        self._last = None

    def tick(self, t):
        if self._last is not None and t > self._last:
            instant = 1.0 / (t - self._last)
            self.fps = instant if self.fps == 0.0 else self.fps + self.smoothing * (instant - self.fps)
        self._last = t
        return self.fps


def _open_avfoundation(index):
    return cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)


class FrameSource:
    def __init__(self, index, width, height, fps, mirror, warmup_frames, fps_smoothing,
                 open_capture=_open_avfoundation, clock=time.monotonic):
        self.index = index
        self.width = width
        self.height = height
        self.target_fps = fps
        self.mirror = mirror
        self.warmup_frames = warmup_frames
        self.fps_counter = FpsCounter(fps_smoothing)
        self._open_capture = open_capture
        self._clock = clock
        self._cap = None
        self.frames = 0  # frames delivered since open()

    @property
    def fps(self):
        return self.fps_counter.fps

    def open(self):
        cap = self._open_capture(self.index)
        if not cap.isOpened():
            raise CameraError(
                f"camera {self.index} did not open. Check System Settings > Privacy & Security > Camera "
                "for this terminal app, and that no other app is using the camera."
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.target_fps)
        self._cap = cap
        # The first frames after opening are often black or mid auto-exposure.
        for _ in range(self.warmup_frames):
            cap.read()
        actual = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        log.info("camera %d open at %dx%d (requested %dx%d @ %d fps)",
                 self.index, actual[0], actual[1], self.width, self.height, self.target_fps)
        return self

    def read(self):
        """Block for the next frame. Returns (frame_bgr, timestamp) or raises CameraError."""
        if self._cap is None:
            raise CameraError("FrameSource.read() before open()")
        ok, frame = self._cap.read()
        t = self._clock()
        if not ok or frame is None:
            raise CameraError("camera stopped delivering frames (unplugged, or permission revoked?)")
        if self.mirror:
            frame = cv2.flip(frame, 1)
        self.fps_counter.tick(t)
        self.frames += 1
        return frame, t

    def close(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
