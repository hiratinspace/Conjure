"""CONJ-19: venue.json, the demo-day threshold overrides.

After the hour-16 freeze only config changes are allowed. venue.json maps
config.py names to new values and is applied at startup, before anything is
built, so every make_* factory sees the tuned numbers.

Typos must never pass silently the night before a demo: an unknown name or a
value of the wrong type is logged as an error and skipped, and every applied
change is logged. Keys starting with "_" are comments. STAGE_CLICK_MODE, if
present, forces the click mode at launch even over the saved profile, so the
stage default is decided by this file alone.
"""

import json
import logging

log = logging.getLogger("conjure.venue")

STAGE_CLICK_MODE = "STAGE_CLICK_MODE"


def _compatible(current, new):
    if isinstance(current, bool) or isinstance(new, bool):
        return isinstance(current, bool) and isinstance(new, bool)
    if isinstance(current, (int, float)):
        return isinstance(new, (int, float))
    if isinstance(current, (list, tuple)):
        return isinstance(new, list)
    return isinstance(new, type(current))


def apply_venue(path, cfg):
    """Apply overrides from `path` onto the `cfg` module. Returns (applied, errors, stage_click_mode)."""
    if not path.exists():
        return [], [], None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.error("venue file %s is unreadable (%s): running with config.py defaults", path, e)
        return [], [str(e)], None
    if not isinstance(data, dict):
        log.error("venue file %s must be a JSON object: ignored", path)
        return [], ["not an object"], None

    applied, errors, stage_mode = [], [], None
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if key == STAGE_CLICK_MODE:
            if value in ("pinch", "dwell", "custom"):
                stage_mode = value
                applied.append(f"{key} = {value!r}")
            else:
                errors.append(f"{key}: {value!r} is not pinch, dwell, or custom")
            continue
        if not key.isupper() or not hasattr(cfg, key):
            errors.append(f"{key}: no such setting in config.py")
            continue
        current = getattr(cfg, key)
        if not _compatible(current, value):
            errors.append(f"{key}: expected {type(current).__name__}, got {type(value).__name__}")
            continue
        setattr(cfg, key, tuple(value) if isinstance(current, tuple) else value)
        applied.append(f"{key}: {current!r} -> {value!r}")
    for line in applied:
        log.info("venue: %s", line)
    for line in errors:
        log.error("venue.json problem, skipped: %s", line)
    return applied, errors, stage_mode
