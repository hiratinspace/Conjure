"""CONJ-10: record a custom gesture three times and build a template.

Flow for each of the 3 samples, driven frame by frame by the engine:
  COUNTDOWN (`countdown_s`): hold your hand naturally; the last part of the
      countdown is captured as the "rest" shape.
  RECORD (`sample_s`): perform the gesture.
A spell is a hand shape, so the sample is trimmed to the shape the user
held: the frames around the peak distance from rest that stay within
`plateau_fraction` of that peak, cut to `max_frames` around the peak. The
transitions into and out of the shape are left out on purpose: their timing
differs on every take (a quick flick, a slow change, a long hold), and keeping
them made three honest repeats of one shape fail the consistency gate. If no
frame differs from rest by more than `active_threshold`, the motion was
indistinguishable from the user's normal hand: the sample is rejected with a
message and recorded again. Losing the hand mid-sample also repeats it.

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

import logging

import numpy as np

import itertools

from pipeline.gestures import RESAMPLE_N, auto_threshold, normalize, sequence_distance, shape_distance

log = logging.getLogger("conjure.recorder")

IDLE, COUNTDOWN, RECORD, DONE = "idle", "countdown", "record", "done"
HOW = "a hand shape, like opening a fist, a thumbs up, or a V. Moving the whole hand is pointing, not a spell."
SAMPLES = 3


class GestureRecorder:
    def __init__(self, aspect, countdown_s, sample_s, active_threshold, plateau_fraction, max_frames, min_frames,
                 threshold_scale, threshold_floor, threshold_ceiling, distinct_factor):
        self.aspect = aspect
        self.countdown_s = countdown_s
        self.sample_s = sample_s
        self.active_threshold = active_threshold
        self.plateau_fraction = plateau_fraction
        self.max_frames = max_frames
        self.min_frames = min_frames
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
                log.info("recorder: hand lost during sample %d, repeating", n)
            self._begin_countdown(t)
            self.prompt = f"Spell sample {n} of {SAMPLES}: show your hand to the camera"
            return

        frame = normalize(hand, self.aspect)
        elapsed = t - self._t_state
        if self.state == COUNTDOWN:
            left = self.countdown_s - elapsed
            self.prompt = f"Spell sample {n} of {SAMPLES}: rest your hand in its normal shape... {max(0, left):.0f}"
            if left >= self.countdown_s / 2:  # the first half, before the user starts to get ready
                self._rest_frames.append(frame)
            if left <= 0:
                self.state = RECORD
                self._t_state = t
                self._frames = []
                self.prompt = f"Spell sample {n} of {SAMPLES}: make the shape and hold it for a second!"
                log.info("recorder: sample %d window open", n)
            return

        self.prompt = f"Spell sample {n} of {SAMPLES}: make the shape and hold it for a second!"
        self._frames.append(frame)
        if elapsed >= self.sample_s:
            self._finish_sample(t)

    def _finish_sample(self, t):
        rest = np.median(np.array(self._rest_frames), axis=0) if self._rest_frames else self._frames[0]
        dist = [shape_distance(f, rest) for f in self._frames]
        active = [i for i, d in enumerate(dist) if d > self.active_threshold]
        if not active:
            self.message = f"No shape change seen. A spell is {HOW}"
            log.info("recorder: sample %d rejected, no shape change (max distance from rest %.2f, need > %.2f)",
                     len(self.samples) + 1, max(dist), self.active_threshold)
            self._begin_countdown(t)
            return
        lo, hi = self._plateau(dist)
        if hi - lo < self.min_frames:
            self.message = "That shape went by too fast to see. Make the shape and hold it for a moment."
            log.info("recorder: sample %d rejected, plateau of %d frames is shorter than %d",
                     len(self.samples) + 1, hi - lo, self.min_frames)
            self._begin_countdown(t)
            return
        self.samples.append(np.array(self._frames[lo:hi]))
        self.rests.append(rest)
        self.message = ""
        log.info("recorder: sample %d accepted (%d frames held of %d active, peak distance %.2f)",
                 len(self.samples), hi - lo, len(active), max(dist))
        if len(self.samples) == SAMPLES and not self._consistent():
            self.rejected_sets += 1
            self.samples, self.rests = [], []
            self.message = ("Those three didn't look alike: use one clear shape change and repeat it the same "
                            "way each time.")
            self._begin_countdown(t)
            return
        if len(self.samples) == SAMPLES:
            self.state = DONE
            self.prompt = "Spell recorded! Now give it a name."
            log.info("recorder: three samples accepted")
        else:
            self._begin_countdown(t)

    def _plateau(self, dist):
        """[lo, hi) of the held shape: the frames around the peak that stay within plateau_fraction of it,
        cut to max_frames around the peak."""
        peak = int(np.argmax(dist))
        floor = max(self.active_threshold, self.plateau_fraction * dist[peak])
        lo = peak
        while lo > 0 and dist[lo - 1] >= floor:
            lo -= 1
        hi = peak + 1
        while hi < len(dist) and dist[hi] >= floor:
            hi += 1
        if hi - lo > self.max_frames:
            lo = max(lo, peak - self.max_frames // 2)
            hi = min(hi, lo + self.max_frames)
        return lo, hi

    def _consistent(self):
        pairs = [sequence_distance(a, b) for a, b in itertools.combinations(self.samples, 2)]
        spread = max(pairs)
        ok = spread * self.threshold_scale <= self.threshold_ceiling
        log.info("recorder: sample spread %s, need each <= %.2f: %s", " ".join(f"{p:.2f}" for p in pairs),
                 self.threshold_ceiling / self.threshold_scale, "consistent" if ok else "rejected, starting over")
        return ok

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
