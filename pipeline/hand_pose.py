"""Per-frame hand shape measurements shared by pinch, scroll, and the overlay.

All distances are measured in aspect-corrected frame units (x scaled by
width/height, so a circle stays a circle) and divided by hand size (wrist to
middle MCP), which makes them independent of distance from the camera.

Findings from the recordings that shaped these measures (PROGRESS.md):
- A curled hand puts the thumb tip on the index finger, which looks like a
  pinch in 2D. So a pinch only counts with the other fingers open
  (`extension`), and a fist cannot be the scroll gesture, since it is a
  natural resting pose while moving the cursor.
- With the hand near the camera the wrist is often below the frame. Only the
  fingertip landmarks need to be inside the frame for a pinch to be trusted
  (`index_pinch_inside`, `middle_pinch_inside`), not the whole hand.
"""

import math
from dataclasses import dataclass

from pipeline.landmarks import INDEX_TIP, MIDDLE_MCP, MIDDLE_TIP, PINKY_TIP, RING_TIP, THUMB_TIP, WRIST

THUMB_REGION = (2, 3, 4)
INDEX_REGION = (6, 7, 8)
MIDDLE_REGION = (10, 11, 12)
FINGER_TIPS = (INDEX_TIP, MIDDLE_TIP, RING_TIP, PINKY_TIP)


@dataclass(frozen=True)
class HandPose:
    size: float  # wrist to middle MCP, aspect-corrected frame units
    pinch_index: float  # thumb tip to index tip / size
    pinch_middle: float  # thumb tip to middle tip / size
    extension: tuple  # (index, middle, ring, pinky): fingertip to wrist / size. Open ~2.0, curled < 1.0
    index_pinch_inside: bool  # thumb and index tip joints at least edge_margin inside the frame
    middle_pinch_inside: bool  # thumb and middle tip joints likewise

    @property
    def index_ext(self):
        return self.extension[0]

    @property
    def middle_ext(self):
        return self.extension[1]

    @property
    def ring_ext(self):
        return self.extension[2]

    @property
    def pinky_ext(self):
        return self.extension[3]


def analyze(hand, aspect, edge_margin):
    lm = hand.landmarks

    def pt(i):
        return lm[i][0] * aspect, lm[i][1]

    size = math.dist(pt(WRIST), pt(MIDDLE_MCP)) or 1e-6
    thumb = pt(THUMB_TIP)

    def inside(indices):
        return all(edge_margin <= lm[i][0] <= 1 - edge_margin and edge_margin <= lm[i][1] <= 1 - edge_margin
                   for i in indices)

    return HandPose(
        size=size,
        pinch_index=math.dist(thumb, pt(INDEX_TIP)) / size,
        pinch_middle=math.dist(thumb, pt(MIDDLE_TIP)) / size,
        extension=tuple(math.dist(pt(WRIST), pt(k)) / size for k in FINGER_TIPS),
        index_pinch_inside=inside(THUMB_REGION + INDEX_REGION),
        middle_pinch_inside=inside(THUMB_REGION + MIDDLE_REGION),
    )

