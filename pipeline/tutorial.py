"""Tutorial mode: the "before" half of the before/after pitch.

This is how the typical MediaPipe virtual-mouse tutorial behaves, on purpose:
- the cursor follows the index *fingertip* (which moves when you pinch),
  mapped from the whole camera frame, with no smoothing and no precision mode;
- a click fires the instant thumb and index tips get closer than a fixed
  distance in camera units: not divided by hand size (so leaning toward the
  camera "pinches"), no hysteresis, no hold time, no open-fingers rule.

The naive clicks are counted and shown on screen, never injected: a stray
click on stage could hit something real. Conjure's own pinch detector keeps
running in shadow during tutorial mode, so the metrics can show both counts
side by side for the same hand movement.
"""

import math

from pipeline.landmarks import INDEX_TIP, THUMB_TIP

NAIVE_PINCH_DISTANCE = 0.05  # normalized frame units, like a fixed "40 px" threshold in a 640 px frame


class NaivePointer:
    def __init__(self, screen_size, aspect, pinch_distance=NAIVE_PINCH_DISTANCE):
        self.screen_w, self.screen_h = screen_size
        self.aspect = aspect
        self.pinch_distance = pinch_distance
        self._closed = False
        self.clicks = 0

    def reset(self):
        self._closed = False

    def target(self, hand):
        x, y = hand.point(INDEX_TIP)
        return (min(max(x, 0.0), 1.0) * (self.screen_w - 1), min(max(y, 0.0), 1.0) * (self.screen_h - 1))

    def update(self, hand):
        """Returns True when the naive detector would click this frame."""
        if hand is None:
            self._closed = False
            return False
        (tx, ty), (ix, iy) = hand.point(THUMB_TIP), hand.point(INDEX_TIP)
        closed = math.dist((tx * self.aspect, ty), (ix * self.aspect, iy)) < self.pinch_distance
        fired = closed and not self._closed
        self._closed = closed
        if fired:
            self.clicks += 1
        return fired
