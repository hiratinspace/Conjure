import math
import random

import numpy as np
import pytest

import config
from main import make_pointer_filter
from pipeline.cursor_mapper import Box, BoxCalibration, CursorMapper
from pipeline.filter import OneEuroFilter2D, PointerFilter
from pipeline.recorder import read_recording

SCREEN = (1440, 900)
DT = 1 / 30


def make_filter(precision_gain=config.PRECISION_GAIN, **overrides):
    params = dict(min_cutoff=config.FILTER_MIN_CUTOFF, beta=config.FILTER_BETA, d_cutoff=config.FILTER_D_CUTOFF,
                  precision_gain=precision_gain, precision_speed=config.PRECISION_SPEED_PX_S,
                  fast_speed=config.FAST_SPEED_PX_S, reanchor_rate=config.REANCHOR_RATE, screen_size=SCREEN,
                  history_size=config.POSITION_HISTORY_FRAMES)
    params.update(overrides)
    return PointerFilter(**params)


def test_noisy_resting_hand_stays_within_3px():
    # Raw jitter here is +-10 px peaks (sigma 4 px), worse than the real idle recording.
    rng = random.Random(1)
    f = make_filter()
    out = []
    for i in range(300):
        target = (700 + rng.gauss(0, 4), 450 + rng.gauss(0, 4))
        out.append(f.update(target, i * DT))
    settled = np.array(out[60:])
    dev = np.hypot(*(settled - settled.mean(axis=0)).T)
    assert dev.max() <= 3.0


def test_fast_sweep_has_no_visible_lag_trail():
    f = make_filter()
    lags = []
    for i in range(26):  # 1500 px/s, left to right, staying on screen
        x = 100 + 1500 * i * DT
        cx, _ = f.update((x, 450), i * DT)
        if i > 10:
            lags.append(x - cx)
    assert max(lags) < 40  # under one frame of travel at this speed (50 px)


def test_precision_gain_applies_only_when_slow():
    f = make_filter(precision_gain=0.3)
    assert f.gain(0) == 0.3
    assert f.gain(config.PRECISION_SPEED_PX_S) == 0.3
    assert f.gain(config.FAST_SPEED_PX_S) == 1.0
    mid = (config.PRECISION_SPEED_PX_S + config.FAST_SPEED_PX_S) / 2
    assert 0.3 < f.gain(mid) < 1.0


def test_slow_movement_moves_the_cursor_less_than_the_hand():
    f = make_filter(precision_gain=0.3)
    start = f.update((700, 450), 0.0)
    for i in range(1, 61):  # 30 px/s for 2 s: 60 px of hand travel
        end = f.update((700 + 30 * i * DT, 450), i * DT)
    assert end[0] - start[0] < 40


def test_fast_movement_reanchors_the_cursor_to_the_hand():
    f = make_filter(precision_gain=0.3)
    for i in range(61):  # slow drift builds an offset
        f.update((700 + 30 * i * DT, 450), i * DT)
    offset_after_slow = abs(760 - f.cursor[0])
    t = 61 * DT
    for i in range(30):  # fast move, then hold still
        f.update((760 + 1200 * min(i, 10) * DT, 450), t + i * DT)
    target_x = 760 + 1200 * 10 * DT
    assert abs(target_x - f.cursor[0]) < offset_after_slow / 2


def test_slow_approach_still_reaches_the_screen_edge():
    f = make_filter(precision_gain=0.3)
    for i in range(300):  # crawl right into the edge at 20 px/s, then stay pushed against it
        f.update((min(1300 + 20 * i * DT, 1439), 450), i * DT)
    assert f.cursor[0] == 1439


def test_position_at_returns_the_cursor_before_a_given_time():
    f = make_filter(precision_gain=1.0, min_cutoff=1e6, beta=0)  # pass-through
    for i in range(10):
        f.update((100 + 10 * i, 100), i * 0.1)
    assert f.position_at(0.45)[0] == pytest.approx(140)
    assert f.position_at(-1.0)[0] == pytest.approx(100)
    assert f.position_at(99)[0] == pytest.approx(190)


def test_reset_makes_reentry_jump_to_the_hand():
    f = make_filter()
    f.update((100, 100), 0.0)
    f.update((110, 100), DT)
    f.reset()
    assert f.update((1000, 800), 1.0) == (1000, 800)


def test_configure_live_applies_parameters():
    f = make_filter()
    f.configure(min_cutoff=2.0, beta=0.5, precision_gain=0.8)
    assert (f.euro.min_cutoff, f.euro.beta, f.precision_gain) == (2.0, 0.5, 0.8)


def test_one_euro_first_sample_passes_through():
    e = OneEuroFilter2D(1.0, 0.0, 1.0)
    assert e((5.0, 6.0), DT) == (5.0, 6.0)


def high_frequency_jitter(xy, half_window=15):
    ma = np.array([xy[max(0, i - half_window):i + half_window + 1].mean(axis=0) for i in range(len(xy))])
    return np.hypot(*(xy - ma).T)


def test_idle_recording_jitter_within_3px():
    """Build-plan validation row: idle-hand jitter within +-3 px, on the real recorded hand.

    Jitter is the cursor's deviation from its own 1 s moving average, so slow real drift
    of a resting hand does not count. Measured after the hand settles (t >= 14 s)."""
    mapper = CursorMapper(BoxCalibration(Box(**config.DEFAULT_CALIBRATION), SCREEN))
    f = make_pointer_filter(SCREEN)
    _, frames = read_recording("recordings/idle.jsonl")
    t0 = frames[0][0]
    raw, out = [], []
    for t, hand in frames:
        if hand is None:
            f.reset()
            continue
        target = mapper.target(hand)
        cursor = f.update(target, t)
        if t - t0 >= 14:
            raw.append(target)
            out.append(cursor)
    raw_jitter = high_frequency_jitter(np.array(raw))
    jitter = high_frequency_jitter(np.array(out))
    assert jitter.mean() <= 3.0
    assert jitter.mean() < raw_jitter.mean() / 2
    assert math.isfinite(jitter.max())


def test_precision_gain_glides_instead_of_snapping():
    f = make_filter(precision_gain=0.3, ramp_s=0.2)
    for i in range(30):  # fast sweep: gain reaches 1
        f.update((100 + 1500 * i * DT, 450), i * DT)
    assert f.current_gain > 0.95
    gains = []
    x = 100 + 1500 * 29 * DT
    for i in range(30, 55):  # hand stops dead
        f.update((x, 450), i * DT)
        gains.append(f.current_gain)
    assert gains[0] > 0.6  # one frame later: still near full gain, no snap
    assert all(a >= b for a, b in zip(gains, gains[1:]))  # monotonic glide down
    assert gains[-1] < 0.4  # settled toward precision gain within ~0.8 s (speed itself decays smoothly)
