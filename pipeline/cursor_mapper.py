"""CONJ-5: hand position to screen position.

The control point is the index MCP knuckle: pinch-invariant, because forming
a pinch moves the fingertips but barely moves the knuckle.

Mapping goes through the Calibration interface (`to_screen(x, y)`).
BoxCalibration maps a box in normalized frame coordinates to the whole screen
and clamps at the edges. The naive default box comes from config; CONJ-12
replaces it with the box the user traced, using the same class.
"""

from dataclasses import dataclass

from pipeline.landmarks import INDEX_MCP

CONTROL_POINT = INDEX_MCP


@dataclass(frozen=True)
class Box:
    """A region of the camera frame, in normalized coordinates (same fields as profile.json calibration)."""

    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def __post_init__(self):
        if not (self.x_max > self.x_min and self.y_max > self.y_min):
            raise ValueError(f"empty or inverted box: {self}")

    @property
    def width(self):
        return self.x_max - self.x_min

    @property
    def height(self):
        return self.y_max - self.y_min

    def scaled(self, factor):
        """The box scaled about its center (factor < 1 shrinks it)."""
        cx, cy = (self.x_min + self.x_max) / 2, (self.y_min + self.y_max) / 2
        hw, hh = self.width * factor / 2, self.height * factor / 2
        return Box(cx - hw, cx + hw, cy - hh, cy + hh)


def _clamp01(v):
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


class BoxCalibration:
    """Maps `box` onto the full screen. Higher sensitivity shrinks the box, so less hand travel covers the screen."""

    def __init__(self, box, screen_size, sensitivity=1.0):
        if sensitivity <= 0:
            raise ValueError("sensitivity must be positive")
        self.box = box
        self.screen_w, self.screen_h = screen_size
        self.sensitivity = sensitivity
        self._effective = box.scaled(1.0 / sensitivity)

    def to_screen(self, x, y):
        b = self._effective
        u = _clamp01((x - b.x_min) / b.width)
        v = _clamp01((y - b.y_min) / b.height)
        return u * (self.screen_w - 1), v * (self.screen_h - 1)


class CursorMapper:
    def __init__(self, calibration):
        self.calibration = calibration

    def target(self, hand):
        """Screen position (points) the hand is pointing at, before smoothing."""
        x, y = hand.point(CONTROL_POINT)
        return self.calibration.to_screen(x, y)
