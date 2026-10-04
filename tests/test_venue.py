import json
import types

import config
from pipeline.venue import apply_venue


def fake_config():
    return types.SimpleNamespace(PINCH_HOLD_MS=150, GESTURE_MATCH_SCALE=1.0, MIRROR=True,
                                 GESTURE_SCALES=(0.75, 1.0, 1.33), DEFAULT_CLICK_MODE="pinch")


def write(tmp_path, data):
    path = tmp_path / "venue.json"
    path.write_text(json.dumps(data) if not isinstance(data, str) else data)
    return path


def test_valid_overrides_are_applied_and_comments_skipped(tmp_path):
    cfg = fake_config()
    applied, errors, mode = apply_venue(write(tmp_path, {"_note": "x", "PINCH_HOLD_MS": 200,
                                                         "GESTURE_MATCH_SCALE": 1.2,
                                                         "GESTURE_SCALES": [0.8, 1.0]}), cfg)
    assert (cfg.PINCH_HOLD_MS, cfg.GESTURE_MATCH_SCALE, cfg.GESTURE_SCALES) == (200, 1.2, (0.8, 1.0))
    assert errors == [] and mode is None and len(applied) == 3


def test_typos_and_wrong_types_are_reported_and_skipped(tmp_path):
    cfg = fake_config()
    _, errors, _ = apply_venue(write(tmp_path, {"PINCH_HOLD_MSS": 200, "MIRROR": 1, "PINCH_HOLD_MS": "200",
                                                "lowercase": 1}), cfg)
    assert len(errors) == 4
    assert cfg.PINCH_HOLD_MS == 150 and cfg.MIRROR is True


def test_stage_click_mode_is_validated(tmp_path):
    assert apply_venue(write(tmp_path, {"STAGE_CLICK_MODE": "dwell"}), fake_config())[2] == "dwell"
    _, errors, mode = apply_venue(write(tmp_path, {"STAGE_CLICK_MODE": "paused"}), fake_config())
    assert mode is None and errors


def test_missing_or_broken_file_runs_on_defaults(tmp_path):
    assert apply_venue(tmp_path / "nope.json", fake_config()) == ([], [], None)
    cfg = fake_config()
    _, errors, _ = apply_venue(write(tmp_path, "{broken"), cfg)
    assert errors and cfg.PINCH_HOLD_MS == 150


def test_the_committed_venue_file_is_valid_against_config():
    """The real venue.json must apply cleanly: no typos reach the stage."""
    cfg = types.SimpleNamespace(**{k: getattr(config, k) for k in dir(config) if k.isupper()})
    applied, errors, mode = apply_venue(config.VENUE_PATH, cfg)
    assert errors == []
    assert mode in ("pinch", "dwell", "custom")
