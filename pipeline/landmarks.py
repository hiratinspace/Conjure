"""FROZEN CONTRACT: LandmarkFrame, the landmark bus (CONJ-4, build-plan section 1).

Every stage downstream of the tracker consumes this type: cursor mapping,
filter, pinch, dwell, the gesture recorder and matcher, auto-pause, and the
JSONL recordings. Import it; do not change its fields. A field change means
re-recording every session in recordings/.

Coordinates: x and y are normalized to [0, 1] of the mirrored camera frame
(x grows to the user's right, y grows downward). z is MediaPipe's relative
depth, roughly in the same units as x, smaller is closer to the camera.
"""

from dataclasses import dataclass

import numpy as np

NUM_LANDMARKS = 21

# MediaPipe hand landmark indices used downstream.
WRIST = 0
THUMB_TIP = 4
INDEX_MCP = 5
INDEX_TIP = 8
MIDDLE_MCP = 9
MIDDLE_TIP = 12
RING_TIP = 16
PINKY_MCP = 17
PINKY_TIP = 20

# Bones for drawing the overlay.
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)


@dataclass(frozen=True, slots=True)
class LandmarkFrame:
    landmarks: tuple  # NUM_LANDMARKS tuples of (x, y, z) floats
    handedness: str  # "Left" or "Right", from the user's point of view
    confidence: float  # handedness classification score, 0..1
    timestamp: float  # seconds, time.monotonic() at camera read

    def __post_init__(self):
        if len(self.landmarks) != NUM_LANDMARKS:
            raise ValueError(f"LandmarkFrame needs {NUM_LANDMARKS} landmarks, got {len(self.landmarks)}")
        if self.handedness not in ("Left", "Right"):
            raise ValueError(f"handedness must be 'Left' or 'Right', got {self.handedness!r}")

    def as_array(self):
        """(21, 3) float array, a fresh copy each call."""
        return np.asarray(self.landmarks, dtype=np.float64)

    def point(self, index):
        """(x, y) of one landmark."""
        x, y, _ = self.landmarks[index]
        return x, y
