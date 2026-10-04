import pytest

import config
from main import make_engine, make_scroll
from pipeline.events import Action
from pipeline.hand_pose import analyze
from pipeline.injector import RecordingInjector
from pipeline.modes import Mode, ModeState
from pipeline.recorder import read_recording
from pipeline.timing import StageTimer
from tests.synthetic import make_hand, stream

ASPECT = config.CAMERA_WIDTH / config.CAMERA_HEIGHT
DT = 1 / 30


def run(frames, mode=Mode.PINCH):
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), (1440, 900), ModeState(mode))
    results = [engine.step(t, h) for t, h in frames]
    return [e for r in results for e in r.events], injector, results


def drive(scroll, frames):
    events = []
    for t, hand in frames:
        events += scroll.update(hand, analyze(hand, ASPECT, 0.03) if hand else None, t, (700, 450))
    return events


def total(events):
    return sum(e.amount for e in events if e.action == Action.SCROLL)


def v_then(offset_hand_sizes, seconds=1.0, scale=0.15):
    """Enter the V pose at wrist y=0.7, then hold it offset_hand_sizes higher (positive = up)."""
    y = 0.7 - offset_hand_sizes * scale
    return stream([(0.4, dict(v_pose=True, wrist=(0.5, 0.7), scale=scale)),
                   (seconds, dict(v_pose=True, wrist=(0.5, y), scale=scale))])


def test_hand_above_center_scrolls_up_and_below_scrolls_down():
    assert total(drive(make_scroll(), v_then(+0.6))) > 0
    assert total(drive(make_scroll(), v_then(-0.6))) < 0


def test_dead_zone_does_not_scroll():
    assert drive(make_scroll(), v_then(+0.1)) == []


def test_rate_grows_with_distance_and_is_capped():
    slow = total(drive(make_scroll(), v_then(+0.4)))
    fast = total(drive(make_scroll(), v_then(+1.0)))
    huge = total(drive(make_scroll(), v_then(+5.0)))
    assert 0 < slow < fast
    assert huge <= config.SCROLL_MAX_RATE * 1.0 + 1


def test_rate_is_the_same_at_any_distance_from_the_camera():
    near = total(drive(make_scroll(), v_then(+0.8, scale=0.25)))
    far = total(drive(make_scroll(), v_then(+0.8, scale=0.10)))
    assert near == pytest.approx(far, abs=2)


def test_pose_must_be_held_before_scrolling_starts():
    frames = stream([(0.1, dict(v_pose=True, wrist=(0.5, 0.7))), (0.5, dict(wrist=(0.5, 0.6)))])
    assert drive(make_scroll(), frames) == []


def test_open_hand_and_fist_never_scroll():
    assert drive(make_scroll(), stream([(2.0, dict(wrist=lambda f: (0.5, 0.75 - 0.2 * f)))])) == []
    assert drive(make_scroll(), stream([(2.0, dict(curled=True, wrist=lambda f: (0.5, 0.75 - 0.2 * f)))])) == []


def test_engine_freezes_the_cursor_while_scrolling():
    frames = v_then(+0.8, seconds=1.0)
    events, injector, results = run(frames)
    assert total(events) > 0
    moves = [c for c in injector.calls if c[0] == "move"]
    frozen_from = len(frames) - 30  # scrolling started after the 0.2 s hold, well before this
    assert all(r.cursor == results[frozen_from].cursor for r in results[frozen_from:])
    assert len(moves) < 20  # moves happen only before the pose is held long enough


def test_scroll_works_in_dwell_mode_and_does_not_dwell_click():
    events, _, _ = run(v_then(+0.8, seconds=3.0), mode=Mode.DWELL)
    assert total(events) > 0
    assert not [e for e in events if e.action == Action.LEFT]


def test_scroll_starting_on_the_first_frame_does_not_crash():
    events, _, _ = run(stream([(1.0, dict(v_pose=True, wrist=(0.5, 0.6)))]))
    assert events == []


@pytest.mark.parametrize("name", ["traversal_first", "traversal", "idle", "exits"])
def test_recorded_sessions_never_scroll(name):
    _, frames = read_recording(f"recordings/{name}.jsonl")
    events, _, _ = run(frames)
    assert [e for e in events if e.action == Action.SCROLL] == []
