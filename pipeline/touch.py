"""Touch mode: use the index finger like a finger on a touchscreen.

A webcam cannot see contact with a screen, and its depth estimate is too noisy
to detect a push toward the camera. So "touching" is a quick bend of the
index finger, the motion of tapping a table:

    pointing (finger straight) = hovering
    finger bends              = touch down
    finger straightens        = lift

Straightness is |MCP->tip| / (sum of the three finger bones): 1.0 for a
straight finger, ~0.3-0.6 bent. It needs no depth and no hand size, so it is
the same at any distance from the camera. The recordings show a clean split:
pointing frames sit at 0.95-1.0.

Phone vocabulary, so nothing new to learn:
    tap (down and up within `tap_max_s`)         -> left click
    two taps                                     -> double-click (ClickCounter)
    press and hold still for `long_press_s`      -> right click (fires while held)
    press and move `drag_px`                     -> drag; lift drops

Safety, from the recordings (ordinary movement, where the finger curls on its
own, produced false touches at 300-1500 px/s and "drags" within 35-100 ms):
- A touch only counts while the hand is nearly still (`max_speed`): aim,
  settle, tap. A bend while moving is ignored until the finger straightens.
- A drag needs the press held `drag_hold_s` first ("press, then move"). A
  touch that slides sooner is cancelled: no click, no drag.
- Armed only after the finger has been straight (pointing) for `arm_s`. A
  relaxed, curled hand, the user's natural pose, never taps.
- The cursor stays on the knuckle (cursor_mapper), which barely moves when the
  finger bends, and a tap lands where the finger was before it bent (filter
  history), so tapping never drags the cursor off target.
- Touches shorter than `min_touch_s` are tremor blips, not taps.
- Index joints at the frame edge are untrusted; losing the hand cancels.
"""

import math

from pipeline.events import Action, ClickEvent

IDLE, HOVER, TOUCH, DRAG, HELD, SLID = "idle", "hover", "touch", "drag", "held", "slid"
INDEX_JOINTS = (5, 6, 7, 8)


def straightness(hand, aspect):
    pts = [(hand.landmarks[i][0] * aspect, hand.landmarks[i][1]) for i in INDEX_JOINTS]
    bones = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    return math.dist(pts[0], pts[-1]) / bones if bones > 0 else 1.0


class TouchDetector:
    def __init__(self, aspect, edge_margin, hover, down, up, arm_s, min_touch_s, tap_max_s, long_press_s, drag_px,
                 max_speed, drag_hold_s):
        if not down < up <= hover:
            raise ValueError("touch thresholds must satisfy down < up <= hover")
        self.aspect = aspect
        self.edge_margin = edge_margin
        self.hover = hover
        self.down = down
        self.up = up
        self.arm_s = arm_s
        self.min_touch_s = min_touch_s
        self.tap_max_s = tap_max_s
        self.long_press_s = long_press_s
        self.drag_px = drag_px
        self.max_speed = max_speed
        self.drag_hold_s = drag_hold_s
        self._need_straight = False  # a bend was rejected: the finger must straighten before the next touch
        self.state = IDLE
        self.straightness = None
        self.blocked = 0  # blips and unarmed bends (metrics)
        self._t_straight = None
        self._t_down = None
        self._down_pos = None
        self._latch = None
        self._t_last_straight = None  # last frame the finger was fully straight (the pre-tap position)
        self._t_now = None

    def _inside(self, hand):
        m = self.edge_margin
        return all(m <= hand.landmarks[i][0] <= 1 - m and m <= hand.landmarks[i][1] <= 1 - m for i in INDEX_JOINTS)

    def reset(self, cursor):
        events = [ClickEvent(Action.DRAG_END, cursor)] if self.state == DRAG else []
        self.state = IDLE
        self._t_straight = None
        return events

    def update(self, hand, t, cursor, pointer_filter):
        if hand is None or not self._inside(hand):
            self.straightness = None
            return self.reset(cursor)
        s = self.straightness = straightness(hand, self.aspect)
        self._t_now = t
        if s > self.hover:
            self._t_last_straight = t

        if self.state == IDLE:
            if s > self.hover:
                self._t_straight = self._t_straight if self._t_straight is not None else t
                if t - self._t_straight >= self.arm_s:
                    self.state = HOVER
            else:
                if s < self.down and self._t_straight is not None:
                    self.blocked += 1  # bent before it was armed: not a tap
                self._t_straight = None
            return []

        if self.state == HOVER:
            if s > self.hover:
                self._need_straight = False
            if s < self.down and not self._need_straight:
                if pointer_filter.speed > self.max_speed:
                    self.blocked += 1  # the finger curled while the hand was moving: not a tap
                    self._need_straight = True
                    return []
                self.state = TOUCH
                self._t_down = t
                self._down_pos = cursor
                self._latch = pointer_filter.position_at(self._t_last_straight)
            return []

        held = t - self._t_down
        if s > self.up:  # lift
            events = []
            if self.state == TOUCH:
                if held < self.min_touch_s:
                    self.blocked += 1
                elif held <= self.tap_max_s:
                    events.append(ClickEvent(Action.LEFT, self._latch))
            elif self.state == DRAG:
                events.append(ClickEvent(Action.DRAG_END, cursor))
            self.state = HOVER
            return events

        if self.state == TOUCH:
            if math.dist(cursor, self._down_pos) > self.drag_px:
                if held < self.drag_hold_s:
                    self.state = SLID  # slid before settling: cancel, wait for the lift
                    self.blocked += 1
                    return []
                self.state = DRAG
                return [ClickEvent(Action.DRAG_START, self._latch)]
            if held >= self.long_press_s:
                self.state = HELD
                return [ClickEvent(Action.RIGHT, self._latch)]
        return []

    def progress(self):
        """(0..1, state) for the overlay: long-press fill while touching, else how far the finger has bent."""
        if self.state == TOUCH:
            return min(1.0, (self._t_now - self._t_down) / self.long_press_s), self.state
        if self.state in (DRAG, HELD):
            return 1.0, self.state
        if self.state == HOVER and self.straightness is not None:
            return min(1.0, max(0.0, (self.hover - self.straightness) / (self.hover - self.down))), self.state
        return None, self.state

    def status(self):
        s = "-" if self.straightness is None else f"{self.straightness:.2f}"
        hint = {IDLE: "point your finger to arm", HOVER: "ready: tap to click", TOUCH: "touching",
                DRAG: "dragging", HELD: "right-clicked: lift to finish",
                SLID: "touch cancelled (moved too soon): lift"}[self.state]
        return f"touch: {hint} (straightness {s})"
