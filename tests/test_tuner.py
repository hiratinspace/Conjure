import json

import numpy as np
import pytest

import config
from main import make_engine
from pipeline.injector import RecordingInjector
from pipeline.modes import Mode, ModeState
from pipeline.profile_schema import default_profile, profile_from_dict, profile_to_dict
from pipeline.profile_store import ProfileStore
from pipeline.recorder import read_recording
from pipeline.timing import StageTimer
from pipeline.tuner import COUNTDOWN, DONE, IDLE
from tests.synthetic import stream

SCREEN = (1440, 900)


def engine(store=None):
    e = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH), "mouse")
    e.store = store
    return e


def test_tuning_on_the_real_resting_hand_sets_a_threshold_just_above_its_tremor(tmp_path):
    e = engine(ProfileStore(tmp_path / "p.json"))
    _, frames = read_recording("recordings/idle.jsonl")
    t0 = frames[0][0]
    settled = [(t, h) for t, h in frames if t - t0 >= 14]  # the hand is resting from 14 s on
    e.submit(lambda eng: eng.tuner.start())
    for t, h in settled:
        e.step(t, h)
    assert e.tuner.state == IDLE and e.tuned
    dead = e.pointers["mouse"][1].dead_speed
    assert config.TUNE_MIN_DEAD <= dead <= config.TUNE_MAX_DEAD
    assert "Tuned to your hand" in e.notice
    # The tuned threshold keeps the resting cursor still, and is saved.
    pts = np.array([r.cursor for t, h in settled[-120:] for r in [e.step(t + 100, h)] if r.cursor])
    assert np.mean(np.hypot(*np.diff(pts, axis=0).T) < 0.01) > 0.9
    assert e.store.load()[0].pointer.dead_speed == pytest.approx(dead)


def test_a_moving_hand_is_rejected_and_measured_again():
    e = engine()
    e.tuner.start()
    import math
    sway = lambda f: (0.5 + 0.2 * math.sin(f * 6 * math.pi), 0.7)  # 3 sweeps across the frame in 5.5 s
    frames = stream([(2.2, dict(wrist=(0.5, 0.7))), (5.5, dict(wrist=sway))])
    for t, h in frames:
        e.step(t, h)
    assert e.tuner.state == COUNTDOWN and "moving" in e.tuner.message
    assert not e.tuned


def test_no_cursor_movement_or_clicks_while_tuning():
    injector = RecordingInjector()
    e = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH), "mouse")
    e.tuner.start()
    for t, h in stream([(3.0, dict(wrist=lambda f: (0.3 + 0.4 * f, 0.7)))]):
        e.step(t, h)
    assert injector.calls == []


def test_pointer_style_and_tuning_round_trip_through_the_profile(tmp_path):
    store = ProfileStore(tmp_path / "p.json")
    e = engine(store)
    e.set_pointer_style("direct")
    e.set_dead_speed(123.0)
    e.persist()
    fresh = engine()
    fresh.apply_profile(store.load()[0])
    assert fresh.pointer_style == "direct" and fresh.pointers["mouse"][1].dead_speed == 123.0 and fresh.tuned


def test_old_profiles_without_a_pointer_section_still_load():
    d = profile_to_dict(default_profile())
    del d["pointer"]
    p = profile_from_dict(json.loads(json.dumps(d)))
    assert p.pointer.style == config.POINTER_STYLE and p.pointer.dead_speed is None


def test_bad_pointer_section_rejects_the_profile():
    from pipeline.profile_schema import ProfileError
    d = profile_to_dict(default_profile())
    d["pointer"] = {"style": "joystick"}
    with pytest.raises(ProfileError):
        profile_from_dict(d)
