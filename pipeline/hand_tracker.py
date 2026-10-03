"""CONJ-4: MediaPipe hand tracking, one hand out.

MediaPipe runs with num_hands=config.MAX_HANDS (1). Once it finds a hand it
tracks it from frame to frame by region, skipping palm detection, so it is
both fast and sticky: a second hand entering the frame is not even looked at
until the tracked one is lost. `select_hand` then gates the result, and keeps
selection sticky if MAX_HANDS is ever raised:
  - only hands at or above the confidence threshold count;
  - the hand being tracked stays selected while it is visible (sticky),
    matched by wrist position, not by its Left/Right label, which MediaPipe
    sometimes flips between frames;
  - otherwise the highest-confidence hand wins.
Flapping between two hands would teleport the cursor (build-plan section 4).
"""

import math

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

from pipeline.landmarks import WRIST, LandmarkFrame


def select_hand(candidates, previous, min_confidence, max_wrist_jump):
    """Pick one LandmarkFrame from `candidates`, or None.

    previous: the frame selected last time (None if no hand was tracked).
    max_wrist_jump: normalized distance within which a candidate is "the same hand".
    """
    eligible = [c for c in candidates if c.confidence >= min_confidence]
    if not eligible:
        return None
    if previous is not None:
        px, py = previous.point(WRIST)
        nearest = min(eligible, key=lambda c: math.dist(c.point(WRIST), (px, py)))
        if math.dist(nearest.point(WRIST), (px, py)) <= max_wrist_jump:
            return nearest
    return max(eligible, key=lambda c: c.confidence)


class HandTracker:
    def __init__(self, model_path, max_hands, min_detection_confidence, min_presence_confidence,
                 min_tracking_confidence, min_hand_confidence, max_wrist_jump):
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=max_hands,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self.min_hand_confidence = min_hand_confidence
        self.max_wrist_jump = max_wrist_jump
        self._last_ts_ms = -1
        self._selected = None

    def process(self, frame_bgr, timestamp):
        """Run tracking on one mirrored BGR frame. Returns a LandmarkFrame or None."""
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        # VIDEO mode requires strictly increasing integer milliseconds.
        ts_ms = max(int(timestamp * 1000), self._last_ts_ms + 1)
        self._last_ts_ms = ts_ms
        result = self._landmarker.detect_for_video(image, ts_ms)
        candidates = [
            LandmarkFrame(
                landmarks=tuple((p.x, p.y, p.z) for p in hand),
                handedness=handed[0].category_name,
                confidence=handed[0].score,
                timestamp=timestamp,
            )
            for hand, handed in zip(result.hand_landmarks, result.handedness)
        ]
        self._selected = select_hand(candidates, self._selected, self.min_hand_confidence, self.max_wrist_jump)
        return self._selected

    def close(self):
        self._landmarker.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
