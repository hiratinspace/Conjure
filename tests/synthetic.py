"""Synthetic hands for headless tests.

`make_hand` builds a plausible open right hand as a LandmarkFrame: wrist at
`wrist`, fingers pointing up the frame, overall size `scale` (wrist to middle
MCP distance in normalized units).
"""

from pipeline.landmarks import LandmarkFrame

# Open right hand in hand units (wrist at origin, wrist->middle MCP = 1, y up the hand).
_OPEN_HAND = [
    (0.0, 0.0),  # 0 wrist
    (-0.35, 0.25), (-0.6, 0.5), (-0.8, 0.75), (-0.95, 1.0),  # thumb
    (-0.3, 0.95), (-0.35, 1.4), (-0.38, 1.7), (-0.4, 1.95),  # index
    (0.0, 1.0), (0.0, 1.5), (0.0, 1.85), (0.0, 2.1),  # middle
    (0.25, 0.95), (0.3, 1.4), (0.32, 1.7), (0.34, 1.9),  # ring
    (0.48, 0.85), (0.55, 1.2), (0.6, 1.4), (0.63, 1.6),  # pinky
]


def make_hand(wrist=(0.5, 0.7), scale=0.15, timestamp=0.0, handedness="Right", confidence=0.95, points=None):
    wx, wy = wrist
    pts = points if points is not None else _OPEN_HAND
    landmarks = tuple((wx + hx * scale, wy - hy * scale, 0.0) for hx, hy in pts)
    return LandmarkFrame(landmarks=landmarks, handedness=handedness, confidence=confidence, timestamp=timestamp)
