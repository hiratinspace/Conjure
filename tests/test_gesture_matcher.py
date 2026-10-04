import random

import numpy as np
import pytest

import config
from main import make_engine, make_gesture_matcher, make_gesture_recorder, make_pointer_filter
from pipeline.events import Action
from pipeline.injector import RecordingInjector
from pipeline.modes import Mode, ModeState
from pipeline.profile_schema import GestureTemplate
from pipeline.recorder import read_recording
from pipeline.timing import StageTimer
from tests.synthetic import make_hand, stream
from tests.test_gestures import OPEN, curl_points, recorder_frames

SCREEN = (1440, 900)


def recorded_curl_template(name="Illuminate"):
    rec = make_gesture_recorder()
    rec.start()
    for t, h in recorder_frames([curl_points] * 3):
        rec.update(h, t)
    samples, threshold, _ = rec.result()
    return GestureTemplate(name=name, samples=samples, threshold=threshold)


def noisy(points, rng, amount):
    return [(x + rng.gauss(0, amount), y + rng.gauss(0, amount)) for x, y in points]


def cast(duration, rng=None, noise=0.0, wrist=(0.5, 0.7)):
    """One cast of the curl gesture lasting `duration` seconds."""
    def pts(f):
        p = curl_points(f)
        return noisy(p, rng, noise) if rng else p
    return (duration, dict(points=pts, wrist=wrist))


def run_engine(frames, template):
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.CUSTOM))
    engine.set_gestures([template])
    results = [engine.step(t, h) for t, h in frames]
    return [(r, e) for r in results for e in r.events], results


def test_cast_fires_one_click_within_500ms_of_finishing():
    template = recorded_curl_template()
    frames = stream([(1.0, dict(points=OPEN)), cast(0.8), (1.5, dict(points=OPEN))])
    fired, results = run_engine(frames, template)
    assert len(fired) == 1
    gesture_end = 1.0 + 0.8
    t_fire = frames[[i for i, r in enumerate(results) if r.events][0]][0]
    assert t_fire - gesture_end <= 0.5
    assert fired[0][0].spell == "Illuminate"
    assert fired[0][1].action == Action.LEFT


def test_at_least_8_of_10_varied_casts_fire():
    """Build-plan validation row: 10 casts -> >= 8 fire within 500 ms (speed and noise vary)."""
    template = recorded_curl_template()
    rng = random.Random(7)
    hits = 0
    for i in range(10):
        duration = rng.uniform(0.6, 1.1)
        wrist = (rng.uniform(0.3, 0.7), rng.uniform(0.5, 0.8))
        frames = stream([(1.0, dict(points=OPEN, wrist=wrist)), cast(duration, rng, 0.03, wrist),
                         (0.5, dict(points=OPEN, wrist=wrist))])
        fired, results = run_engine(frames, template)
        end = 1.0 + duration
        times = [frames[i][0] for i, r in enumerate(results) if r.events]
        hits += len(fired) == 1 and times[0] - end <= 0.5
    assert hits >= 8


def test_holding_the_gesture_fires_once():
    template = recorded_curl_template()
    frames = stream([(1.0, dict(points=OPEN)), (0.4, dict(points=lambda f: curl_points(f / 2))),
                     (3.0, dict(curled=True)), (0.4, dict(points=lambda f: curl_points(0.5 + f / 2))),
                     (1.0, dict(points=OPEN))])
    fired, _ = run_engine(frames, template)
    assert len(fired) <= 1


def test_click_lands_where_the_cursor_was_when_the_gesture_began():
    template = recorded_curl_template()
    # The knuckle drifts right during the cast.
    frames = stream([(1.0, dict(points=OPEN, wrist=(0.5, 0.7))),
                     (0.8, dict(points=curl_points, wrist=lambda f: (0.5 + 0.04 * f, 0.7))),
                     (1.0, dict(points=OPEN, wrist=(0.54, 0.7)))])
    fired, results = run_engine(frames, template)
    assert len(fired) == 1
    before = results[29].cursor  # last frame before the cast
    assert fired[0][1].position[0] < results[-1].cursor[0] - 10
    assert fired[0][1].position[0] == pytest.approx(before[0], abs=40)


def test_no_template_means_no_clicks():
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.CUSTOM))
    for t, h in stream([(1.0, dict(points=OPEN)), cast(0.8), (1.0, dict(points=OPEN))]):
        engine.step(t, h)
    assert injector.actions() == []


def test_lost_hand_clears_the_buffer():
    m = make_gesture_matcher()
    m.set_templates([recorded_curl_template()])
    f = make_pointer_filter(SCREEN)
    for t, h in stream([(0.5, dict(points=OPEN))]):
        f.update((700, 450), t)
        m.update(h, t, f)
    m.update(None, 1.0, f)
    assert len(m._buffer) == 0


def test_match_scale_is_tunable_at_runtime():
    m = make_gesture_matcher()
    m.configure(match_scale=1.5)
    assert m.match_scale == 1.5


@pytest.mark.parametrize("name", ["traversal_first", "traversal", "idle", "exits"])
def test_ordinary_movement_fires_zero_false_matches(name):
    """Build-plan validation row: 60 s of ordinary movement -> 0 false gesture matches."""
    _, frames = read_recording(f"recordings/{name}.jsonl")
    fired, _ = run_engine(frames, recorded_curl_template())
    assert fired == []


def test_casting_notifies_spell_listeners_with_the_name():
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.CUSTOM))
    engine.set_gestures([recorded_curl_template("Banish")])
    heard = []
    engine.spell_listeners.append(heard.append)
    for t, h in stream([(1.0, dict(points=OPEN)), cast(0.8), (1.0, dict(points=OPEN))]):
        engine.step(t, h)
    assert heard == ["Banish"]
