"""Diagnose "the preview doesn't show my hand": no window needed.

Captures a few seconds from the camera, runs the tracker on every frame, and
prints what it found: resolution, frame rate, brightness, and how often a hand
was detected (with MediaPipe's raw output, before our confidence gate). Saves
snapshots with the overlay to logs/diagnose_*.jpg so they can be inspected.

Usage, from the repo root, with your hand up in front of the camera:
    python scripts/diagnose_tracking.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import mediapipe as mp  # noqa: E402

import config  # noqa: E402
from main import make_frame_source, make_tracker  # noqa: E402
from pipeline.preview import draw_hand, draw_text_lines  # noqa: E402

SECONDS = 5
OUT_DIR = config.ROOT / "logs"


def main():
    OUT_DIR.mkdir(exist_ok=True)
    print(f"Hold your hand up in front of the camera, palm facing it. Capturing for {SECONDS} s...")
    frames = raw_hands = selected = 0
    brightness = []
    scores = []
    snapshot_hand = snapshot_last = None
    source = make_frame_source(config.CAMERA_INDEX)
    with source, make_tracker() as tracker:
        start = time.monotonic()
        while time.monotonic() - start < SECONDS:
            image, t = source.read()
            hand = tracker.process(image, t)
            frames += 1
            brightness.append(float(image.mean()))
            # Raw MediaPipe output on the same frame, before select_hand's gate.
            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            result = tracker._landmarker.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), tracker._last_ts_ms + 1)
            tracker._last_ts_ms += 1
            raw_hands += bool(result.hand_landmarks)
            scores += [h[0].score for h in result.handedness]
            if hand is not None:
                selected += 1
                snapshot_hand = (image.copy(), hand)
            snapshot_last = image.copy()
        elapsed = time.monotonic() - start

    h, w = snapshot_last.shape[:2]
    mean_b = sum(brightness) / len(brightness)
    print("\n===== Conjure tracking diagnosis (paste this block back) =====")
    print(f"Frames:      {frames} in {elapsed:.1f}s ({frames / elapsed:.1f} fps), size {w}x{h}")
    print(f"Brightness:  mean {mean_b:.0f}/255 (under ~60 is too dark for tracking)")
    print(f"MediaPipe:   hand found in {raw_hands}/{frames} frames"
          + (f", handedness scores {min(scores):.2f}-{max(scores):.2f}" if scores else ""))
    print(f"Selected:    hand passed our gate (>= {config.MIN_HAND_CONFIDENCE}) in {selected}/{frames} frames")

    last_path = OUT_DIR / "diagnose_last.jpg"
    draw_text_lines(snapshot_last, ["last frame"])
    cv2.imwrite(str(last_path), snapshot_last)
    print(f"Saved:       {last_path}")
    if snapshot_hand is not None:
        image, hand = snapshot_hand
        draw_hand(image, hand)
        hand_path = OUT_DIR / "diagnose_hand.jpg"
        cv2.imwrite(str(hand_path), image)
        print(f"Saved:       {hand_path}")
    print("===============================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
