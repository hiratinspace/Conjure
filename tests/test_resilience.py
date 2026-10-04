import numpy as np
import pytest

import config
import main
from main import make_engine
from pipeline.frame_source import CameraError, FrameSource
from pipeline.injector import RecordingInjector
from pipeline.modes import HAND_LOST, Mode, ModeState
from pipeline.timing import StageTimer
from tests.synthetic import make_hand, stream
from tests.test_frame_source import FakeCapture, FakeClock

SCREEN = (1440, 900)


def test_a_failing_frame_is_recovered_not_raised():
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH))
    frames = stream([(0.3, dict(pinch=0.0, wrist=(0.4, 0.7))), (0.3, dict(pinch=0.95, wrist=(0.4, 0.7))),
                     (0.4, dict(pinch=0.95, wrist=lambda f: (0.4 + 0.15 * f, 0.7)))])
    for t, h in frames:
        engine.step(t, h)
    assert engine.actions.dragging  # mid-drag when the failure hits

    boom = make_hand()
    engine.pinch.update = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("detector exploded"))
    result = engine.step(frames[-1][0] + 0.033, boom)
    assert "frame error" in " ".join(result.lines)
    assert engine.frame_errors == 1
    assert injector.actions()[-1] == ("release", "left")  # the held button was let go
    assert not engine.actions.dragging


def test_errors_reset_after_a_good_frame():
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.DWELL))
    original = engine.dwell.update
    engine.dwell.update = lambda *a, **k: (_ for _ in ()).throw(ValueError("x"))
    engine.step(0.0, make_hand())
    assert engine.frame_errors == 1
    engine.dwell.update = original
    engine.step(0.033, make_hand())
    assert engine.frame_errors == 0


def test_camera_loss_is_retried_with_a_notice_and_a_pause(monkeypatch):
    """The camera dies after a few frames, then a fresh one works: the session continues."""
    sources = []
    frame = np.zeros((config.CAMERA_HEIGHT, config.CAMERA_WIDTH, 3), np.uint8)

    def fake_source(_camera):
        frames = [frame] * (3 if not sources else 5)
        src = FrameSource(0, 640, 480, 30, True, 0, 0.5, open_capture=lambda _i: FakeCapture(frames),
                          clock=FakeClock(1 / 30))
        sources.append(src)
        return src

    monkeypatch.setattr(main, "make_frame_source", fake_source)
    monkeypatch.setattr(config, "CAMERA_RETRY_S", 0.0)
    monkeypatch.setattr(config, "CAMERA_MAX_RETRIES", 2)
    modes = ModeState(Mode.PINCH)
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, modes)
    seen = []

    def on_frame(image, hand, result, fps):
        seen.append((image is None, modes.paused, engine.notice))
        return False

    args = type("A", (), {"replay": None, "record": None, "camera": 0})()
    with pytest.raises(CameraError):  # the third source also runs dry: retries exhausted, error surfaces
        main.run_pipeline(args, engine, StageTimer(33.0, 1e9), None, on_frame, lambda: False)
    assert len(sources) == 3  # first camera, two retries
    notices = [n for _, _, n in seen if n]
    assert notices and "Camera lost" in notices[0] and "Retrying" in notices[0]
    assert any(paused for img_none, paused, _ in seen if img_none)  # paused while the camera is gone
    assert sum(1 for img_none, _, _ in seen if not img_none) == 3 + 5 + 5  # frames from every camera ran
