"""CONJ-14: what the settings panel can change, as pure functions on the engine.

The panel (pipeline/settings_panel.py) only draws buttons; every change goes
through here, runs on the pipeline thread via engine.submit(), applies live,
and is saved to the profile. Kept separate from Tk so it is testable.

User-facing values are coarse and named, not raw filter parameters:
smoothing is a 1-5 level, precision is on/off, and spell strictness scales
the recorded gesture's threshold (which is what profile.json persists).
"""

from pipeline.modes import USER, Mode

# Smoothing level -> One Euro min_cutoff (Hz). Higher level = smoother and a little laggier.
SMOOTHING_LEVELS = {1: 1.5, 2: 1.0, 3: 0.5, 4: 0.3, 5: 0.15}
# Responsiveness level -> One Euro beta. Higher level = less lag on fast moves (a little more shake).
RESPONSIVENESS_LEVELS = {1: 0.002, 2: 0.005, 3: 0.01, 4: 0.02, 5: 0.04}
PRECISION_ON_GAIN = 0.3

SENSITIVITY_RANGE = (0.5, 3.0, 0.1)  # (min, max, step)
DWELL_MS_RANGE = (300, 3000, 100)
DWELL_RADIUS_RANGE = (10, 80, 5)
SPELL_THRESHOLD_RANGE = (0.05, 0.6, 0.025)


def clamp_step(value, direction, value_range):
    lo, hi, step = value_range
    return round(min(hi, max(lo, value + direction * step)), 3)


def smoothing_level(min_cutoff):
    return min(SMOOTHING_LEVELS, key=lambda level: abs(SMOOTHING_LEVELS[level] - min_cutoff))


def responsiveness_level(beta):
    return min(RESPONSIVENESS_LEVELS, key=lambda level: abs(RESPONSIVENESS_LEVELS[level] - beta))


def current(engine):
    """Display values for the panel."""
    spell = engine.gestures[0] if engine.gestures else None
    return {
        "mode": engine.modes.mode,
        "click_mode": engine.modes.click_mode,
        "user_paused": USER in engine.modes.pause_reasons,
        "sensitivity": engine.mapper.calibration.sensitivity,
        "smoothing": smoothing_level(engine.filter.euro.min_cutoff),
        "responsiveness": responsiveness_level(engine.filter.euro.beta),
        "precision": engine.filter.precision_gain < 1.0,
        "dwell_ms": round(engine.dwell.dwell_s * 1000),
        "dwell_radius": round(engine.dwell.radius_px),
        "spell": spell.name if spell else None,
        "spell_threshold": spell.threshold if spell else None,
        "calibrated": engine.calibrated,
        "pointer_style": engine.pointer_style,
    }


def _then_save(fn):
    def apply(engine, *args):
        fn(engine, *args)
        engine.persist()
    return apply


@_then_save
def set_click_mode(engine, mode):
    engine.modes.set_click_mode(Mode(mode))


def toggle_user_pause(engine):
    """Pausing is not saved: a relaunch always starts unpaused."""
    if USER in engine.modes.pause_reasons:
        engine.modes.resume(USER)
    else:
        engine.actions.drop_drag()  # even if auto-pause already holds the mode at PAUSED
        engine.modes.pause(USER)


@_then_save
def step_sensitivity(engine, direction):
    engine.set_sensitivity(clamp_step(engine.mapper.calibration.sensitivity, direction, SENSITIVITY_RANGE))


@_then_save
def step_smoothing(engine, direction):
    level = min(5, max(1, smoothing_level(engine.filter.euro.min_cutoff) + direction))
    engine.filter.configure(min_cutoff=SMOOTHING_LEVELS[level])


@_then_save
def step_responsiveness(engine, direction):
    level = min(5, max(1, responsiveness_level(engine.filter.euro.beta) + direction))
    engine.filter.configure(beta=RESPONSIVENESS_LEVELS[level])


@_then_save
def toggle_pointer_style(engine):
    """Mouse-like (relative, accelerated) <-> Direct (calibrated box). Saved in the profile."""
    engine.set_pointer_style("direct" if engine.pointer_style == "mouse" else "mouse")


@_then_save
def toggle_precision(engine):
    engine.filter.configure(precision_gain=1.0 if engine.filter.precision_gain < 1.0 else PRECISION_ON_GAIN)


@_then_save
def step_dwell_ms(engine, direction):
    ms = clamp_step(engine.dwell.dwell_s * 1000, direction, DWELL_MS_RANGE)
    engine.dwell.configure(dwell_s=ms / 1000)


@_then_save
def step_dwell_radius(engine, direction):
    engine.dwell.configure(radius_px=clamp_step(engine.dwell.radius_px, direction, DWELL_RADIUS_RANGE))


@_then_save
def step_spell_threshold(engine, direction):
    """direction +1 = more forgiving (higher threshold), -1 = stricter."""
    if not engine.gestures:
        return
    spell = engine.gestures[0]
    spell.threshold = clamp_step(spell.threshold, direction, SPELL_THRESHOLD_RANGE)
    engine.set_gestures([spell])
