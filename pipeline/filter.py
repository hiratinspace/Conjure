"""CONJ-6: One Euro smoothing, precision mode, and the position history.

OneEuroFilter2D (Casiez et al. 2012) lowers its cutoff when the hand is slow,
removing jitter, and raises it when the hand is fast, removing lag. Its speed
estimate drives a single cutoff for both axes, so smoothing never differs by
direction.

PointerFilter adds two things on top, working in screen points:

- Precision mode: cursor gain drops toward `precision_gain` as hand speed
  drops below `precision_speed`, so small targets are hittable. Gain < 1
  makes the cursor drift from where the hand points; while the hand moves
  fast the cursor is re-anchored toward the absolute target at
  `reanchor_rate` per frame, where the correction goes unnoticed.
- The gain never snaps: it glides toward the speed-based target with a time
  constant of `ramp_s / 3` (about 95% of the way in `ramp_s`).
- Position history: a ring buffer of (t, cursor). `position_at(t)` is how a
  pinch click lands where the cursor was *before* the pinch started (CONJ-7).
"""

import math
from collections import deque


def _alpha(cutoff_hz, dt):
    tau = 1.0 / (2.0 * math.pi * cutoff_hz)
    return 1.0 / (1.0 + tau / dt)


class OneEuroFilter2D:
    def __init__(self, min_cutoff, beta, d_cutoff):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.reset()

    def reset(self):
        self._x = None
        self._dx = (0.0, 0.0)
        self.speed = 0.0

    def __call__(self, point, dt):
        if self._x is None or dt <= 0:
            if self._x is None:
                self._x = point
            return self._x
        px, py = self._x
        raw_dx = ((point[0] - px) / dt, (point[1] - py) / dt)
        a_d = _alpha(self.d_cutoff, dt)
        self._dx = (self._dx[0] + a_d * (raw_dx[0] - self._dx[0]), self._dx[1] + a_d * (raw_dx[1] - self._dx[1]))
        self.speed = math.hypot(*self._dx)
        a = _alpha(self.min_cutoff + self.beta * self.speed, dt)
        self._x = (px + a * (point[0] - px), py + a * (point[1] - py))
        return self._x


class PointerFilter:
    def __init__(self, min_cutoff, beta, d_cutoff, precision_gain, precision_speed, fast_speed, reanchor_rate,
                 screen_size, history_size, ramp_s=0.0):
        self.euro = OneEuroFilter2D(min_cutoff, beta, d_cutoff)
        self.precision_gain = precision_gain
        self.precision_speed = precision_speed
        self.fast_speed = fast_speed
        self.reanchor_rate = reanchor_rate
        self.ramp_s = ramp_s
        self.current_gain = 1.0  # the smoothed gain actually applied
        self.max_x, self.max_y = screen_size[0] - 1, screen_size[1] - 1
        self.history = deque(maxlen=history_size)
        self._t = None
        self._smooth = None
        self.cursor = None

    def configure(self, min_cutoff=None, beta=None, precision_gain=None):
        """Live-apply new parameters (settings panel)."""
        if min_cutoff is not None:
            self.euro.min_cutoff = min_cutoff
        if beta is not None:
            self.euro.beta = beta
        if precision_gain is not None:
            self.precision_gain = precision_gain

    def reset(self):
        """Forget motion state, e.g. when the hand is lost, so re-entry does not glide from the old spot.
        The history is kept: a click may still need where the cursor was."""
        self.euro.reset()
        self._t = None
        self._smooth = None

    @property
    def speed(self):
        """Smoothed hand speed in screen points per second."""
        return self.euro.speed

    def gain(self, speed):
        if self.precision_gain >= 1.0 or speed >= self.fast_speed:
            return 1.0
        if speed <= self.precision_speed:
            return self.precision_gain
        frac = (speed - self.precision_speed) / (self.fast_speed - self.precision_speed)
        return self.precision_gain + frac * (1.0 - self.precision_gain)

    def update(self, target, t):
        """Feed one raw screen target; returns the cursor position to inject."""
        if self._smooth is None:
            # First frame, or re-entry after a reset: start exactly where the hand points.
            self.euro(target, 0.0)
            self._smooth = target
            self.cursor = target
        else:
            dt = t - self._t if self._t is not None and t > self._t else 1.0 / 30.0
            smooth = self.euro(target, dt)
            g = self._ramp(self.gain(self.speed), dt)
            cx = self.cursor[0] + g * (smooth[0] - self._smooth[0])
            cy = self.cursor[1] + g * (smooth[1] - self._smooth[1])
            if self.precision_gain < 1.0:
                fast_weight = min(1.0, max(0.0, (g - self.precision_gain) / (1.0 - self.precision_gain)))
                pull = self.reanchor_rate * fast_weight
                cx += pull * (smooth[0] - cx)
                cy += pull * (smooth[1] - cy)
            # The raw target is clamped, so sitting exactly on an edge means the hand is past the
            # calibration box. Snap that axis to the edge, or a slow approach under precision gain
            # (and the filter's asymptotic approach) would stop short of it.
            if target[0] <= 0.0 or target[0] >= self.max_x:
                cx = target[0]
            if target[1] <= 0.0 or target[1] >= self.max_y:
                cy = target[1]
            self._smooth = smooth
            self.cursor = (min(max(cx, 0.0), self.max_x), min(max(cy, 0.0), self.max_y))
        self._t = t
        self.history.append((t, self.cursor))
        return self.cursor

    def _ramp(self, target_gain, dt):
        if self.ramp_s <= 0:
            self.current_gain = target_gain
        else:
            self.current_gain += (target_gain - self.current_gain) * (1 - math.exp(-dt / (self.ramp_s / 3)))
        return self.current_gain

    def position_at(self, t):
        """Cursor position at time t: the latest history entry at or before t (oldest if t predates it)."""
        if not self.history:
            return self.cursor
        for ts, pos in reversed(self.history):
            if ts <= t:
                return pos
        return self.history[0][1]
