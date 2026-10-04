"""CONJ-9: scroll with the two-finger V pose, used like a joystick.

Pose: index and middle extended, ring and pinky folded. Not a fist: in the
traversal recording a loose fist is the user's natural travel pose, while the
V pose never appeared by accident (PROGRESS.md).

Hold the pose for `enter_s` to start scrolling; the knuckle's height at that
moment is the joystick center. Moving the hand up from the center scrolls up,
down scrolls down, faster the further it goes (after a dead zone, capped at
`max_rate`). Distances are in hand sizes, so it feels the same at any distance
from the camera. Leaving the pose (looser thresholds: hysteresis) for
`exit_s` stops scrolling. The engine freezes the cursor while scrolling, so
moving the hand to scroll does not also move the pointer.
"""

from pipeline.events import Action, ClickEvent
from pipeline.landmarks import INDEX_MCP


class ScrollDetector:
    def __init__(self, extended, folded, exit_extended, exit_folded, enter_s, exit_s, dead_zone, gain, max_rate):
        self.extended = extended
        self.folded = folded
        self.exit_extended = exit_extended
        self.exit_folded = exit_folded
        self.enter_s = enter_s
        self.exit_s = exit_s
        self.dead_zone = dead_zone
        self.gain = gain
        self.max_rate = max_rate
        self.active = False
        self.rate = 0.0
        self._t_pose = None
        self._t_lost = None
        self._center = None
        self._t_last = None
        self._carry = 0.0

    def _in_pose(self, pose, ext, fold):
        return (pose.index_ext > ext and pose.middle_ext > ext and pose.ring_ext < fold and pose.pinky_ext < fold)

    def reset(self):
        self.active = False
        self.rate = 0.0
        self._t_pose = self._t_lost = self._center = self._t_last = None
        self._carry = 0.0

    def update(self, hand, pose, t, cursor):
        """Returns SCROLL events for this frame; sets `active` while the cursor should stay frozen."""
        if hand is None or pose is None:
            self.reset()
            return []
        if not self.active:
            if self._in_pose(pose, self.extended, self.folded):
                if self._t_pose is None:
                    self._t_pose = t
                if t - self._t_pose >= self.enter_s:
                    self.active = True
                    self._center = hand.point(INDEX_MCP)[1]
                    self._t_last = t
                    self._t_lost = None
            else:
                self._t_pose = None
            return []

        if self._in_pose(pose, self.exit_extended, self.exit_folded):
            self._t_lost = None
        else:
            if self._t_lost is None:
                self._t_lost = t
            if t - self._t_lost >= self.exit_s:
                self.reset()
                return []

        offset = (self._center - hand.point(INDEX_MCP)[1]) / max(pose.size, 1e-6)  # + = hand above center
        magnitude = max(0.0, abs(offset) - self.dead_zone)
        self.rate = min(self.max_rate, self.gain * magnitude) * (1 if offset > 0 else -1)
        dt = max(0.0, t - self._t_last)
        self._t_last = t
        self._carry += self.rate * dt
        steps = int(self._carry)
        if steps == 0:
            return []
        self._carry -= steps
        return [ClickEvent(Action.SCROLL, cursor, amount=steps)]

    def status(self):
        if self.active:
            return f"scroll: {self.rate:+.0f} steps/s"
        return "scroll: hold V pose" if self._t_pose is not None else ""
