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


def test_badge_names_the_mode():
    assert badge_text(UiSnapshot(mode="dwell")) == "Conjure: dwell"
    assert badge_text(UiSnapshot()) == ""


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
