"""CONJ-15: pause all input when the hand leaves; resume when it returns.

`lost_frames` consecutive frames without a usable hand pause (reason
HAND_LOST); `found_frames` consecutive frames with one resume. "Usable" means
the tracker reported a hand (it already drops low-confidence ones) and the
cursor control point is inside the frame: a knuckle at the very edge is a
hand leaving, while a wrist below the frame is just the normal rested pose
and does not count.

Pausing goes through the shared ModeState, so the overlay, the settings
panel, and the ActionMapper all see it, and the injector is switched off as
a second guard (main.py), so no noise frame can click while paused.
"""

from pipeline.cursor_mapper import CONTROL_POINT
from pipeline.modes import HAND_LOST


class AutoPause:
    def __init__(self, modes, lost_frames, found_frames, edge_margin):
        self.modes = modes
        self.lost_frames = lost_frames
        self.found_frames = found_frames
        self.edge_margin = edge_margin
        self._missing = 0
        self._present = 0

    def usable(self, hand):
        if hand is None:
            return False
        x, y = hand.point(CONTROL_POINT)
        m = self.edge_margin
        return m <= x <= 1 - m and m <= y <= 1 - m

    def update(self, hand):
        """Returns True if the hand counts as present this frame."""
        if self.usable(hand):
            self._present += 1
            self._missing = 0
            if self._present >= self.found_frames and HAND_LOST in self.modes.pause_reasons:
                self.modes.resume(HAND_LOST)
            return True
        self._missing += 1
        self._present = 0
        if self._missing >= self.lost_frames and HAND_LOST not in self.modes.pause_reasons:
            self.modes.pause(HAND_LOST)
        return False
