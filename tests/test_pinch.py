import pytest

import config
from main import make_engine
from pipeline.events import Action
from pipeline.injector import ClickCounter, RecordingInjector
from pipeline.modes import USER, Mode, ModeState
from pipeline.recorder import read_recording
from pipeline.timing import StageTimer
from tests.synthetic import stream

SCREEN = (1440, 900)


def run(frames, mode=Mode.PINCH):
    injector = RecordingInjector()
    modes = ModeState(mode)
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, modes)
    results = [engine.step(t, hand) for t, hand in frames]
    events = [e for r in results for e in r.events]
    return events, injector, results, engine


def ramp(a, b):
    return lambda f: a + (b - a) * f


def pinch_stream(hold_s, open_s=0.5, close_s=0.1, **hand):
    return stream([
        (open_s, dict(pinch=0.0, **hand)),
        (close_s, dict(pinch=ramp(0.0, 0.95), **hand)),
        (hold_s, dict(pinch=0.95, **hand)),
        (0.1, dict(pinch=ramp(0.95, 0.0), **hand)),
        (open_s, dict(pinch=0.0, **hand)),
    ])


def test_held_pinch_fires_exactly_one_left_click_on_release():
    events, injector, _, _ = run(pinch_stream(hold_s=0.3))
    assert [e.action for e in events] == [Action.LEFT]
    assert injector.actions() == [("click", "left", 1)]


def test_blip_shorter_than_hold_fires_nothing():
    events, _, _, _ = run(pinch_stream(hold_s=0.05, close_s=0.03))
    assert events == []


def test_click_lands_at_the_pre_pinch_position():
    # The knuckle drifts 3% of the frame (~60 px) while the fingers close; the click must land
    # where the cursor was before, and that drift must not count as a drag.
    frames = stream([
        (0.6, dict(pinch=0.0, wrist=(0.5, 0.7))),
        (0.15, dict(pinch=ramp(0.0, 0.95), wrist=lambda f: (0.5 + 0.03 * f, 0.7))),
        (0.3, dict(pinch=0.95, wrist=(0.53, 0.7))),
        (0.1, dict(pinch=ramp(0.95, 0.0), wrist=(0.53, 0.7))),
    ])
    events, _, results, _ = run(frames)
    pre_pinch = results[18].cursor  # last frame before the fingers started closing
    assert len(events) == 1
    assert events[0].position == pytest.approx(pre_pinch, abs=1.0)
    assert results[-1].cursor[0] > events[0].position[0] + 5  # the cursor itself did move


def test_hysteresis_does_not_double_fire_on_a_wobbling_pinch():
    # Ratio wobbles between engage (0.20) and release (0.32) while held: still exactly one click.
    wobble = lambda f: 0.85 - 0.1 * ((f * 10) % 1 > 0.5)  # pinch 0.85/0.75 = ratio ~0.18/~0.30
    frames = stream([(0.5, dict(pinch=0.0)), (0.6, dict(pinch=wobble)), (0.5, dict(pinch=0.0))])
    events, _, _, _ = run(frames)
    assert [e.action for e in events] == [Action.LEFT]


def test_curled_hand_never_pinches():
    frames = stream([(0.5, dict(curled=True)), (1.0, dict(curled=True, pinch=0.95)), (0.5, dict(curled=True))])
    events, _, _, _ = run(frames)
    assert events == []


def test_fingertips_at_frame_edge_never_pinch():
    edge = dict(wrist=(0.1, 0.7))  # thumb and pinch point sit at the left edge of the frame
    events, _, _, _ = run(pinch_stream(hold_s=0.4, **edge))
    assert events == []


def test_hand_lost_mid_pinch_cancels_without_clicking():
    frames = stream([(0.5, dict(pinch=0.0)), (0.4, dict(pinch=0.95)), (0.5, None), (0.5, dict(pinch=0.0))])
    events, _, _, _ = run(frames)
    assert events == []


def test_pinch_and_move_drags_then_releases_where_the_pinch_opens():
    frames = stream([
        (0.5, dict(pinch=0.0, wrist=(0.4, 0.7))),
        (0.3, dict(pinch=0.95, wrist=(0.4, 0.7))),
        (0.6, dict(pinch=0.95, wrist=ramp_point((0.4, 0.7), (0.6, 0.6)))),
        (0.2, dict(pinch=0.0, wrist=(0.6, 0.6))),
    ])
    events, injector, results, _ = run(frames)
    assert [e.action for e in events] == [Action.DRAG_START, Action.DRAG_END]
    assert events[1].position[0] > events[0].position[0] + 100
    assert injector.actions() == [("press", "left"), ("release", "left")]


def ramp_point(a, b):
    return lambda f: (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def test_middle_finger_pinch_is_a_right_click():
    events, injector, _, _ = run(pinch_stream(hold_s=0.3, finger="middle"))
    assert [e.action for e in events] == [Action.RIGHT]
    assert injector.actions() == [("click", "right", 1)]


def test_pinch_does_nothing_in_dwell_mode_or_while_paused():
    assert run(pinch_stream(hold_s=0.3), mode=Mode.DWELL)[0] == []
    frames = pinch_stream(hold_s=0.3)
    injector = RecordingInjector()
    modes = ModeState(Mode.PINCH)
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, modes)
    modes.pause(USER)  # paused from the panel: a visible hand must not resume it
    for t, hand in frames:
        engine.step(t, hand)
    assert injector.calls == []


def test_switching_mode_mid_drag_releases_the_button():
    injector = RecordingInjector()
    modes = ModeState(Mode.PINCH)
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, modes)
    frames = stream([(0.5, dict(pinch=0.0, wrist=(0.4, 0.7))), (0.3, dict(pinch=0.95, wrist=(0.4, 0.7))),
                     (0.4, dict(pinch=0.95, wrist=ramp_point((0.4, 0.7), (0.6, 0.7))))])
    for t, hand in frames:
        engine.step(t, hand)
    assert ("press", "left") in injector.actions()
    modes.set_click_mode(Mode.DWELL)
    engine.step(frames[-1][0] + 0.033, frames[-1][1])
    assert injector.actions()[-1] == ("release", "left")


def test_two_quick_pinches_count_as_a_double_click():
    counter = ClickCounter(config.DOUBLE_CLICK_INTERVAL_S, config.DOUBLE_CLICK_RADIUS_PX)
    assert counter.register("left", 0.0, (100, 100)) == 1
    assert counter.register("left", 0.3, (103, 101)) == 2
    assert counter.register("left", 0.5, (103, 101)) == 3
    assert counter.register("left", 2.0, (103, 101)) == 1  # too slow
    assert counter.register("left", 2.2, (200, 101)) == 1  # moved too far
    assert counter.register("right", 2.3, (200, 101)) == 1  # other button


@pytest.mark.parametrize("name", ["traversal_first", "traversal", "idle", "exits"])
def test_recorded_sessions_without_pinching_fire_zero_clicks(name):
    """Build-plan validation row: 60 s full-screen traversal with no pinch intended -> 0 false clicks."""
    _, frames = read_recording(f"recordings/{name}.jsonl")
    events, injector, _, _ = run(frames)
    assert events == []
    assert injector.actions() == []


def test_a_natural_quick_pinch_now_clicks():
    # ~100 ms closed: thrown away as a blip under the old 150 ms hold.
    events, _, _, _ = run(pinch_stream(hold_s=0.1, close_s=0.07))
    assert [e.action for e in events] == [Action.LEFT]


def test_no_pinch_starts_while_the_hand_sweeps_fast():
    frames = stream([(0.5, dict(pinch=0.0, wrist=(0.2, 0.7))),
                     (0.5, dict(pinch=lambda f: 0.95 if f > 0.2 else 0.0, wrist=lambda f: (0.2 + 0.5 * f, 0.7)))])
    events, _, results, _ = run(frames)
    assert events == []
    assert any("hold still" in " ".join(r.lines) for r in results)


def test_a_blocked_pinch_says_why_and_turns_the_dot_red():
    frames = stream([(0.5, dict(curled=True)), (0.5, dict(curled=True, pinch=0.95))])
    events, _, results, _ = run(frames)
    assert events == []
    assert results[-1].pinch_state == "blocked"
    assert any("open your other fingers" in line for line in results[-1].lines)
