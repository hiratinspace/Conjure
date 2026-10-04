"""CONJ-10: record a custom gesture three times and build a template.

Flow for each of the 3 samples, driven frame by frame by the engine:
  COUNTDOWN (`countdown_s`): hold your hand naturally; the last part of the
      countdown is captured as the "rest" shape.
  RECORD (`sample_s`): perform the gesture.
The sample is trimmed to the frames whose shape differs from rest by more
than `active_threshold` (plus a small margin). If no frame does, the motion
was indistinguishable from the user's normal hand: the sample is rejected
with a message and recorded again. Losing the hand mid-sample also repeats it.

Quality gate: after the third sample the three are compared with each
other. If they would need a threshold above the ceiling to match each other,
they did not look alike, and saving them would give a spell that misfires or
never fires. All three are discarded with a message and recording starts
over (`rejected_sets` counts this).

After 3 good samples, `result()` gives the samples, a generous threshold
derived from their consistency, and warnings (e.g. a gesture too close to the
rest shape, which risks false clicks during ordinary movement). Naming the
spell is the UI's job (CONJ-17); saving is the profile store's (CONJ-13).

`prompt` is the text the overlay shows, so a user can follow along without
the terminal.
"""

import numpy as np

import itertools

from pipeline.gestures import RESAMPLE_N, auto_threshold, normalize, sequence_distance, shape_distance

IDLE, COUNTDOWN, RECORD, DONE = "idle", "countdown", "record", "done"
SAMPLES = 3


class GestureRecorder:
    def __init__(self, aspect, countdown_s, sample_s, active_threshold, margin_frames, threshold_scale,
                 threshold_floor, threshold_ceiling, distinct_factor):
        self.aspect = aspect
        self.countdown_s = countdown_s
        self.sample_s = sample_s
        self.active_threshold = active_threshold
        self.margin_frames = margin_frames
        self.threshold_scale = threshold_scale
        self.threshold_floor = threshold_floor
        self.threshold_ceiling = threshold_ceiling
        self.distinct_factor = distinct_factor
        self.state = IDLE
        self.prompt = ""
        self.message = ""
        self.samples = []
        self.rests = []
        self.rejected_sets = 0
        self._frames = []
        self._rest_frames = []
        self._t_state = None

    @property
    def active(self):
        return self.state in (COUNTDOWN, RECORD)

    def start(self):
        self.samples, self.rests = [], []
        self.message = ""
        self._begin_countdown(None)

    def cancel(self):
        self.state = IDLE
        self.prompt = ""

    def _begin_countdown(self, t):
        self.state = COUNTDOWN
        self._t_state = t
        self._rest_frames = []

    def update(self, hand, t):
        if not self.active:
            return
        if self._t_state is None:
            self._t_state = t
        n = len(self.samples) + 1
        if hand is None:
            if self.state == RECORD:
                self.message = "Lost your hand: let's do that one again."
            self._begin_countdown(t)
            self.prompt = f"Spell sample {n} of {SAMPLES}: show your hand to the camera"
            return

        frame = normalize(hand, self.aspect)
        elapsed = t - self._t_state
        if self.state == COUNTDOWN:
            left = self.countdown_s - elapsed
            self.prompt = f"Spell sample {n} of {SAMPLES}: hold your hand naturally... {max(0, left):.0f}"
            if left <= self.countdown_s / 2:
                self._rest_frames.append(frame)
            if left <= 0:
                self.state = RECORD
                self._t_state = t
                self._frames = []
                self.prompt = f"Spell sample {n} of {SAMPLES}: cast your gesture now!"
            return

        self.prompt = f"Spell sample {n} of {SAMPLES}: cast your gesture now!"
        self._frames.append(frame)
        if elapsed >= self.sample_s:
            self._finish_sample(t)

    def _finish_sample(self, t):
        rest = np.median(np.array(self._rest_frames), axis=0) if self._rest_frames else self._frames[0]
        dist = [shape_distance(f, rest) for f in self._frames]
        active = [i for i, d in enumerate(dist) if d > self.active_threshold]
        if not active:
            self.message = "That looked just like your resting hand. Try a bigger or more distinct gesture."
            self._begin_countdown(t)
            return
        lo = max(0, active[0] - self.margin_frames)
        hi = min(len(self._frames), active[-1] + 1 + self.margin_frames)
        self.samples.append(np.array(self._frames[lo:hi]))
        self.rests.append(rest)
        self.message = ""
        if len(self.samples) == SAMPLES and not self._consistent():
            self.rejected_sets += 1
            self.samples, self.rests = [], []
            self.message = ("Those three didn't look alike: try a bigger, more distinct motion, "
                            "and repeat it the same way each time.")
            self._begin_countdown(t)
            return
        if len(self.samples) == SAMPLES:
            self.state = DONE
            self.prompt = "Spell recorded! Now give it a name."
        else:
            self._begin_countdown(t)

    def _consistent(self):
        spread = max(sequence_distance(a, b) for a, b in itertools.combinations(self.samples, 2))
        return spread * self.threshold_scale <= self.threshold_ceiling

    def result(self, ordinary=None):
        """(samples as nested lists, threshold, warnings). Only valid once state == DONE.

        ordinary: recent normalized frames of the user's normal movement (the engine keeps ~15 s).
        If any stretch of it is as close to a sample as the match threshold, the gesture would
        fire during ordinary use, and a warning says so."""
        threshold = auto_threshold(self.samples, self.threshold_scale, self.threshold_floor, self.threshold_ceiling)
        warnings = []
        for sample, rest in zip(self.samples, self.rests):
            peak = max(shape_distance(f, rest) for f in sample)
            if peak < threshold * self.distinct_factor:
                warnings.append("This gesture is close to your resting hand and may fire during normal use. "
                                "A bigger or more distinct motion will be more reliable.")
                break
        if ordinary is not None and len(ordinary) >= RESAMPLE_N:
            closest = min_window_distance(self.samples, np.asarray(ordinary))
            if closest < threshold:
                warnings.append("Your normal hand movement in the last few seconds already looks like this "
                                "gesture, so it may click by accident. Try a more distinct motion.")
        return [s.round(4).tolist() for s in self.samples], threshold, warnings


def min_window_distance(samples, frames, step=3):
    """Smallest distance between any sample and any same-length stretch of `frames`."""
    best = float("inf")
    for sample in samples:
        n = len(sample)
        if n > len(frames):
            continue
        for start in range(0, len(frames) - n + 1, step):
            best = min(best, sequence_distance(sample, frames[start:start + n]))
    return best
