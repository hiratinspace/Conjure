import numpy as np
import pytest

from pipeline.frame_source import CameraError, FpsCounter, FrameSource


class FakeCapture:
    def __init__(self, frames, opened=True):
        self.frames = list(frames)
        self.opened = opened
        self.props = {}
        self.released = False

    def isOpened(self):
        return self.opened

    def set(self, prop, value):
        self.props[prop] = value

    def get(self, prop):
        return self.props.get(prop, 0)

    def read(self):
        if not self.frames:
            return False, None
        return True, self.frames.pop(0)

    def release(self):
        self.released = True


class FakeClock:
    def __init__(self, step):
        self.t, self.step = 0.0, step

    def __call__(self):
        self.t += self.step
        return self.t


def make_source(capture, warmup=0, mirror=True, clock=None):
    return FrameSource(0, 640, 480, 30, mirror, warmup, 0.5,
                       open_capture=lambda _i: capture, clock=clock or FakeClock(1 / 30))


def gradient_frame():
    frame = np.zeros((2, 3, 3), np.uint8)
    frame[:, :, 0] = [10, 20, 30]  # left-to-right ramp in the blue channel
    return frame


def test_read_mirrors_frame_horizontally():
    src = make_source(FakeCapture([gradient_frame()])).open()
    frame, _ = src.read()
    assert list(frame[0, :, 0]) == [30, 20, 10]


def test_read_without_mirror_keeps_orientation():
    src = make_source(FakeCapture([gradient_frame()]), mirror=False).open()
    frame, _ = src.read()
    assert list(frame[0, :, 0]) == [10, 20, 30]


def test_warmup_frames_are_discarded():
    frames = [np.full((2, 2, 3), i, np.uint8) for i in range(4)]
    src = make_source(FakeCapture(frames), warmup=3, mirror=False).open()
    frame, _ = src.read()
    assert frame[0, 0, 0] == 3


def test_closed_camera_raises_with_permission_hint():
    with pytest.raises(CameraError, match="Privacy & Security > Camera"):
        make_source(FakeCapture([], opened=False)).open()


def test_camera_that_stops_delivering_raises():
    src = make_source(FakeCapture([])).open()
    with pytest.raises(CameraError):
        src.read()


def test_requests_resolution_and_fps():
    cap = FakeCapture([])
    make_source(cap).open()
    import cv2
    assert cap.props[cv2.CAP_PROP_FRAME_WIDTH] == 640
    assert cap.props[cv2.CAP_PROP_FRAME_HEIGHT] == 480
    assert cap.props[cv2.CAP_PROP_FPS] == 30


def test_fps_counter_converges_to_frame_rate():
    counter = FpsCounter(smoothing=0.2)
    for i in range(100):
        counter.tick(i / 30)
    assert counter.fps == pytest.approx(30, rel=1e-6)


def test_fps_counter_ignores_non_increasing_time():
    counter = FpsCounter(smoothing=0.2)
    counter.tick(1.0)
    counter.tick(1.0)
    assert counter.fps == 0.0


def test_context_manager_releases_camera():
    cap = FakeCapture([gradient_frame()])
    with make_source(cap) as src:
        src.read()
    assert cap.released
