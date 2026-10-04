"""CONJ-8: dwell click. Hold the cursor still to click.

"Still" means the cursor stays within `radius_px` of where the dwell started.
Leaving that circle restarts the dwell from the new position. After a click,
or after the hand re-enters the frame, the detector is disarmed until the
cursor has moved out of the circle once, so a user who simply stays still
never machine-guns clicks and a hand that reappears never clicks on its own.

`progress` (0..1, or None while disarmed) drives the on-screen countdown ring.
"""

import math

from pipeline.events import Action, ClickEvent


class DwellDetector:
    def __init__(self, dwell_s, radius_px):
        self.dwell_s = dwell_s
        self.radius_px = radius_px
        self.armed = False
        self.progress = None
        self.anchor = None
        self._t_anchor = None

    def configure(self, dwell_s=None, radius_px=None):
        """Live-apply new settings (settings panel)."""
        if dwell_s is not None:
            self.dwell_s = dwell_s
        if radius_px is not None:
            self.radius_px = radius_px

    def reset(self):
        """Hand lost or mode left: forget the dwell and require movement before the next one."""
        self.anchor = None
        self.armed = False
        self.progress = None

    def update(self, cursor, t):
        if self.anchor is None or math.dist(cursor, self.anchor) > self.radius_px:
            if self.anchor is not None:
                self.armed = True  # moved out of the circle: the next stillness may click
            self.anchor = cursor
            self._t_anchor = t
        if not self.armed:
            self.progress = None
            return []
        self.progress = min(1.0, (t - self._t_anchor) / self.dwell_s)
        if self.progress < 1.0:
            return []
        self.armed = False
        self.progress = None
        return [ClickEvent(Action.LEFT, cursor)]

    def status(self):
        if self.progress is None:
            return "dwell: move to arm" if not self.armed else "dwell: armed"
        return f"dwell: {self.progress * 100:.0f}%"
