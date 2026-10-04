"""CONJ-11: recognize the recorded custom gesture in the live stream.

Every frame, the last stretch of normalized hand shapes is compared with each
of the template's 3 samples, at a few window lengths around the sample's own
(`scales`), so casting a bit faster or slower still matches. The best
distance below `threshold x match_scale` fires the mapped click, at the
cursor position from when the gesture began (the gesture's own motion moves
the knuckle).

After firing, the matcher is disarmed until the distance rises above
`threshold x rearm_factor`: holding the gesture fires once, not repeatedly.
It also starts disarmed, and a lost hand clears the buffer, since a gesture
cannot span a gap. `refractory_s` caps the match rate.

Scope: one gesture (scope.md section 4). The matcher loops over a list only
so the code does not change when that limit is lifted.
"""

from collections import deque

from pipeline.events import Action, ClickEvent
from pipeline.gestures import normalize, sequence_distance


class GestureMatcher:
    def __init__(self, aspect, scales, match_scale, rearm_factor, refractory_s, buffer_frames):
        self.aspect = aspect
        self.scales = scales
        self.match_scale = match_scale
        self.rearm_factor = rearm_factor
        self.refractory_s = refractory_s
        self._buffer = deque(maxlen=buffer_frames)  # (t, normalized frame)
        self.templates = []
        self.armed = False
        self.distance = None
        self.last_match = None  # name of the last gesture fired (spell flash, voice)
        self._t_fired = None

    def configure(self, match_scale=None):
        """Live-tune how strict matching is (settings panel). >1 is more forgiving."""
        if match_scale is not None:
            self.match_scale = match_scale

    def set_templates(self, templates):
        self.templates = list(templates)
        self.armed = False

    def reset(self):
        self._buffer.clear()
        self.armed = False
        self.distance = None

    def _best(self, template):
        frames = [f for _, f in self._buffer]
        best, best_len = float("inf"), None
        for sample in template.samples:
            for scale in self.scales:
                n = max(2, round(len(sample) * scale))
                if n > len(frames):
                    continue
                d = sequence_distance(sample, frames[-n:])
                if d < best:
                    best, best_len = d, n
        return best, best_len

    def update(self, hand, t, pointer_filter):
        """Returns the ClickEvents fired this frame."""
        if hand is None:
            self.reset()
            return []
        self._buffer.append((t, normalize(hand, self.aspect)))
        if not self.templates:
            return []
        for template in self.templates:
            d, n = self._best(template)
            self.distance = d
            limit = template.threshold * self.match_scale
            if not self.armed:
                if d > limit * self.rearm_factor:
                    self.armed = True
                continue
            in_refractory = self._t_fired is not None and t - self._t_fired < self.refractory_s
            if d < limit and not in_refractory:
                self.armed = False
                self._t_fired = t
                self.last_match = template.name
                t_start = self._buffer[-n][0]
                return [ClickEvent(Action.LEFT, pointer_filter.position_at(t_start))]
        return []

    def status(self):
        if not self.templates:
            return "custom: no spell recorded (press g)"
        d = "-" if self.distance is None or self.distance == float("inf") else f"{self.distance:.2f}"
        limit = self.templates[0].threshold * self.match_scale
        return f"custom '{self.templates[0].name}': dist {d} / {limit:.2f} {'armed' if self.armed else 'rearming'}"
