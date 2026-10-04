import numpy as np

from pipeline.engine import StepResult
from pipeline.events import Action, ClickEvent
from pipeline.overlay import badge_text, ring_arc
from pipeline.ui_state import UiSnapshot, UiState
from tests.synthetic import make_hand


def test_ring_fills_clockwise_from_twelve_oclock():
    assert ring_arc(0.0) == (90.0, 0.0)
    assert ring_arc(0.5) == (90.0, -180.0)
    assert ring_arc(1.5) == (90.0, -360.0)


def test_status_pill_shows_tracking_state_and_mode():
    assert badge_text(UiSnapshot(mode="dwell", tracking="tracking")) == "Tracking  |  Dwell"
    assert badge_text(UiSnapshot(mode="paused", tracking="paused")) == "Paused"
    assert badge_text(UiSnapshot(mode="pinch")) == "Pinch"
    assert badge_text(UiSnapshot()) == ""


def test_engine_reports_pinch_progress_and_tracking_state():
    from main import make_engine
    from pipeline.injector import RecordingInjector
    from pipeline.modes import Mode, ModeState
    from pipeline.timing import StageTimer
    from tests.synthetic import stream

    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), (1440, 900), ModeState(Mode.PINCH))
    frames = stream([(0.3, dict(pinch=0.0)), (0.3, dict(pinch=lambda f: 0.9 * f)), (0.3, dict(pinch=0.95)),
                     (0.2, None)])
    results = [engine.step(t, h) for t, h in frames]
    progress = [r.pinch_progress for r in results[:27] if r.pinch_progress is not None]
    assert progress[0] == 0.0 and max(progress) == 1.0  # fills as the fingers close
    assert any(r.pinch_state == "confirmed" for r in results)
    assert results[0].tracking == "tracking" and results[-1].tracking == "no hand"


def test_publish_annotates_preview_only_while_visible():
    ui = UiState()
    frame = np.zeros((480, 640, 3), np.uint8)
    result = StepResult(cursor=(1, 2), lines=["x"])
    ui.publish(frame, make_hand(), result, 30.0, "pinch")
    assert ui.snapshot().preview is None
    ui.preview_visible = True
    ui.publish(frame, make_hand(), result, 30.0, "pinch")
    snap = ui.snapshot()
    assert snap.preview is not None and snap.preview.any()
    assert not frame.any()  # the camera frame itself is never drawn on
    assert snap.cursor == (1, 2) and snap.hand_visible and snap.mode == "pinch"


def test_events_are_drained_once():
    ui = UiState()
    event = ClickEvent(Action.LEFT, (0, 0))
    ui.publish(None, None, StepResult(events=[event]), 30.0, "pinch")
    assert ui.drain_events() == [event]
    assert ui.drain_events() == []
