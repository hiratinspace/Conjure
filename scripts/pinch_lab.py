"""Pinch lab: see exactly why a pinch does or does not click. Never clicks anything for real.

Shows the camera with three live gauges, each with its threshold line, red
when it is the thing blocking the click:
  1. Fingertips: how close thumb and index tips are (must pass the line)
  2. Pinch speed: how fast the fingers closed, from open to touching
     (must be under the line: a deliberate pinch snaps shut, a relaxing hand drifts)
  3. Hand speed: how fast the hand moves (must stay below the line)
and a big status: READY, PINCHED, CLICK!, or BLOCKED with the reason.

The session is saved to recordings/lab-<time>.jsonl so the thresholds can be
tuned on real pinches. Usage, from the repo root:
    python scripts/pinch_lab.py          # q or Esc to finish
"""

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import config  # noqa: E402
from main import make_engine, make_frame_source, make_tracker  # noqa: E402
from pipeline.events import Action  # noqa: E402
from pipeline.injector import RecordingInjector  # noqa: E402
from pipeline.modes import Mode, ModeState  # noqa: E402
from pipeline.permissions import main_screen_size  # noqa: E402
from pipeline.preview import draw_hand  # noqa: E402
from pipeline.recorder import LandmarkRecorder  # noqa: E402
from pipeline.timing import StageTimer  # noqa: E402

PANEL_W = 460
GREEN, RED, GREY, WHITE, GOLD = (90, 200, 90), (60, 60, 230), (120, 120, 120), (255, 255, 255), (66, 197, 245)
FONT = cv2.FONT_HERSHEY_SIMPLEX
WINDOW = "Conjure pinch lab (q to finish)"


def gauge(panel, y, label, value, lo, hi, line, ok, text):
    """Horizontal bar: value in [lo, hi], a threshold mark at `line`, green when ok else red."""
    x0, x1 = 20, PANEL_W - 20
    cv2.putText(panel, label, (x0, y), FONT, 0.62, WHITE, 1, cv2.LINE_AA)
    cv2.putText(panel, text, (x1 - 150, y), FONT, 0.62, WHITE, 1, cv2.LINE_AA)
    top, bottom = y + 10, y + 42
    cv2.rectangle(panel, (x0, top), (x1, bottom), GREY, 2)
    if value is not None:
        frac = min(1.0, max(0.0, (value - lo) / (hi - lo)))
        cv2.rectangle(panel, (x0 + 2, top + 2), (x0 + 2 + int((x1 - x0 - 4) * frac), bottom - 2), GREEN if ok else RED, -1)
    lx = x0 + int((x1 - x0) * min(1.0, max(0.0, (line - lo) / (hi - lo))))
    cv2.line(panel, (lx, top - 6), (lx, bottom + 6), GOLD, 3)


def main():
    out = config.RECORDINGS_DIR / f"lab-{datetime.now():%Y%m%d-%H%M%S}.jsonl"
    screen = main_screen_size()
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(1e9, 1e9), screen, ModeState(Mode.PINCH))
    from pipeline.profile_store import ProfileStore
    profile, _ = ProfileStore(config.PROFILE_PATH).load()
    engine.apply_profile(profile)  # the same tuned thresholds the app uses
    print(f"thresholds: engage {engine.pinch.left.engage:.2f}, release {engine.pinch.left.release:.2f}, "
          f"snap window {(engine.pinch.left.quick_close_s or 0) * 1000:.0f} ms"
          + (" (tuned to you)" if engine.pinch_engage or engine.pinch_close_s else " (defaults; press Tune in the app)"))
    left = engine.pinch.left
    clicks, blocked, flash_until = 0, {}, 0.0
    last_reason = ""
    t_open, close_ms, was_closed = None, None, False

    print(__doc__.split("Usage")[0])
    source = make_frame_source(config.CAMERA_INDEX)
    with source, make_tracker() as tracker, LandmarkRecorder(
            out, name="lab", instructions="pinch lab: free pinching", frame_size=[config.CAMERA_WIDTH,
                                                                                 config.CAMERA_HEIGHT],
            mirror=config.MIRROR) as rec:
        while True:
            image, t = source.read()
            hand = tracker.process(image, t)
            rec.write(t, hand)
            result = engine.step(t, hand)
            for e in result.events:
                if e.action in (Action.LEFT, Action.RIGHT, Action.DRAG_START):
                    clicks += 1
                    flash_until = time.monotonic() + 0.6
            if left.block_reason and left.block_reason != last_reason:
                blocked[left.block_reason] = blocked.get(left.block_reason, 0) + 1
            last_reason = left.block_reason

            panel = np.full((config.CAMERA_HEIGHT, PANEL_W, 3), 30, np.uint8)
            ratio = left.ratio
            if ratio is not None and ratio >= left.release:
                t_open = t
            closed = ratio is not None and ratio < left.engage
            if closed and not was_closed:  # just closed: how long since the fingers were open?
                close_ms = (t - t_open) * 1000 if t_open is not None and t - t_open < 1.0 else 999
            was_closed = closed
            # 1. fingertips: show closeness, so "more full" = closer; the line is the engage ratio
            closeness = None if ratio is None else max(0.0, 1.0 - ratio)
            gauge(panel, 40, "1. Fingertips together", closeness, 0.0, 1.0, 1.0 - left.engage,
                  ratio is not None and ratio < left.engage, "-" if ratio is None else f"{ratio:.2f}")
            limit_ms = (left.quick_close_s or 1.0) * 1000
            gauge(panel, 130, "2. Pinch speed (ms to close)", close_ms, 0.0, 600.0, limit_ms,
                  close_ms is not None and close_ms <= limit_ms, "-" if close_ms is None else f"{close_ms:.0f} ms")
            speed = engine.filter.speed if hand is not None else None
            gauge(panel, 220, "3. Hand still enough", speed, 0.0, 1200.0, left.max_speed or 1e9,
                  speed is not None and speed <= (left.max_speed or 1e9), "-" if speed is None else f"{speed:.0f}")

            if hand is None:
                status, color = "NO HAND", GREY
            elif time.monotonic() < flash_until:
                status, color = "CLICK!", GOLD
            elif left.block_reason:
                status, color = "BLOCKED", RED
            elif left.state in ("pending", "confirmed", "dragging"):
                status, color = "PINCHED: let go", GREEN
            else:
                status, color = "READY", WHITE
            cv2.putText(panel, status, (20, 340), FONT, 1.4, color, 3, cv2.LINE_AA)
            if left.block_reason:
                cv2.putText(panel, left.block_reason, (20, 380), FONT, 0.75, RED, 2, cv2.LINE_AA)
            cv2.putText(panel, f"clicks: {clicks}", (20, 440), FONT, 0.9, WHITE, 2, cv2.LINE_AA)

            if hand is not None:
                draw_hand(image, hand)
            cv2.imshow(WINDOW, np.hstack([image, panel]))
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break
        frames = rec.frames
    cv2.destroyAllWindows()

    print("\n===== Pinch lab summary (paste this back) =====")
    print(f"clicks counted: {clicks}")
    print("pinches blocked:", ", ".join(f"{k}: {v}" for k, v in blocked.items()) or "none")
    print(f"saved {frames} frames to {out}")
    print("===============================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
