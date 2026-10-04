import pytest

from main import make_engine
from pipeline.dwell import DwellDetector
from pipeline.events import Action
from pipeline.injector import RecordingInjector
from pipeline.modes import Mode, ModeState
from pipeline.recorder import read_recording
from pipeline.timing import StageTimer
from tests.synthetic import stream

DT = 1 / 30


def feed(detector, points, t0=0.0):
    events = []
    for i, p in enumerate(points):
        events += detector.update(p, t0 + i * DT)
    return events


def test_staying_still_fires_exactly_one_click_after_the_dwell_time():
    d = DwellDetector(dwell_s=1.0, radius_px=30)
    feed(d, [(100, 100), (200, 100)])  # arrive: moving out of the first circle arms it
    events = feed(d, [(200, 100)] * 90, t0=2 * DT)  # then 3 s of stillness
    assert [e.action for e in events] == [Action.LEFT]


def test_click_fires_on_time_and_progress_rises_before_it():
    d = DwellDetector(dwell_s=1.0, radius_px=30)
    feed(d, [(100, 100), (200, 100)])
    progress = []
    for i in range(40):
        events = d.update((200, 100), (2 + i) * DT)
        progress.append(d.progress)
        if events:
            break
    assert i in (29, 30)  # 1.0 s after the anchor at frame 1 (+-1 frame of float rounding)
    assert progress[0] < progress[10] < progress[20] < 1.0


def test_jitter_inside_the_radius_still_counts_as_still():
    d = DwellDetector(dwell_s=1.0, radius_px=30)
    feed(d, [(100, 100), (200, 100)])
    wobble = [(200 + (i % 3) * 8, 100 - (i % 2) * 8) for i in range(40)]
    assert len(feed(d, wobble, t0=2 * DT)) == 1


def test_moving_out_of_the_radius_restarts_the_countdown():
    d = DwellDetector(dwell_s=1.0, radius_px=30)
    feed(d, [(100, 100), (200, 100)])
    feed(d, [(200, 100)] * 20, t0=2 * DT)  # 0.67 s
    assert feed(d, [(300, 100)] * 20, t0=22 * DT) == []  # moved: starts over, not yet 1 s


def test_must_move_out_and_back_before_the_next_click():
    d = DwellDetector(dwell_s=0.5, radius_px=30)
    feed(d, [(100, 100), (200, 100)])
    first = feed(d, [(200, 100)] * 200, t0=2 * DT)  # stay still for ~6.7 s
    assert len(first) == 1
    feed(d, [(260, 100)], t0=210 * DT)  # move away
    again = feed(d, [(260, 100)] * 30, t0=211 * DT)
    assert len(again) == 1


def test_reset_disarms_so_reentry_never_clicks_by_itself():
    d = DwellDetector(dwell_s=0.5, radius_px=30)
    feed(d, [(100, 100), (200, 100)])
    d.reset()
    assert feed(d, [(500, 500)] * 60, t0=1.0) == []


def test_configure_live_applies():
    d = DwellDetector(dwell_s=1.0, radius_px=30)
    d.configure(dwell_s=2.0, radius_px=10)
    assert (d.dwell_s, d.radius_px) == (2.0, 10)


def run_engine(frames, mode=Mode.DWELL):
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), (1440, 900), ModeState(mode))
    results = [engine.step(t, h) for t, h in frames]
    return [e for r in results for e in r.events], results


def test_engine_dwell_mode_clicks_and_reports_ring_progress():
    frames = stream([(0.5, dict(wrist=lambda f: (0.4 + 0.2 * f, 0.7))), (2.5, dict(wrist=(0.6, 0.7)))])
    events, results = run_engine(frames)
    assert [e.action for e in events] == [Action.LEFT]
    assert any(r.dwell_progress and 0 < r.dwell_progress < 1 for r in results)


def test_engine_hand_loss_cancels_a_dwell_in_progress():
    frames = stream([(0.5, dict(wrist=lambda f: (0.4 + 0.2 * f, 0.7))), (0.6, dict(wrist=(0.6, 0.7))),
                     (0.5, None), (2.0, dict(wrist=(0.6, 0.7)))])
    events, _ = run_engine(frames)
    assert events == []


def test_idle_recording_in_dwell_mode_clicks_once_per_arrival():
    """A resting hand in dwell mode clicks when it settles, then never again without moving:
    between two dwell clicks the cursor always left the dwell circle of the first."""
    import math

    import config
    _, frames = read_recording("recordings/idle.jsonl")
    events, results = run_engine(frames)
    assert 1 <= len(events) <= 5
    click_frames = [i for i, r in enumerate(results) if r.events]
    for a, b in zip(click_frames, click_frames[1:]):
        origin = results[a].events[0].position
        assert any(r.cursor and math.dist(r.cursor, origin) > config.DWELL_RADIUS_PX for r in results[a:b])


def test_slow_drift_after_a_click_does_not_click_the_same_target_again():
    # Dwell starts at x=200, the cursor creeps right inside the circle until it clicks near x=220,
    # then keeps creeping a few pixels: it must not re-arm until it is a full radius from the click.
    d = DwellDetector(dwell_s=0.5, radius_px=25)
    feed(d, [(100, 100), (200, 100)])
    creep = [(200 + i * 0.5, 100) for i in range(120)]  # 0.5 px per frame: 60 px over 4 s
    events = []
    for i, p in enumerate(creep):
        events += d.update(p, (2 + i) * DT)
    clicks = [e.position[0] for e in events]
    assert all(b - a > 25 for a, b in zip(clicks, clicks[1:]))
