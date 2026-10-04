import dataclasses
import json

import pytest

import config
from pipeline.action_mapper import ActionMapper
from pipeline.events import Action, ClickEvent
from pipeline.injector import RecordingInjector
from pipeline.modes import CLICK_MODES, HAND_LOST, USER, Mode, ModeState
from pipeline.profile_schema import (SCHEMA_VERSION, ProfileError, default_profile, profile_from_dict,
                                     profile_to_dict)

# ---- Mode state machine ----


def test_mode_enum_is_exactly_the_four_modes():
    # TOUCH was added deliberately after the build plan (touchscreen-style taps).
    assert [m.value for m in Mode] == ["touch", "pinch", "dwell", "custom", "paused"]


def test_pause_remembers_click_mode_and_resume_restores_it():
    modes = ModeState(Mode.DWELL)
    modes.pause(HAND_LOST)
    assert modes.mode == Mode.PAUSED and modes.click_mode == Mode.DWELL
    modes.resume(HAND_LOST)
    assert modes.mode == Mode.DWELL


def test_input_resumes_only_when_every_pause_reason_clears():
    modes = ModeState()
    modes.pause(USER)
    modes.pause(HAND_LOST)
    modes.resume(HAND_LOST)
    assert modes.paused
    modes.resume(USER)
    assert not modes.paused


def test_paused_is_not_a_click_mode():
    with pytest.raises(ValueError):
        ModeState().set_click_mode(Mode.PAUSED)


def test_listeners_hear_effective_changes_only():
    modes = ModeState(Mode.PINCH)
    seen = []
    modes.subscribe(lambda old, new: seen.append((old, new)))
    modes.set_click_mode(Mode.DWELL)
    modes.pause(USER)
    modes.pause(HAND_LOST)  # already paused: no change
    modes.set_click_mode(Mode.CUSTOM)  # still paused: no effective change
    modes.resume(USER)
    modes.resume(HAND_LOST)
    assert seen == [(Mode.PINCH, Mode.DWELL), (Mode.DWELL, Mode.PAUSED), (Mode.PAUSED, Mode.CUSTOM)]


# ---- ClickEvent + ActionMapper ----


def test_click_event_fields_are_frozen():
    assert [f.name for f in dataclasses.fields(ClickEvent)] == ["action", "position", "amount"]
    assert [a.value for a in Action] == ["left", "right", "double", "drag_start", "drag_end", "scroll"]


def make_mapper():
    injector = RecordingInjector()
    modes = ModeState()
    return ActionMapper(injector, modes), injector, modes


def test_each_action_maps_to_injector_calls_at_the_event_position():
    mapper, inj, _ = make_mapper()
    for action in (Action.LEFT, Action.RIGHT, Action.DOUBLE, Action.DRAG_START, Action.DRAG_END):
        mapper.handle(ClickEvent(action, (10, 20)))
    mapper.handle(ClickEvent(Action.SCROLL, (10, 20), amount=-3))
    assert inj.actions() == [("click", "left", 1), ("click", "right", 1), ("click", "left", 2),
                             ("press", "left"), ("release", "left"), ("scroll", -3)]
    assert ("move", 10, 20) in inj.calls


def test_events_are_dropped_while_paused():
    mapper, inj, modes = make_mapper()
    modes.pause(HAND_LOST)
    assert not mapper.handle(ClickEvent(Action.LEFT, (1, 1)))
    assert inj.actions() == []


def test_pausing_mid_drag_releases_the_button():
    mapper, inj, modes = make_mapper()
    mapper.handle(ClickEvent(Action.DRAG_START, (1, 1)))
    modes.pause(HAND_LOST)
    assert inj.actions()[-1] == ("release", "left")
    assert not mapper.dragging


def test_drag_end_without_drag_is_ignored():
    mapper, inj, _ = make_mapper()
    assert not mapper.handle(ClickEvent(Action.DRAG_END, (1, 1)))
    assert inj.actions() == []


def test_listeners_receive_applied_events():
    mapper, _, _ = make_mapper()
    seen = []
    mapper.subscribe(seen.append)
    event = ClickEvent(Action.LEFT, (5, 5))
    mapper.handle(event)
    assert seen == [event]


# ---- profile.json schema ----


def valid_profile_dict():
    d = profile_to_dict(default_profile())
    d["calibration"] = {"x_min": 0.3, "x_max": 0.6, "y_min": 0.5, "y_max": 0.8}
    frame = [[0.0, 0.0, 0.0]] * 21
    d["gestures"] = [{"name": "Lumos", "samples": [[frame, frame], [frame], [frame, frame, frame]], "threshold": 0.4}]
    return d


def test_default_profile_round_trips_through_json():
    d = json.loads(json.dumps(profile_to_dict(default_profile())))
    assert profile_from_dict(d) == default_profile()


def test_full_profile_round_trips():
    d = valid_profile_dict()
    assert profile_to_dict(profile_from_dict(d)) == d


def test_default_settings_come_from_config():
    s = default_profile().settings
    assert (s.click_mode, s.dwell_ms, s.dwell_radius_px, s.sensitivity) == (
        config.DEFAULT_CLICK_MODE, config.DWELL_MS, config.DWELL_RADIUS_PX, config.SENSITIVITY)
    assert s.click_mode in [m.value for m in CLICK_MODES]


def test_top_level_fields_are_frozen():
    # "pointer" is an additive, optional section (mouse-style pointer + auto-tune); files without it load.
    assert set(profile_to_dict(default_profile())) == {"version", "calibration", "gestures", "settings", "pointer"}
    assert set(profile_to_dict(default_profile())["settings"]) == {
        "click_mode", "dwell_ms", "dwell_radius_px", "filter", "sensitivity"}


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(version=SCHEMA_VERSION + 1),
    lambda d: d.pop("settings"),
    lambda d: d["settings"].update(click_mode="paused"),
    lambda d: d["settings"].update(dwell_ms="soon"),
    lambda d: d["settings"]["filter"].pop("beta"),
    lambda d: d.update(calibration={"x_min": 0.6, "x_max": 0.3, "y_min": 0.5, "y_max": 0.8}),
    lambda d: d["gestures"][0].update(samples=[[]]),
    lambda d: d["gestures"][0].update(name=""),
    lambda d: d["gestures"][0]["samples"][0][0].pop(),
    lambda d: d.update(gestures="none"),
])
def test_any_invalid_field_rejects_the_whole_profile(mutate):
    d = valid_profile_dict()
    mutate(d)
    with pytest.raises(ProfileError):
        profile_from_dict(d)


def test_clicks_inside_the_refractory_period_are_dropped():
    injector = RecordingInjector()
    mapper = ActionMapper(injector, ModeState(), refractory_s=0.3)
    assert mapper.handle(ClickEvent(Action.LEFT, (1, 1)), t=1.0)
    assert not mapper.handle(ClickEvent(Action.RIGHT, (1, 1)), t=1.2)
    assert mapper.handle(ClickEvent(Action.LEFT, (1, 1)), t=1.35)
    assert mapper.suppressed == 1


def test_refractory_never_blocks_scroll_or_drag_end():
    injector = RecordingInjector()
    mapper = ActionMapper(injector, ModeState(), refractory_s=0.3)
    mapper.handle(ClickEvent(Action.DRAG_START, (1, 1)), t=1.0)
    assert mapper.handle(ClickEvent(Action.DRAG_END, (5, 5)), t=1.05)
    assert mapper.handle(ClickEvent(Action.SCROLL, (5, 5), amount=2), t=1.06)
