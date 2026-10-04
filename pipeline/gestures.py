"""Custom gesture math (CONJ-10 recorder + CONJ-11 matcher): normalize, compare, threshold.

Normalization makes a hand shape independent of where the hand is and how far
from the camera: subtract the wrist, divide by hand size (wrist to middle
MCP), in aspect-corrected units. Subtracting the wrist per frame also removes
whole-hand travel, so moving the cursor around is never a gesture: only
changes of hand *shape* over time are.

A sample is a sequence of normalized frames, shape (T, 21, 3). Sequences are
compared by resampling both to `RESAMPLE_N` frames and taking the mean
per-landmark distance (in hand sizes). The matcher tries a few window lengths
around each sample's own length, which tolerates casting faster or slower
than when recording.
"""

import itertools
import math

import numpy as np

from pipeline.landmarks import MIDDLE_MCP, WRIST

RESAMPLE_N = 16
Z_WEIGHT = 0.5  # MediaPipe depth is noisier than x/y


def normalize(hand, aspect):
    """LandmarkFrame -> (21, 3) array: wrist at the origin, hand size 1."""
    a = hand.as_array()
    a[:, 0] *= aspect
    a[:, 2] *= aspect * Z_WEIGHT
    a -= a[WRIST]
    size = math.hypot(a[MIDDLE_MCP, 0], a[MIDDLE_MCP, 1]) or 1e-6
    return a / size


def resample(seq, n=RESAMPLE_N):
    """(T, 21, 3) -> (n, 21, 3) by linear interpolation in time. A single frame is repeated."""
    seq = np.asarray(seq, dtype=np.float64)
    t = len(seq)
    if t == 1:
        return np.repeat(seq, n, axis=0)
    pos = np.linspace(0, t - 1, n)
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, t - 1)
    w = (pos - lo)[:, None, None]
    return seq[lo] * (1 - w) + seq[hi] * w


def sequence_distance(a, b):
    """Mean per-landmark distance between two sequences, in hand sizes."""
    ra, rb = resample(a), resample(b)
    return float(np.linalg.norm(ra - rb, axis=2).mean())


def shape_distance(frame, rest):
    """Mean per-landmark distance between one normalized frame and a rest shape."""
    return float(np.linalg.norm(np.asarray(frame) - np.asarray(rest), axis=1).mean())


def auto_threshold(samples, scale, floor, ceiling):
    """Generous threshold from how consistent the samples are with each other."""
    pairs = [sequence_distance(a, b) for a, b in itertools.combinations(samples, 2)]
    spread = max(pairs) if pairs else 0.0
    return float(min(ceiling, max(floor, scale * spread)))
