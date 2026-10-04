"""FROZEN CONTRACT: the versioned profile.json schema (build-plan section 1).

The one data model. The profile store (CONJ-13) reads and writes it;
calibration (CONJ-12), the gesture recorder (CONJ-10), the matcher (CONJ-11),
dwell (CONJ-8), the filter (CONJ-6), and the settings panel (CONJ-14) consume
it.

    {
      "version": 1,
      "calibration": {"x_min", "x_max", "y_min", "y_max"} | null,   # frame coords; null = default box
      "gestures": [{"name", "samples": [3][T][21][3], "threshold"}],
      "settings": {
        "click_mode": "touch" | "pinch" | "dwell" | "custom",
        "dwell_ms": int, "dwell_radius_px": int,
        "filter": {"min_cutoff", "beta", "precision_gain"},
        "sensitivity": float
      }
    }

Additive extension (not in the build plan): an optional top-level "pointer"
section, `{"style": "mouse" | "direct", "dead_speed": float | null, "pinch_close_ms": int | null, "feel": str}`, for the
mouse-style pointer and its auto-tuned dead zone. Old files without it load
with defaults, so the version stays 1.

One deliberate deviation from the build plan's table, flagged in PROGRESS.md:
gesture samples are sequences, [3][T][21][3], not single poses [3][21][3],
because the recorded gesture is a motion. A static pose is T = 1.

`profile_from_dict` validates everything and raises ProfileError on any
problem, so the store can fall back to defaults as a whole: a profile is
either fully applied or not applied at all, never half.
"""

from dataclasses import asdict, dataclass, field

import config
from pipeline.landmarks import NUM_LANDMARKS
from pipeline.modes import CLICK_MODES

SCHEMA_VERSION = 1
SAMPLES_PER_GESTURE = 3


class ProfileError(ValueError):
    pass


@dataclass
class FilterSettings:
    min_cutoff: float = config.FILTER_MIN_CUTOFF
    beta: float = config.FILTER_BETA
    precision_gain: float = config.PRECISION_GAIN


@dataclass
class Settings:
    click_mode: str = config.DEFAULT_CLICK_MODE
    dwell_ms: int = config.DWELL_MS
    dwell_radius_px: int = config.DWELL_RADIUS_PX
    filter: FilterSettings = field(default_factory=FilterSettings)
    sensitivity: float = config.SENSITIVITY


@dataclass
class GestureTemplate:
    name: str
    samples: list  # [SAMPLES_PER_GESTURE][T][21][3], normalized (see pipeline/gestures.py)
    threshold: float


@dataclass
class PointerSettings:
    style: str = config.POINTER_STYLE  # "mouse" | "direct"
    dead_speed: float = None  # auto-tuned resting threshold (base px/s), None = config default
    pinch_close_ms: int = None  # auto-tuned pinch snap window, None = config default
    feel: str = "balanced"  # mouse-pointer preset: "precise" | "balanced" | "fast"


@dataclass
class Profile:
    version: int = SCHEMA_VERSION
    calibration: dict = None  # {"x_min", "x_max", "y_min", "y_max"} or None for the default box
    gestures: list = field(default_factory=list)  # [GestureTemplate]
    settings: Settings = field(default_factory=Settings)
    pointer: PointerSettings = field(default_factory=PointerSettings)


def default_profile():
    return Profile()


def profile_to_dict(profile):
    return asdict(profile)


def _require(cond, message):
    if not cond:
        raise ProfileError(message)


def _number(obj, key, lo=None, hi=None, integer=False):
    _require(key in obj, f"missing {key!r}")
    value = obj[key]
    _require(isinstance(value, (int, float)) and not isinstance(value, bool), f"{key!r} must be a number")
    if integer:
        _require(float(value).is_integer(), f"{key!r} must be an integer")
        value = int(value)
    _require(lo is None or value >= lo, f"{key!r} below {lo}")
    _require(hi is None or value <= hi, f"{key!r} above {hi}")
    return value


def _parse_calibration(obj):
    if obj is None:
        return None
    _require(isinstance(obj, dict), "calibration must be an object or null")
    box = {k: _number(obj, k, 0.0 - 0.5, 1.0 + 0.5) for k in ("x_min", "x_max", "y_min", "y_max")}
    _require(box["x_max"] > box["x_min"] and box["y_max"] > box["y_min"], "calibration box is empty or inverted")
    return box


def _parse_samples(samples, name):
    _require(isinstance(samples, list) and len(samples) == SAMPLES_PER_GESTURE,
             f"gesture {name!r} needs {SAMPLES_PER_GESTURE} samples")
    for sample in samples:
        _require(isinstance(sample, list) and len(sample) >= 1, f"gesture {name!r} has an empty sample")
        for frame in sample:
            _require(isinstance(frame, list) and len(frame) == NUM_LANDMARKS,
                     f"gesture {name!r} frame needs {NUM_LANDMARKS} landmarks")
            for point in frame:
                _require(isinstance(point, list) and len(point) == 3
                         and all(isinstance(v, (int, float)) for v in point), f"gesture {name!r} has a bad landmark")
    return samples


def _parse_gesture(obj):
    _require(isinstance(obj, dict), "gesture must be an object")
    name = obj.get("name")
    _require(isinstance(name, str) and name.strip(), "gesture needs a non-empty name")
    return GestureTemplate(name=name, samples=_parse_samples(obj.get("samples"), name),
                           threshold=_number(obj, "threshold", lo=0.0))


def _parse_settings(obj):
    _require(isinstance(obj, dict), "settings must be an object")
    click_mode = obj.get("click_mode")
    _require(click_mode in [m.value for m in CLICK_MODES], f"bad click_mode {click_mode!r}")
    f = obj.get("filter")
    _require(isinstance(f, dict), "settings.filter must be an object")
    return Settings(
        click_mode=click_mode,
        dwell_ms=_number(obj, "dwell_ms", lo=100, hi=10000, integer=True),
        dwell_radius_px=_number(obj, "dwell_radius_px", lo=1, hi=500, integer=True),
        filter=FilterSettings(min_cutoff=_number(f, "min_cutoff", lo=0.0001), beta=_number(f, "beta", lo=0.0),
                              precision_gain=_number(f, "precision_gain", lo=0.05, hi=1.0)),
        sensitivity=_number(obj, "sensitivity", lo=0.1, hi=10.0),
    )


def _parse_pointer(obj):
    if obj is None:
        return PointerSettings()
    _require(isinstance(obj, dict), "pointer must be an object")
    style = obj.get("style", config.POINTER_STYLE)
    _require(style in ("mouse", "direct"), f"bad pointer style {style!r}")
    dead = obj.get("dead_speed")
    if dead is not None:
        dead = _number(obj, "dead_speed", lo=1.0, hi=5000.0)
    close = obj.get("pinch_close_ms")
    if close is not None:
        close = _number(obj, "pinch_close_ms", lo=50, hi=2000, integer=True)
    feel = obj.get("feel", "balanced")
    _require(feel in ("precise", "balanced", "fast"), f"bad feel {feel!r}")
    return PointerSettings(style=style, dead_speed=dead, pinch_close_ms=close, feel=feel)


def profile_from_dict(obj):
    """Validate and build a Profile. Raises ProfileError on any problem; never returns a partial profile."""
    _require(isinstance(obj, dict), "profile must be a JSON object")
    version = obj.get("version")
    _require(version == SCHEMA_VERSION, f"unsupported profile version {version!r} (expected {SCHEMA_VERSION})")
    gestures = obj.get("gestures")
    _require(isinstance(gestures, list), "gestures must be a list")
    return Profile(
        version=SCHEMA_VERSION,
        calibration=_parse_calibration(obj.get("calibration")),
        gestures=[_parse_gesture(g) for g in gestures],
        settings=_parse_settings(obj.get("settings")),
        pointer=_parse_pointer(obj.get("pointer")),
    )

