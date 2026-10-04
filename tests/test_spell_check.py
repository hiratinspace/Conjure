import pytest

from main import make_engine
from pipeline.injector import RecordingInjector
from pipeline.modes import Mode, ModeState
from pipeline.timing import StageTimer
from tests.synthetic import stream
from tests.test_gesture_matcher import cast
from tests.test_gestures import OPEN, curl_points, recorder_frames

SCREEN = (1440, 900)


def engine_with_named_spell(name="Lumos"):
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH))
    engine.start_flow("record")
    t_last = 0.0
    for t, h in recorder_frames([curl_points] * 3):
        engine.step(t, h)
        t_last = t
    engine.finish_recording(name)
    return engine, injector, t_last


def casts(n, start):
    segs = []
    for _ in range(n):
        segs += [(1.0, dict(points=OPEN)), cast(0.8)]
    segs.append((1.0, dict(points=OPEN)))
    return stream(segs, start=start)


def test_three_good_casts_pass_the_check_and_switch_to_spell_mode():
    engine, injector, t0 = engine_with_named_spell()
    assert engine.spell_check.active
    prompts = []
    for t, h in casts(3, t0 + 0.1):
        r = engine.step(t, h)
        prompts.append(r.prompt)
    assert not engine.spell_check.active
    assert "recognized 3 of 3" in engine.notice
    assert engine.modes.click_mode == Mode.CUSTOM
    assert injector.actions() == []  # checking never clicks
    assert any("1/3" in p for p in prompts)


def test_a_spell_that_does_not_fire_gets_a_record_again_verdict():
    engine, _, t0 = engine_with_named_spell()
    for t, h in stream([(21.0, dict(points=OPEN))], start=t0 + 0.1):  # never cast it
        engine.step(t, h)
    assert not engine.spell_check.active
    assert "not recognized" in engine.notice and "Record spell" in engine.notice
    assert engine.modes.click_mode == Mode.PINCH


def test_starting_another_flow_cancels_the_rest():
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH))
    engine.start_flow("record")
    assert engine.recorder.active
    engine.start_flow("tune")
    assert engine.tuner.active and not engine.recorder.active
    engine.start_flow("calibrate")
    assert engine.calibrator.active and not engine.tuner.active
    engine, _, _ = engine_with_named_spell()
    engine.start_flow("record")
    assert not engine.spell_check.active and engine.recorder.active


def test_feel_presets_apply_and_persist(tmp_path):
    from pipeline import settings_model as sm
    from pipeline.profile_store import ProfileStore
    import config
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH))
    engine.store = ProfileStore(tmp_path / "p.json")
    sm.set_feel(engine, "fast")
    pointer = engine.pointers["mouse"][1]
    assert (pointer.low_gain, pointer.high_gain, pointer.fast_speed) == config.MOUSE_FEELS["fast"]
    fresh = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH))
    fresh.apply_profile(engine.store.load()[0])
    assert fresh.feel == "fast" and fresh.pointers["mouse"][1].high_gain == config.MOUSE_FEELS["fast"][1]
