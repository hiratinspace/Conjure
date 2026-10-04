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
    for t, h in settled[:270]:  # 9 s: countdown + measurement
        e.step(t, h)
    assert e.tuner.state == "pinches"  # rest measured, now waiting for three pinches
    dead = e.pointers["mouse"][1].dead_speed  # not applied yet
    _, pinch_frames = read_recording("recordings/pinches.jsonl")
    t_last = settled[269][0]
    for i, (t, h) in enumerate(pinch_frames[:400]):  # the user's real pinches, time-shifted to follow
        e.step(t_last + 0.033 * (i + 1), h)
        if e.tuner.state == IDLE:
            break
    assert e.tuner.state == IDLE and e.tuned
    dead = e.pointers["mouse"][1].dead_speed
    assert config.TUNE_MIN_DEAD <= dead <= config.TUNE_MAX_DEAD
    assert "Tuned to your hand" in e.notice and "window set to" in e.notice
    close_s = e.pinch_close_s
    assert config.TUNE_MIN_CLOSE_MS / 1000 <= close_s <= config.TUNE_MAX_CLOSE_MS / 1000
    assert e.store.load()[0].pointer.pinch_close_ms == round(close_s * 1000)
    # The tuned threshold keeps the resting cursor still, and is saved.
    pts = np.array([r.cursor for t, h in settled[-120:] for r in [e.step(t + 100, h)] if r.cursor])
    assert np.mean(np.hypot(*np.diff(pts, axis=0).T) < 0.01) > 0.9
    assert e.store.load()[0].pointer.dead_speed == pytest.approx(dead)


def test_no_pinch_during_the_pinch_phase_keeps_the_default_window():
    e = engine()
    e.tuner.start()
    for t, h in stream([(2.2, dict(wrist=(0.5, 0.7))), (5.3, dict(wrist=(0.5, 0.7))),
                        (config.TUNE_PINCH_TIMEOUT_S + 0.5, dict(wrist=(0.5, 0.7)))]):
        e.step(t, h)
    assert e.tuner.state == IDLE and e.tuned and e.pinch_close_s is None
    assert "no pinch was seen" in e.notice


def test_a_slow_pincher_gets_a_wider_window_within_the_clamp():
    from tests.test_pinch import ramp
    e = engine()
    e.tuner.start()
    # Slow over the stretch that counts: from fingertips apart (ratio 0.40) to touching (0.25), ~180 ms.
    slow_pinch = [(0.5, dict(pinch=ramp(0.6, 0.95))), (0.2, dict(pinch=0.95)), (0.2, dict(pinch=ramp(0.95, 0.0)))]
    frames = stream([(2.2, dict()), (5.3, dict()), (0.5, dict()), *slow_pinch, (0.4, dict()), *slow_pinch,
                     (0.4, dict()), *slow_pinch, (0.5, dict())])
    for t, h in frames:
        e.step(t, h)
    assert e.pinch_close_s is not None
    assert e.pinch_close_s > config.PINCH_QUICK_CLOSE_MS / 1000  # wider than the default 200 ms
    assert e.pinch_close_s <= config.TUNE_MAX_CLOSE_MS / 1000


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


def test_fingertips_that_do_not_quite_meet_get_a_looser_engage_ratio():
    from tests.test_pinch import ramp
    e = engine()
    e.tuner.start()
    shallow = [(0.1, dict(pinch=ramp(0.0, 0.75))), (0.2, dict(pinch=0.75)), (0.1, dict(pinch=ramp(0.75, 0.0)))]
    # pinch=0.75 leaves the tips ~0.3 hand-sizes apart: never below the default 0.25 engage ratio
    frames = stream([(2.2, dict()), (5.3, dict()), (0.5, dict()), *shallow, (0.4, dict()), *shallow,
                     (0.4, dict()), *shallow, (0.5, dict())])
    for t, h in frames:
        e.step(t, h)
    assert e.pinch_engage is not None and e.pinch_engage > config.PINCH_ENGAGE_RATIO
    assert e.pinch.left.release == pytest.approx(e.pinch_engage + config.TUNE_HYSTERESIS)
    # A shallow pinch now clicks for this person.
    from tests.test_pinch import run as run_pinch
    events, _, _, _ = run_pinch(stream([(0.5, dict(pinch=0.0)), (0.06, dict(pinch=ramp(0.0, 0.75))),
                                        (0.2, dict(pinch=0.75)), (0.1, dict(pinch=ramp(0.75, 0.0)))]))
    assert events == []  # defaults: not a pinch
    events = [x for t, h in stream([(0.5, dict(pinch=0.0)), (0.06, dict(pinch=ramp(0.0, 0.75))),
                                    (0.2, dict(pinch=0.75)), (0.1, dict(pinch=ramp(0.75, 0.0)))], start=50.0)
              for x in e.step(t, h).events]
    assert [x.action.value for x in events] == ["left"]  # tuned: a click


def test_deep_pinchers_keep_the_default_engage_ratio():
    from tests.test_pinch import ramp
    e = engine()
    e.tuner.start()
    deep = [(0.07, dict(pinch=ramp(0.0, 0.95))), (0.2, dict(pinch=0.95)), (0.1, dict(pinch=ramp(0.95, 0.0)))]
    frames = stream([(2.2, dict()), (5.3, dict()), (0.5, dict()), *deep, (0.4, dict()), *deep, (0.4, dict()),
                     *deep, (0.5, dict())])
    for t, h in frames:
        e.step(t, h)
    assert e.pinch_engage == pytest.approx(config.PINCH_ENGAGE_RATIO)
