"""Record a named landmark session to recordings/<name>.jsonl for headless replay tests.

Each preset tells you what to do with your hand, counts down 3 seconds in the
preview window, then records for a fixed time. Press q in the preview to stop
early (the partial file is kept).

Usage, from the repo root:
    python scripts/record_session.py --list
    python scripts/record_session.py traversal
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from main import make_frame_source, make_tracker  # noqa: E402
from pipeline.preview import QUIT, Preview, draw_hand  # noqa: E402
from pipeline.recorder import LandmarkRecorder  # noqa: E402

COUNTDOWN_S = 3

PRESETS = {
    "traversal": (60, "Move your hand around the whole frame as if steering a cursor to every corner and edge, "
                      "slow and fast. Do NOT pinch, make a fist, or do any gesture. (0 false-click test)"),
    "pinches": (90, "Make exactly 20 deliberate pinches (thumb tip to index tip, then release), at varied speeds: "
                    "some with the hand still, some while moving. Count them out loud."),
    "idle": (30, "Rest your forearm on the desk with the hand in frame, and hold it as still as is comfortable. "
                 "(jitter test)"),
    "exits": (70, "Move your hand fully out of the frame and back in, 10 times: about 3 s out, 3 s in. "
                  "(auto-pause test)"),
    "small_range": (30, "Rest your forearm on the desk. Move your hand only within a comfortable box of about "
                        "3 inches, tracing its edges and corners a few times. (calibration test)"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("preset", nargs="?", choices=sorted(PRESETS), help="what to record")
    parser.add_argument("--list", action="store_true", help="show presets and instructions")
    parser.add_argument("--camera", type=int, default=config.CAMERA_INDEX)
    parser.add_argument("--out", help="output path (default recordings/<preset>.jsonl)")
    args = parser.parse_args()

    if args.list or not args.preset:
        for name, (secs, text) in PRESETS.items():
            print(f"{name:12} {secs:3d}s  {text}\n")
        return 0

    duration, instructions = PRESETS[args.preset]
    out = Path(args.out) if args.out else config.RECORDINGS_DIR / f"{args.preset}.jsonl"
    print(f"\n{args.preset} ({duration}s): {instructions}\n")
    input("Press Enter to open the camera. Recording starts after a 3 s countdown in the preview window. ")

    preview = Preview(enabled=True)
    source = make_frame_source(args.camera)
    hands = frames = 0
    with source, make_tracker() as tracker:
        start = time.monotonic()
        while True:  # countdown: tracking runs so the hand overlay is live, nothing is recorded
            image, t = source.read()
            hand = tracker.process(image, t)
            if hand is not None:
                draw_hand(image, hand)
            left = COUNTDOWN_S - (t - start)
            if left <= 0:
                break
            if preview.show(image, [f"{args.preset}: starting in {left:.0f}", instructions[:70]]) == QUIT:
                return 1

        with LandmarkRecorder(out, name=args.preset, instructions=instructions, duration_s=duration,
                              frame_size=[config.CAMERA_WIDTH, config.CAMERA_HEIGHT], mirror=config.MIRROR) as rec:
            rec_start = time.monotonic()
            while True:
                image, t = source.read()
                hand = tracker.process(image, t)
                rec.write(t, hand)
                frames += 1
                hands += hand is not None
                left = duration - (t - rec_start)
                if left <= 0:
                    break
                if hand is not None:
                    draw_hand(image, hand)
                lines = [f"REC {args.preset}  {left:.0f}s left", f"{source.fps:.1f} fps",
                         "hand" if hand is not None else "no hand"]
                if preview.show(image, lines) == QUIT:
                    break
    preview.close()

    elapsed = time.monotonic() - rec_start
    print(f"\nSaved {out}")
    print(f"  {frames} frames in {elapsed:.1f}s ({frames / elapsed:.1f} fps), hand visible in {hands} "
          f"({100 * hands / max(frames, 1):.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
