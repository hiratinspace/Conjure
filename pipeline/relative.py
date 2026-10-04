"""Mouse-like pointer: relative motion with pointer acceleration.

The hand works like a mouse on a small pad. The cursor moves by how much the
hand moved, scaled by a gain that depends on how fast it moved:

    hand speed     gain
    tremor         0          (below `dead_speed`: the cursor does not drift at rest)
    slow           low_gain   (careful moves are scaled down: precise on tiny targets)
    fast           high_gain  (a quick flick of a few centimeters crosses the screen)

with a smooth ramp in between, like macOS pointer acceleration. This removes
the conflict of the absolute ("Direct") mapping, where covering the screen
from a small area needs a high gain that also magnifies every tremor.

"Lifting the mouse": drop the hand out of view and bring it back elsewhere.
reset() forgets the hand's last position, so re-entry moves nothing.

Coordinates: the control point (index knuckle) in "base pixels", the
normalized frame position scaled by `base_px` (aspect corrected), so speeds
and gains read like screen pixels. Smoothed by the same One Euro filter.

Same interface as PointerFilter (update, reset, speed, position_at,
configure, current_gain, precision_gain), so the engine and settings work
unchanged. `precision_gain < 1` means acceleration is on; at 1.0 the gain is
a constant `flat_gain` (acceleration off).
"""

from collections import deque

from pipeline.filter import OneEuroFilter2D


def smoothstep(edge0, edge1, x):
    if x <= edge0:
        return 0.0
    if x >= edge1:
        return 1.0
    f = (x - edge0) / (edge1 - edge0)
    return f * f * (3 - 2 * f)


class HandSpeed:
    """Smoothed hand speed in base px/s (1000 = one camera-frame height per second), independent of
    pointer style, calibration, and screen size. Every speed gate (pinch, touch, jitter metric)
    reads this, so the gates mean the same thing whichever pointer is active."""

    def __init__(self, min_cutoff, beta, d_cutoff):
        self.euro = OneEuroFilter2D(min_cutoff, beta, d_cutoff)
        self._t = None

    @property
    def speed(self):
        return self.euro.speed

    def reset(self):
        self.euro.reset()
        self._t = None

    def update(self, point, t):
        dt = t - self._t if self._t is not None and t > self._t else 1.0 / 30.0
        self.euro(point, dt)
        self._t = t
        return self.euro.speed


class GateView:
    """What detectors see: hand speed in base px/s plus the active pointer's cursor history."""

    def __init__(self, hand_speed, pointer):
        self._hand_speed = hand_speed
        self.pointer = pointer

    @property
    def speed(self):
        return self._hand_speed.speed

    def position_at(self, t):
        return self.pointer.position_at(t)


class RelativePointer:
    def __init__(self, min_cutoff, beta, d_cutoff, screen_size, history_size, dead_speed, slow_speed, fast_speed,
                 low_gain, high_gain, flat_gain=1.5, sensitivity=1.0, accelerate=True):
        self.euro = OneEuroFilter2D(min_cutoff, beta, d_cutoff)
        self.max_x, self.max_y = screen_size[0] - 1, screen_size[1] - 1
        self.history = deque(maxlen=history_size)
        self.dead_speed = dead_speed
        self.slow_speed = slow_speed
        self.fast_speed = fast_speed
        self.low_gain = low_gain
        self.high_gain = high_gain
        self.flat_gain = flat_gain
        self.sensitivity = sensitivity
        self.precision_gain = 0.5 if accelerate else 1.0
        self.current_gain = 0.0
        self.cursor = (self.max_x / 2, self.max_y / 2)
        self._smooth = None
        self._t = None

    @property
    def speed(self):
        return self.euro.speed

    def configure(self, min_cutoff=None, beta=None, precision_gain=None):
        if min_cutoff is not None:
            self.euro.min_cutoff = min_cutoff
        if beta is not None:
            self.euro.beta = beta
        if precision_gain is not None:
            self.precision_gain = precision_gain

    def reset(self):
        """Hand lost or lifted: forget where it was, keep the cursor where it is."""
        self.euro.reset()
        self._smooth = None
        self._t = None

    def gain(self, speed):
        if speed <= self.dead_speed:  # the dead zone applies with acceleration on or off: tremor never moves it
            return 0.0
        if self.precision_gain >= 1.0:
            return self.flat_gain * self.sensitivity
        if speed < self.slow_speed:
            g = self.low_gain * smoothstep(self.dead_speed, self.slow_speed, speed)
        else:
            g = self.low_gain + (self.high_gain - self.low_gain) * smoothstep(self.slow_speed, self.fast_speed, speed)
        return g * self.sensitivity

    def update(self, point, t):
        """point: control point in base pixels. Returns the new cursor position on screen."""
        if self._smooth is None:
            self.euro(point, 0.0)
            self._smooth = point
        else:
            dt = t - self._t if self._t is not None and t > self._t else 1.0 / 30.0
            smooth = self.euro(point, dt)
            g = self.current_gain = self.gain(self.speed)
            cx = self.cursor[0] + g * (smooth[0] - self._smooth[0])
            cy = self.cursor[1] + g * (smooth[1] - self._smooth[1])
            self.cursor = (min(max(cx, 0.0), self.max_x), min(max(cy, 0.0), self.max_y))
            self._smooth = smooth
        self._t = t
        self.history.append((t, self.cursor))
        return self.cursor

    def position_at(self, t):
        if not self.history:
            return self.cursor
        for ts, pos in reversed(self.history):
            if ts <= t:
                return pos
        return self.history[0][1]


class BasePixelMapper:
    """Control point -> base pixels (no box, no clamping) for the relative pointer."""

    def __init__(self, control_point, aspect, base_px, calibration):
        self.control_point = control_point
        self.aspect = aspect
        self.base_px = base_px
        self.calibration = calibration  # kept so calibration/settings code keeps working

    def target(self, hand):
        x, y = hand.point(self.control_point)
        return x * self.aspect * self.base_px, y * self.base_px

