"""Synthetic hands for headless tests.

`make_hand` builds a plausible right hand as a LandmarkFrame: wrist at `wrist`,
fingers pointing up the frame, overall size `scale` (wrist to middle MCP in
normalized units). Shape options:
  pinch:  0 = thumb and finger apart (ratio ~1.1), 1 = tips touching
  finger: which finger pinches with the thumb ("index" or "middle")
  curled: middle, ring, and pinky folded into the palm (a loose fist)
  v_pose: index and middle extended, ring and pinky folded (the scroll pose)
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
_FINGER_TIP = {"index": 8, "middle": 12}
_FOLDED = {  # joints pulled back toward the palm
    10: (0.0, 1.2), 11: (0.05, 0.95), 12: (0.05, 0.75),
    14: (0.28, 1.15), 15: (0.3, 0.95), 16: (0.3, 0.75),
    18: (0.5, 1.0), 19: (0.5, 0.85), 20: (0.48, 0.7),
}


def hand_points(pinch=0.0, finger="index", curled=False, v_pose=False):
    pts = list(_OPEN_HAND)
    if curled:
        for i, p in _FOLDED.items():
            pts[i] = p
    if v_pose:
        for i in (14, 15, 16, 18, 19, 20):
            pts[i] = _FOLDED[i]
    if pinch:
        tip = _FINGER_TIP[finger]
        thumb, other = pts[4], pts[tip]
        meet = ((thumb[0] + other[0]) / 2, (thumb[1] + other[1]) / 2)
        pts[4] = (thumb[0] + pinch * (meet[0] - thumb[0]), thumb[1] + pinch * (meet[1] - thumb[1]))
        pts[tip] = (other[0] + pinch * (meet[0] - other[0]), other[1] + pinch * (meet[1] - other[1]))
    return pts


def make_hand(wrist=(0.5, 0.7), scale=0.15, timestamp=0.0, handedness="Right", confidence=0.95, points=None,
              **shape):
    wx, wy = wrist
    pts = points if points is not None else hand_points(**shape)
    landmarks = tuple((wx + hx * scale, wy - hy * scale, 0.0) for hx, hy in pts)
    return LandmarkFrame(landmarks=landmarks, handedness=handedness, confidence=confidence, timestamp=timestamp)


def stream(segments, fps=30, start=0.0):
    """Build [(t, LandmarkFrame | None)] from [(duration_s, kwargs-for-make_hand or None)].
    A kwargs value may be a function of the fraction through its segment (0..1)."""
    frames, t = [], start
    for duration, spec in segments:
        n = max(1, round(duration * fps))
        for i in range(n):
            if spec is None:
                frames.append((t, None))
            else:
                frac = i / max(1, n - 1)
                kw = {k: (v(frac) if callable(v) else v) for k, v in spec.items()}
                frames.append((t, make_hand(timestamp=t, **kw)))
            t += 1.0 / fps
    return frames
