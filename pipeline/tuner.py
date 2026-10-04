"""Auto-tune: measure the user's own resting tremor and set the pointer's dead zone from it.

The mouse-style pointer ignores hand motion below `dead_speed`, so tremor
never moves the cursor. The right value differs per person and per day, so
instead of a fixed number, Tuner asks the user to rest for a few seconds,
records the smoothed hand speed, and sets the dead zone just above what their
resting hand does (the 95th percentile times `margin`, clamped), with the
"careful movement" band scaled to match.

Then a second phase measures how the user pinches: they pinch three times,
naturally, and the time each pinch takes to close (from fingertips apart to
touching) sets the pinch "snap" window at `pinch_margin` x the slowest one,
clamped. A slow pincher is no longer locked out by a window tuned on someone
else's hand.

Driven by the engine one frame at a time, like the calibrator: COUNTDOWN
(get comfortable), MEASURE (hold still), PINCHES (pinch three times), DONE. Frames with no hand do not
count. A result that is suspiciously high (the hand was moving, not resting)
is rejected with a message and measuring starts over.
"""

import numpy as np

IDLE, COUNTDOWN, MEASURE, PINCHES, DONE = "idle", "countdown", "measure", "pinches", "done"


class Tuner:
    def __init__(self, countdown_s, measure_s, margin, min_dead, max_dead, slow_ratio, min_slow, moving_speed,
                 pinch_engage=0.25, pinch_release=0.40, pinches_wanted=3, pinch_timeout_s=12.0, pinch_margin=1.5,
                 min_close_s=0.15, max_close_s=0.45):
        self.countdown_s = countdown_s
        self.measure_s = measure_s
        self.margin = margin
        self.min_dead = min_dead
        self.max_dead = max_dead
        self.slow_ratio = slow_ratio
        self.min_slow = min_slow
        self.moving_speed = moving_speed
        self.pinch_engage = pinch_engage
        self.pinch_release = pinch_release
        self.pinches_wanted = pinches_wanted
        self.pinch_timeout_s = pinch_timeout_s
        self.pinch_margin = pinch_margin
        self.min_close_s = min_close_s
        self.max_close_s = max_close_s
        self.pinch_close_s = None  # set after the pinch phase, None if no pinch was seen
        self.close_times = []
        self._t_open = None
        self._closed = False
        self.state = IDLE
        self.prompt = ""
        self.message = ""
        self.result = None  # (dead_speed, slow_speed, measured_p95)
        self._speeds = []
        self._t_state = None
        self._measured_s = 0.0
        self._t_prev = None

    @property
    def active(self):
        return self.state in (COUNTDOWN, MEASURE, PINCHES)

    def start(self):
        self.state = COUNTDOWN
        self.message = ""
        self.result = None
        self._t_state = None

    def cancel(self):
        self.state = IDLE
        self.prompt = ""

    def update(self, hand_speed, t, pinch_ratio=None):
        """hand_speed: smoothed hand speed this frame, or None without a hand. pinch_ratio: thumb-index
        distance over hand size, or None when the fingertips are not trusted."""
        if not self.active:
            return
        if self._t_state is None:
            self._t_state = t
        if self.state == PINCHES:
            return self._update_pinches(pinch_ratio, t)
        if self.state == COUNTDOWN:
            left = self.countdown_s - (t - self._t_state)
            self.prompt = f"Tune: rest your forearm and get comfortable... {max(0, left):.0f}"
            if left <= 0:
                self.state = MEASURE
                self._speeds, self._measured_s, self._t_prev = [], 0.0, t
            return
        if hand_speed is not None:
            self._measured_s += t - self._t_prev
            self._speeds.append(hand_speed)
        self._t_prev = t
        left = self.measure_s - self._measured_s
        self.prompt = (f"Tune: hold your hand as still as is comfortable... {max(0, left):.0f}"
                       if hand_speed is not None else "Tune: show your hand to the camera")
        if left <= 0:
            self._finish(t)

    def _finish(self, t):
        p95 = float(np.percentile(self._speeds, 95))
        if p95 > self.moving_speed:
            self.message = "Your hand was moving. Rest it on the table and try to keep it still."
            self.state = COUNTDOWN
            self._t_state = t
            return
        dead = min(self.max_dead, max(self.min_dead, self.margin * p95))
        slow = max(self.min_slow, dead * self.slow_ratio)
        self.result = (dead, slow, p95)
        self.state = PINCHES
        self._t_state = t
        self.close_times, self._t_open, self._closed = [], None, False
        self.message = ""

    def _update_pinches(self, ratio, t):
        n = len(self.close_times)
        self.prompt = f"Tune: now pinch {self.pinches_wanted} times, the way that feels natural... {n}/{self.pinches_wanted}"
        if ratio is not None:
            if ratio >= self.pinch_release:
                self._t_open = t
                self._closed = False
            elif ratio < self.pinch_engage and not self._closed:
                self._closed = True
                if self._t_open is not None and t - self._t_open < 1.0:
                    self.close_times.append(t - self._t_open)
        if len(self.close_times) >= self.pinches_wanted or t - self._t_state >= self.pinch_timeout_s:
            self._finish_pinches()

    def _finish_pinches(self):
        if self.close_times:
            slowest = max(self.close_times)
            self.pinch_close_s = min(self.max_close_s, max(self.min_close_s, self.pinch_margin * slowest))
        else:
            self.pinch_close_s = None  # keep the default; the hint explains
        self.state = DONE
        self.prompt = ""
        self.message = ""
