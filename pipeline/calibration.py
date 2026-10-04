"""CONJ-12: range-of-motion calibration.

With the forearm rested, the user traces the edges of the small area they can
move in comfortably. The knuckle (the cursor control point) positions seen
during the trace become a Box via percentiles, so a stray twitch does not
stretch it and the edges are reachable without straining. BoxCalibration
then maps that box to the whole screen, replacing the naive default.

Frames without a hand do not count toward the trace time. Too small a box
(the hand barely moved) is rejected with a message and the trace starts over.
Recalibration can be started at any time; nothing needs a restart.
"""

import numpy as np

from pipeline.cursor_mapper import CONTROL_POINT, Box

IDLE, COUNTDOWN, TRACE, DONE = "idle", "countdown", "trace", "done"


class Calibrator:
    def __init__(self, countdown_s, trace_s, low_pct, high_pct, min_size):
        self.countdown_s = countdown_s
        self.trace_s = trace_s
        self.low_pct = low_pct
        self.high_pct = high_pct
        self.min_size = min_size
        self.state = IDLE
        self.prompt = ""
        self.message = ""
        self.box = None
        self._points = []
        self._t_state = None
        self._traced_s = 0.0
        self._t_prev = None

    @property
    def active(self):
        return self.state in (COUNTDOWN, TRACE)

    def start(self):
        self.state = COUNTDOWN
        self.message = ""
        self.box = None
        self._t_state = None
        self._points = []

    def cancel(self):
        self.state = IDLE
        self.prompt = ""

    def update(self, hand, t):
        if not self.active:
            return
        if self._t_state is None:
            self._t_state = t
        if self.state == COUNTDOWN:
            left = self.countdown_s - (t - self._t_state)
            self.prompt = f"Calibrate: rest your forearm and get comfortable... {max(0, left):.0f}"
            if left <= 0:
                self.state = TRACE
                self._points, self._traced_s, self._t_prev = [], 0.0, t
            return

        if hand is not None:
            self._traced_s += t - self._t_prev
            self._points.append(hand.point(CONTROL_POINT))
        self._t_prev = t
        left = self.trace_s - self._traced_s
        self.prompt = (f"Calibrate: trace the edges of a small area you can reach comfortably... {max(0, left):.0f}"
                       if hand is not None else "Calibrate: show your hand to the camera")
        if left <= 0:
            self._finish(t)

    def _finish(self, t):
        pts = np.array(self._points)
        x_lo, x_hi = np.percentile(pts[:, 0], [self.low_pct, self.high_pct])
        y_lo, y_hi = np.percentile(pts[:, 1], [self.low_pct, self.high_pct])
        if x_hi - x_lo < self.min_size or y_hi - y_lo < self.min_size:
            self.message = "That area was too small. Move a little further toward each edge."
            self.state = COUNTDOWN
            self._t_state = t
            return
        self.box = Box(float(x_lo), float(x_hi), float(y_lo), float(y_hi))
        self.state = DONE
        self.prompt = ""
        self.message = ""
