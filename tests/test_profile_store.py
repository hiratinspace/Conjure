import json
import os

import pytest

from main import make_engine
from pipeline.events import Action
from pipeline.injector import RecordingInjector
from pipeline.modes import Mode, ModeState
from pipeline.profile_schema import default_profile, profile_to_dict
from pipeline.profile_store import ProfileStore
from pipeline.timing import StageTimer
from tests.synthetic import stream
from tests.test_calibration import square_trace
from tests.test_gesture_matcher import cast, recorded_curl_template
from tests.test_gestures import OPEN

SCREEN = (1440, 900)


def new_engine(store=None, mode=Mode.PINCH):
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(mode))
    if store is not None:
        profile, warning = store.load()
        engine.apply_profile(profile)
        engine.store = store
        engine.notice = warning or ""
    return engine


def test_missing_file_gives_defaults_without_warning(tmp_path):
    profile, warning = ProfileStore(tmp_path / "profile.json").load()
    assert profile == default_profile() and warning is None


@pytest.mark.parametrize("content", [
    "{not json",
    "",
    json.dumps({"version": 1}),
    json.dumps({**profile_to_dict(default_profile()), "version": 0}),
    json.dumps([1, 2, 3]),
])
def test_corrupt_or_old_file_gives_defaults_and_a_warning_and_keeps_the_file(tmp_path, content):
    path = tmp_path / "profile.json"
    path.write_text(content)
    profile, warning = ProfileStore(path).load()
    assert profile == default_profile()
    assert "default settings" in warning
    assert not path.exists()
    backups = list(tmp_path.glob("profile.json.bad-*"))
    assert len(backups) == 1 and backups[0].read_text() == content


def test_save_then_load_round_trips(tmp_path):
    store = ProfileStore(tmp_path / "profile.json")
    profile = default_profile()
    profile.settings.dwell_ms = 1500
    profile.calibration = {"x_min": 0.3, "x_max": 0.5, "y_min": 0.5, "y_max": 0.7}
    store.save(profile)
    assert store.load() == (profile, None)


def test_save_is_atomic_when_the_write_fails(tmp_path, monkeypatch):
    store = ProfileStore(tmp_path / "profile.json")
    store.save(default_profile())
    before = store.path.read_text()

    def boom(*_):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", boom)
    changed = default_profile()
    changed.settings.dwell_ms = 2000
    with pytest.raises(OSError):
        store.save(changed)
    assert store.path.read_text() == before
    assert [p.name for p in tmp_path.iterdir()] == ["profile.json"]  # no temp file left behind


def test_engine_save_failure_is_reported_not_raised(tmp_path, monkeypatch):
    engine = new_engine(ProfileStore(tmp_path / "profile.json"))
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("read-only")))
    engine.persist()
    assert "Could not save" in engine.notice


def test_kill_and_relaunch_restores_calibration_and_spell_with_zero_setup(tmp_path):
    """Build-plan validation row: kill and relaunch -> calibration + gesture work with no re-setup."""
    store = ProfileStore(tmp_path / "profile.json")
    first = new_engine(store)
    first.modes.set_click_mode(Mode.CUSTOM)  # the user switches to custom mode
    first.calibrator.start()
    for t, h in stream(square_trace((0.4, 0.6), 0.05, 9.0)):
        first.step(t, h)
    first.set_gestures([recorded_curl_template("Summon")])
    first.persist()
    box = first.calibration_box

    relaunched = new_engine(store)  # a brand-new process: nothing carried over but the file
    assert relaunched.calibrated and relaunched.calibration_box == box
    assert [g.name for g in relaunched.gestures] == ["Summon"]
    assert relaunched.modes.click_mode == Mode.CUSTOM
    frames = stream([(1.0, dict(points=OPEN)), cast(0.8), (1.0, dict(points=OPEN))], start=100.0)
    events = [e for t, h in frames for e in relaunched.step(t, h).events]
    assert [e.action for e in events] == [Action.LEFT]


def test_calibrating_and_recording_save_automatically(tmp_path):
    store = ProfileStore(tmp_path / "profile.json")
    engine = new_engine(store)
    engine.calibrator.start()
    for t, h in stream(square_trace((0.4, 0.6), 0.05, 9.0)):
        engine.step(t, h)
    assert store.load()[0].calibration is not None


def test_corrupt_profile_on_launch_shows_the_warning(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text("{oops")
    engine = new_engine(ProfileStore(path))
    assert "default settings" in engine.notice
    assert not engine.calibrated and engine.gestures == []
