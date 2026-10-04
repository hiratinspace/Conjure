import pytest

import config

from main import make_engine
from pipeline import settings_model as sm
from pipeline.injector import RecordingInjector
from pipeline.modes import USER, Mode, ModeState
from pipeline.profile_store import ProfileStore
from pipeline.timing import StageTimer
from tests.synthetic import stream
from tests.test_gesture_matcher import recorded_curl_template


@pytest.fixture
def engine(tmp_path):
    e = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), (1440, 900), ModeState(Mode.PINCH))
    e.store = ProfileStore(tmp_path / "profile.json")
    return e


def saved(engine):
    return engine.store.load()[0].settings


def test_clamp_step_stays_in_range():
    assert sm.clamp_step(1.0, +1, (0.5, 3.0, 0.1)) == 1.1
    assert sm.clamp_step(3.0, +1, (0.5, 3.0, 0.1)) == 3.0
    assert sm.clamp_step(0.5, -1, (0.5, 3.0, 0.1)) == 0.5


def test_smoothing_level_round_trips():
    for level, cutoff in sm.SMOOTHING_LEVELS.items():
        assert sm.smoothing_level(cutoff) == level


def test_each_setting_applies_live_and_is_saved(engine):
    sm.step_sensitivity(engine, +1)
    assert engine.mapper.calibration.sensitivity == pytest.approx(1.1)
    sm.step_smoothing(engine, +1)
    assert engine.filter.euro.min_cutoff == sm.SMOOTHING_LEVELS[4]
    sm.toggle_precision(engine)
    assert engine.filter.precision_gain == 1.0
    sm.step_dwell_ms(engine, +1)
    assert engine.dwell.dwell_s == pytest.approx((config.DWELL_MS + 100) / 1000)
    sm.step_dwell_radius(engine, -1)
    assert engine.dwell.radius_px == config.DWELL_RADIUS_PX - 5
    sm.set_click_mode(engine, "dwell")
    assert engine.modes.click_mode == Mode.DWELL
    s = saved(engine)
    assert (s.sensitivity, s.dwell_ms, s.dwell_radius_px, s.click_mode) == (
        pytest.approx(1.1), config.DWELL_MS + 100, config.DWELL_RADIUS_PX - 5, "dwell")
    assert s.filter.min_cutoff == sm.SMOOTHING_LEVELS[4] and s.filter.precision_gain == 1.0


def test_live_change_affects_the_very_next_frame(engine):
    sm.set_click_mode(engine, "dwell")
    sm.step_dwell_ms(engine, -1)  # 100 ms shorter than the default
    frames = stream([(0.3, dict(wrist=lambda f: (0.4 + 0.2 * f, 0.7))), (1.5, dict(wrist=(0.6, 0.7)))])
    clicks = [i for i, (t, h) in enumerate(frames) if engine.step(t, h).events]
    assert len(clicks) == 1
    assert frames[clicks[0]][0] - 0.3 < config.DWELL_MS / 1000  # sooner than the default


def test_spell_forgiveness_adjusts_and_saves_the_threshold(engine):
    engine.set_gestures([recorded_curl_template()])
    before = engine.gestures[0].threshold
    sm.step_spell_threshold(engine, +1)
    assert engine.gestures[0].threshold == pytest.approx(before + 0.025)
    assert engine.matcher.templates[0].threshold == engine.gestures[0].threshold
    assert engine.store.load()[0].gestures[0].threshold == pytest.approx(before + 0.025)


def test_spell_forgiveness_without_a_spell_is_a_no_op(engine):
    sm.step_spell_threshold(engine, +1)
    assert engine.gestures == []


def test_user_pause_toggles_and_is_not_saved(engine):
    sm.toggle_user_pause(engine)
    assert USER in engine.modes.pause_reasons and engine.modes.mode == Mode.PAUSED
    sm.toggle_user_pause(engine)
    assert not engine.modes.paused


def test_current_reports_display_values(engine):
    v = sm.current(engine)
    assert v["click_mode"] == Mode.PINCH and v["smoothing"] == 3 and v["precision"] and v["spell"] is None


def test_big_button_is_at_least_60px_tall():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    try:
        from pipeline.settings_panel import MIN_TARGET_PX, BigButton
        for label, width in (("+", 3), ("Calibrate", 10), ("Pinch", 8)):
            b = BigButton(root, label, lambda: None, width=width)
            b.update_idletasks()
            assert b.winfo_reqheight() >= MIN_TARGET_PX
            assert b.winfo_reqwidth() >= MIN_TARGET_PX
    finally:
        root.destroy()
