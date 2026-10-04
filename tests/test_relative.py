import numpy as np
import pytest

import config
from main import make_engine, make_mouse_pointer
from pipeline.events import Action
from pipeline.injector import RecordingInjector
from pipeline.modes import Mode, ModeState
from pipeline.recorder import read_recording
from pipeline.timing import StageTimer
from tests.synthetic import stream

SCREEN = (1440, 900)
DT = 1 / 30


def test_resting_hand_leaves_the_cursor_still():
    """The user's real resting hand: still in most frames, a few pixels of wander in 16 s."""
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH), "mouse")
    _, frames = read_recording("recordings/idle.jsonl")
    t0 = frames[0][0]
    pts = [r.cursor for t, h in frames for r in [engine.step(t, h)] if r.cursor and t - t0 >= 14]
    pts = np.array(pts)
    still = np.mean(np.hypot(*np.diff(pts, axis=0).T) < 0.01)
    wander = np.hypot(*(pts.max(axis=0) - pts.min(axis=0)))
    assert still > 0.85 and wander < 15


def test_traversal_covers_the_whole_screen():
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH), "mouse")
    _, frames = read_recording("recordings/traversal_first.jsonl")
    pts = np.array([r.cursor for t, h in frames for r in [engine.step(t, h)] if r.cursor])
    assert pts[:, 0].min() == 0 and pts[:, 0].max() == SCREEN[0] - 1
    assert pts[:, 1].min() == 0 and pts[:, 1].max() == SCREEN[1] - 1


def test_acceleration_slow_moves_are_scaled_down_fast_moves_up():
    p = make_mouse_pointer(SCREEN)
    assert p.gain(config.MOUSE_DEAD_SPEED / 2) == 0.0
    assert p.gain(config.MOUSE_SLOW_SPEED) == pytest.approx(config.MOUSE_LOW_GAIN)
    assert p.gain(config.MOUSE_FAST_SPEED * 2) == pytest.approx(config.MOUSE_HIGH_GAIN)
    speeds = np.linspace(0, 3000, 50)
    gains = [p.gain(s) for s in speeds]
    assert all(b >= a for a, b in zip(gains, gains[1:]))


def test_same_hand_distance_moves_the_cursor_further_when_fast():
    def travel(seconds):
        p = make_mouse_pointer(SCREEN)
        n = round(seconds / DT)
        for i in range(n + 15):
            x = 300 + 200 * min(1.0, i / n)  # 200 base px of hand travel
            out = p.update((x, 400), i * DT)
        return out[0] - SCREEN[0] / 2 + 1
    assert travel(0.15) > 2 * travel(1.5)


def test_lifting_the_hand_keeps_the_cursor_and_reentry_does_not_jump():
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH), "mouse")
    frames = stream([(0.5, dict(wrist=(0.3, 0.7))), (0.6, dict(wrist=lambda f: (0.3 + 0.2 * f, 0.7))),
                     (0.6, None), (0.6, dict(wrist=(0.8, 0.5)))])  # hand comes back somewhere else
    results = [engine.step(t, h) for t, h in frames]
    before = results[32].cursor
    after = [r.cursor for r in results[-15:]]
    assert all(np.hypot(c[0] - before[0], c[1] - before[1]) < 5 for c in after)


def test_sensitivity_scales_the_mouse_gain():
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH), "mouse")
    engine.set_sensitivity(2.0)
    assert engine.filter.gain(config.MOUSE_SLOW_SPEED) == pytest.approx(2 * config.MOUSE_LOW_GAIN)


def test_switching_pointer_style_keeps_sensitivity_and_both_work():
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH), "mouse")
    engine.set_sensitivity(1.5)
    engine.set_pointer_style("direct")
    assert engine.mapper.calibration.sensitivity == 1.5
    engine.set_pointer_style("mouse")
    assert engine.filter.sensitivity == 1.5


@pytest.mark.parametrize("name,minimum", [("lab-20261004-010742", 38), ("lab-20261003-235641", 30)])
def test_real_pinches_still_click_with_mouse_pointing(name, minimum):
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH), "mouse")
    _, frames = read_recording(f"recordings/{name}.jsonl")
    clicks = [e for t, h in frames for e in engine.step(t, h).events
              if e.action in (Action.LEFT, Action.RIGHT, Action.DRAG_START)]
    assert len(clicks) >= minimum


@pytest.mark.parametrize("name", ["traversal_first", "exits", "idle"])
def test_mouse_pointing_keeps_zero_false_clicks(name):
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH), "mouse")
    _, frames = read_recording(f"recordings/{name}.jsonl")
    assert [e for t, h in frames for e in engine.step(t, h).events] == []
