import pytest

import config
from main import make_engine
from pipeline.events import Action
from pipeline.injector import RecordingInjector
from pipeline.modes import Mode, ModeState
from pipeline.recorder import read_recording
from pipeline.timing import StageTimer
from pipeline.touch import straightness
from tests.synthetic import make_hand, stream

SCREEN = (1440, 900)
ASPECT = config.CAMERA_WIDTH / config.CAMERA_HEIGHT


def run(frames):
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.TOUCH))
    results = [engine.step(t, h) for t, h in frames]
    return [e for r in results for e in r.events], injector, results, engine


def ramp(a, b):
    return lambda f: a + (b - a) * f


def tap(hold_s=0.15, **hand):
    """Point, bend the index quickly, hold, straighten."""
    return [(0.08, dict(bend=ramp(0.0, 1.0), **hand)), (hold_s, dict(bend=1.0, **hand)),
            (0.08, dict(bend=ramp(1.0, 0.0), **hand))]


POINT = (0.6, dict(bend=0.0))


def test_straightness_separates_pointing_from_bent():
    assert straightness(make_hand(), ASPECT) > config.TOUCH_HOVER_STRAIGHTNESS
    assert straightness(make_hand(bend=1.0), ASPECT) < config.TOUCH_DOWN_STRAIGHTNESS


def test_tap_is_a_left_click_on_lift():
    events, injector, _, _ = run(stream([POINT, *tap(), POINT]))
    assert [e.action for e in events] == [Action.LEFT]
    assert injector.actions() == [("click", "left", 1)]


def test_tap_lands_where_the_finger_was_before_it_bent():
    frames = stream([(0.6, dict(wrist=(0.5, 0.7))),
                     (0.08, dict(bend=ramp(0, 1), wrist=lambda f: (0.5 + 0.004 * f, 0.7))),
                     (0.15, dict(bend=1.0, wrist=(0.504, 0.7))), (0.08, dict(bend=ramp(1, 0), wrist=(0.504, 0.7)))])
    events, _, results, _ = run(frames)
    assert events[0].position == pytest.approx(results[17].cursor, abs=1.0)


def test_two_taps_make_a_double_click():
    events, _, _, _ = run(stream([POINT, *tap(), (0.12, dict()), *tap(), POINT]))
    assert [e.action for e in events] == [Action.LEFT, Action.LEFT]  # ClickCounter makes it a double-click


def test_long_press_is_a_right_click_fired_once_while_held():
    events, _, results, _ = run(stream([POINT, *tap(hold_s=1.2), POINT]))
    assert [e.action for e in events] == [Action.RIGHT]
    assert any(r.dwell_progress and 0 < r.dwell_progress < 1 for r in results)  # the hold ring fills first


def test_press_hold_then_move_drags_and_lift_drops():
    frames = stream([(0.6, dict(wrist=(0.4, 0.7))), (0.08, dict(bend=ramp(0, 1), wrist=(0.4, 0.7))),
                     (0.3, dict(bend=1.0, wrist=(0.4, 0.7))),
                     (0.8, dict(bend=1.0, wrist=lambda f: (0.4 + 0.15 * f, 0.7))),
                     (0.1, dict(bend=ramp(1, 0), wrist=(0.55, 0.7)))])
    events, injector, _, _ = run(frames)
    assert [e.action for e in events] == [Action.DRAG_START, Action.DRAG_END]
    assert injector.actions() == [("press", "left"), ("release", "left")]


def test_a_touch_that_slides_before_settling_is_cancelled():
    frames = stream([(0.6, dict(wrist=(0.4, 0.7))), (0.08, dict(bend=ramp(0, 1), wrist=(0.4, 0.7))),
                     (0.15, dict(bend=1.0, wrist=lambda f: (0.4 + 0.15 * f, 0.7))),
                     (0.45, dict(bend=1.0, wrist=(0.55, 0.7))),
                     (0.1, dict(bend=ramp(1, 0), wrist=(0.55, 0.7)))])
    events, _, _, engine = run(frames)
    assert events == [] and engine.touch.blocked >= 1


def test_a_bend_while_the_hand_is_moving_fast_is_ignored():
    frames = stream([(0.6, dict(wrist=(0.3, 0.7))),
                     (0.4, dict(bend=lambda f: 1.0 if 0.3 < f < 0.8 else 0.0, wrist=lambda f: (0.3 + 0.3 * f, 0.7)))])
    events, _, _, _ = run(frames)
    assert events == []


def test_a_curled_hand_that_never_pointed_cannot_tap():
    frames = stream([(1.0, dict(bend=1.0)), (0.1, dict(bend=ramp(1, 0.2))), (0.1, dict(bend=ramp(0.2, 1)))])
    events, _, _, _ = run(frames)
    assert events == []


def test_tremor_blip_is_not_a_tap():
    frames = stream([POINT, (0.03, dict(bend=1.0)), POINT])
    events, _, _, _ = run(frames)
    assert events == []


def test_losing_the_hand_mid_drag_drops_it():
    frames = stream([(0.6, dict(wrist=(0.4, 0.7))), (0.08, dict(bend=ramp(0, 1), wrist=(0.4, 0.7))),
                     (0.3, dict(bend=1.0, wrist=(0.4, 0.7))),
                     (0.6, dict(bend=1.0, wrist=lambda f: (0.4 + 0.15 * f, 0.7))), (0.5, None)])
    events, injector, _, _ = run(frames)
    assert [e.action for e in events] == [Action.DRAG_START, Action.DRAG_END]
    assert injector.actions()[-1] == ("release", "left")


@pytest.mark.parametrize("name", ["traversal_first", "traversal", "idle", "exits"])
def test_ordinary_movement_never_taps_or_drags(name):
    """Before the stillness and press-then-move rules, traversal gave 2 false clicks and 3 drags, exits 5 drags."""
    _, frames = read_recording(f"recordings/{name}.jsonl")
    events, injector, _, _ = run(frames)
    assert events == [] and injector.actions() == []
