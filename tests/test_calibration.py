import math

import pytest

import config
from main import make_calibrator, make_engine
from pipeline.calibration import COUNTDOWN, DONE, IDLE, TRACE
from pipeline.cursor_mapper import CONTROL_POINT
from pipeline.injector import RecordingInjector
from pipeline.modes import Mode, ModeState
from pipeline.timing import StageTimer
from tests.synthetic import make_hand, stream

SCREEN = (1440, 900)


def square_trace(center, half, seconds, scale=0.15):
    """Knuckle traces a square of +-half (normalized) around center, repeatedly."""
    cx, cy = center
    offset = make_hand(wrist=(0.0, 0.0), scale=scale).point(CONTROL_POINT)

    def wrist(f):
        p = (f * 4 * 3) % 4  # three laps
        side, k = int(p), p - int(p)
        x, y = [(-1 + 2 * k, -1), (1, -1 + 2 * k), (1 - 2 * k, 1), (-1, 1 - 2 * k)][side]
        return (cx + half * x - offset[0], cy + half * y - offset[1])
    return [(config.CALIBRATION_COUNTDOWN_S + 0.1, dict(wrist=(cx - offset[0], cy - offset[1]), scale=scale)),
            (seconds, dict(wrist=wrist, scale=scale))]


def run_calibrator(segments):
    cal = make_calibrator()
    cal.start()
    for t, h in stream(segments):
        cal.update(h, t)
    return cal


def test_traced_area_becomes_the_calibration_box():
    cal = run_calibrator(square_trace((0.4, 0.6), 0.05, config.CALIBRATION_TRACE_S + 0.5))
    assert cal.state == DONE
    b = cal.box
    assert b.x_min == pytest.approx(0.35, abs=0.01) and b.x_max == pytest.approx(0.45, abs=0.01)
    assert b.y_min == pytest.approx(0.55, abs=0.01) and b.y_max == pytest.approx(0.65, abs=0.01)


def test_a_stray_twitch_does_not_stretch_the_box():
    segments = square_trace((0.4, 0.6), 0.05, config.CALIBRATION_TRACE_S + 0.5)
    segments.insert(2, (0.1, dict(wrist=(0.9, 0.2))))  # 3 frames far away
    cal = run_calibrator(segments)
    assert cal.box.x_max < 0.47 and cal.box.y_min > 0.53


def test_hand_off_screen_time_does_not_count():
    segments = square_trace((0.4, 0.6), 0.05, 4.0)
    segments += [(5.0, None)]
    cal = run_calibrator(segments)
    assert cal.state == TRACE and "show your hand" in cal.prompt


def test_too_small_an_area_is_redone():
    cal = run_calibrator(square_trace((0.4, 0.6), 0.005, config.CALIBRATION_TRACE_S + 0.5))
    assert cal.state == COUNTDOWN
    assert "too small" in cal.message


def test_calibrated_small_area_reaches_every_screen_edge():
    """Build-plan validation row: a ~3-inch rested-forearm box reaches all four screen edges."""
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.DWELL))
    engine.submit(lambda e: e.calibrator.start())
    frames = stream(square_trace((0.4, 0.6), 0.05, config.CALIBRATION_TRACE_S + 0.5))
    for t, h in frames:
        engine.step(t, h)
    assert engine.calibrator.state == IDLE
    assert "Calibrated" in engine.notice
    moves_before = len(injector.calls)
    t0 = frames[-1][0] + 0.1
    for t, h in stream(square_trace((0.4, 0.6), 0.06, 6.0)[1:], start=t0):  # sweep slightly past the box
        engine.step(t, h)
    xs = [c[1] for c in injector.calls[moves_before:] if c[0] == "move"]
    ys = [c[2] for c in injector.calls[moves_before:] if c[0] == "move"]
    assert min(xs) == 0 and max(xs) == SCREEN[0] - 1
    assert min(ys) == 0 and max(ys) == SCREEN[1] - 1


def test_calibrating_freezes_the_cursor_and_clicks():
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.DWELL))
    engine.calibrator.start()
    for t, h in stream(square_trace((0.4, 0.6), 0.05, 3.0)):
        engine.step(t, h)
    assert injector.calls == []


def test_recalibration_works_any_time_without_restart():
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH))
    for center in ((0.4, 0.6), (0.6, 0.4)):
        engine.calibrator.start()
        for t, h in stream(square_trace(center, 0.05, config.CALIBRATION_TRACE_S + 0.5)):
            engine.step(t, h)
        b = engine.calibration_box
        assert math.isclose((b.x_min + b.x_max) / 2, center[0], abs_tol=0.01)


def test_sensitivity_change_keeps_the_calibrated_box():
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH))
    box = engine.calibration_box
    engine.set_sensitivity(2.0)
    assert engine.calibration_box == box and engine.mapper.calibration.sensitivity == 2.0
