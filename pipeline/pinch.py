"""CONJ-7 (+ drag from CONJ-9): pinch clicks with hysteresis and a confirmation hold.

One PinchChannel per thumb-finger pair: thumb + index is the left button (and
drags), thumb + middle is the right button.

States: OPEN -> PENDING (ratio below `engage`, other fingers open)
             -> CONFIRMED (stayed closed for `hold_s`)
             -> DRAGGING (CONFIRMED, still firmly closed, and the cursor then moved `drag_start_px`)
Release is ratio above `release` (hysteresis: release > engage, so a ratio
hovering near one threshold cannot flicker the state). On release, CONFIRMED
fires one click and DRAGGING ends the drag; PENDING (a blip under the hold
time) fires nothing.

Pre-pinch latch: closing the fingers drags the knuckle slightly, so the
click lands where the cursor was when the closing motion *began*: walking
back from the engage frame while the ratio was still falling (within
`LATCH_NOISE`), at most `latch_lookback_s`, and reading that moment from the
filter's position history.

Drag distance is measured from where the cursor was at confirmation, not
from the latch: the knuckle drift caused by closing the pinch must not turn
every click into a drag.

Losing the hand or the fingertips leaving the frame cancels a pending or
confirmed pinch without clicking, and ends a drag.
"""

import math
from collections import deque

from pipeline.events import Action, ClickEvent

OPEN, PENDING, CONFIRMED, DRAGGING = "open", "pending", "confirmed", "dragging"
LATCH_NOISE = 0.02  # ratio wobble still counted as "falling" when walking back to the pinch start


def _left_ratio(pose):
    return pose.pinch_index if pose.index_pinch_inside else None


def _left_others_open(pose, open_ext):
    return (pose.middle_ext + pose.ring_ext + pose.pinky_ext) / 3 > open_ext


def _right_ratio(pose):
    return pose.pinch_middle if pose.middle_pinch_inside else None


def _right_others_open(pose, open_ext):
    return (pose.index_ext + pose.pinky_ext) / 2 > open_ext


class PinchChannel:
    def __init__(self, name, ratio_fn, others_open_fn, click_action, allow_drag, engage, release, hold_s,
                 open_extension, drag_start_px, latch_lookback_s):
        if release <= engage:
            raise ValueError("release ratio must exceed engage ratio (hysteresis)")
        self.name = name
        self._ratio = ratio_fn
        self._others_open = others_open_fn
        self.click_action = click_action
        self.allow_drag = allow_drag
        self.engage = engage
        self.release = release
        self.hold_s = hold_s
        self.open_extension = open_extension
        self.drag_start_px = drag_start_px
        self.latch_lookback_s = latch_lookback_s
        self._ratios = deque(maxlen=60)  # (t, ratio), ~2 s
        self.state = OPEN
        self.ratio = None
        self._t_engage = None
        self._latch = None
        self._confirm_pos = None

    @property
    def active(self):
        return self.state != OPEN

    def cancel(self, cursor):
        """Abort without clicking; end a drag at `cursor`. Returns the events to emit."""
        events = []
        if self.state == DRAGGING:
            events.append(ClickEvent(Action.DRAG_END, cursor))
        self.state = OPEN
        self._latch = None
        return events

    def update(self, pose, t, cursor, pointer_filter):
        r = self._ratio(pose) if pose is not None else None
        self.ratio = r
        if r is None:  # no hand, or the pinching fingertips are at the frame edge
            self._ratios.clear()
            return self.cancel(cursor)
        self._ratios.append((t, r))

        if self.state == OPEN:
            if r < self.engage and self._others_open(pose, self.open_extension):
                self.state = PENDING
                self._t_engage = t
            return []

        if r > self.release:
            events = []
            if self.state == CONFIRMED:
                events.append(ClickEvent(self.click_action, self._latch))
            elif self.state == DRAGGING:
                events.append(ClickEvent(Action.DRAG_END, cursor))
            self.state = OPEN
            self._latch = None
            return events

        if self.state == PENDING:
            if not self._others_open(pose, self.open_extension):
                self.state = OPEN  # the hand is curling into a fist, not pinching
                return []
            if t - self._t_engage >= self.hold_s:
                self.state = CONFIRMED
                self._latch = pointer_filter.position_at(self._closing_start())
                self._confirm_pos = cursor
        # Only a firmly closed pinch (below `engage`) can start a drag: the hand moving while the
        # fingers are already opening (inside the hysteresis band) is a release, not a drag.
        if (self.state == CONFIRMED and self.allow_drag and r < self.engage
                and math.dist(cursor, self._confirm_pos) > self.drag_start_px):
            self.state = DRAGGING
            return [ClickEvent(Action.DRAG_START, self._latch)]
        return []


    def _closing_start(self):
        """Time the fingers started closing for the current pinch."""
        hist = [(t, r) for t, r in self._ratios if t <= self._t_engage]
        i = len(hist) - 1
        while (i > 0 and hist[i - 1][1] >= hist[i][1] - LATCH_NOISE
               and self._t_engage - hist[i - 1][0] <= self.latch_lookback_s):
            i -= 1
        return hist[i][0] if hist else self._t_engage


class PinchDetector:
    """Left (thumb + index, with drag) and right (thumb + middle) channels; only one can be active at a time."""

    def __init__(self, engage, release, hold_s, open_extension, drag_start_px, latch_lookback_s):
        common = dict(engage=engage, release=release, hold_s=hold_s, open_extension=open_extension,
                      drag_start_px=drag_start_px, latch_lookback_s=latch_lookback_s)
        self.left = PinchChannel("left", _left_ratio, _left_others_open, Action.LEFT, True, **common)
        self.right = PinchChannel("right", _right_ratio, _right_others_open, Action.RIGHT, False, **common)

    def reset(self, cursor):
        return self.left.cancel(cursor) + self.right.cancel(cursor)

    def update(self, pose, t, cursor, pointer_filter):
        if self.right.active:
            return self.right.update(pose, t, cursor, pointer_filter)
        events = self.left.update(pose, t, cursor, pointer_filter)
        if not self.left.active and not events:
            events = self.right.update(pose, t, cursor, pointer_filter)
        return events

    def status(self):
        for ch in (self.left, self.right):
            if ch.active:
                return f"pinch {ch.name}: {ch.state}"
        r = self.left.ratio
        return f"pinch ratio {r:.2f}" if r is not None else "pinch: fingertips not in frame"
