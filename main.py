"""Conjure: webcam hand tracking as a mouse replacement.

The single process loop. Each stage is a module in pipeline/; this file only
wires them together and owns startup and shutdown.

The loop consumes (timestamp, image, LandmarkFrame | None) from either the live
camera + tracker or a JSONL recording (--replay), so every stage after the
tracker runs identically on recorded sessions.
"""

import argparse
import logging
import sys

import numpy as np

import config
from pipeline.frame_source import CameraError, FrameSource
from pipeline.hand_tracker import HandTracker
from pipeline.preview import QUIT, Preview, draw_hand
from pipeline.recorder import LandmarkRecorder, replay
from pipeline.timing import StageTimer

log = logging.getLogger("conjure")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Conjure: hand-tracking pointer for macOS")
    parser.add_argument("--preview", action="store_true", help="show the debug preview window (p hides it, q quits)")
    parser.add_argument("--camera", type=int, default=config.CAMERA_INDEX, help="camera index")
    parser.add_argument("--record", metavar="PATH", help="record the landmark stream to a JSONL file")
    parser.add_argument("--replay", metavar="PATH", help="run from a JSONL recording instead of the camera")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def make_tracker():
    return HandTracker(config.HAND_MODEL_PATH, config.MAX_HANDS, config.MIN_DETECTION_CONFIDENCE, config.MIN_PRESENCE_CONFIDENCE,
                       config.MIN_TRACKING_CONFIDENCE, config.MIN_HAND_CONFIDENCE, config.MAX_WRIST_JUMP,
                       config.SWAP_HANDEDNESS)


def make_frame_source(camera):
    return FrameSource(camera, config.CAMERA_WIDTH, config.CAMERA_HEIGHT, config.CAMERA_FPS,
                       config.MIRROR, config.CAMERA_WARMUP_FRAMES, config.FPS_SMOOTHING)


def live_stream(source, tracker, timer):
    """Yield (t, image, hand) from the camera, timing capture and tracking."""
    while True:
        with timer.stage("capture", budgeted=False):
            image, t = source.read()
        with timer.stage("track"):
            hand = tracker.process(image, t)
        yield t, image, hand


def replay_stream(path):
    """Yield (t, blank canvas, hand) from a recording at its original pace."""
    for t, hand in replay(path, realtime=True):
        yield t, np.zeros((config.CAMERA_HEIGHT, config.CAMERA_WIDTH, 3), np.uint8), hand


def run_loop(stream, timer, preview, recorder, fps_fn):
    for t, image, hand in stream:
        if recorder is not None:
            recorder.write(t, hand)

        with timer.stage("preview"):
            if preview.enabled:
                lines = [f"{fps_fn():.1f} fps"]
                if hand is not None:
                    draw_hand(image, hand)
                    lines.append(f"{hand.handedness} hand  conf {hand.confidence:.2f}")
                else:
                    lines.append("no hand")
                if recorder is not None:
                    lines.append(f"REC {recorder.frames} frames")
                action = preview.show(image, lines)
                if action == QUIT:
                    return
        timer.end_frame()


def run(args):
    timer = StageTimer(config.FRAME_BUDGET_MS, config.TIMING_LOG_INTERVAL_S)
    preview = Preview(enabled=args.preview)
    recorder = None
    try:
        if args.replay:
            log.info("replaying %s", args.replay)
            run_loop(replay_stream(args.replay), timer, preview, None, lambda: timer.last_summary.get("fps", 0.0))
            return
        source = make_frame_source(args.camera)
        with source, make_tracker() as tracker:
            if args.record:
                recorder = LandmarkRecorder(args.record, name="manual", frame_size=[config.CAMERA_WIDTH, config.CAMERA_HEIGHT],
                                            mirror=config.MIRROR)
                log.info("recording to %s", args.record)
            run_loop(live_stream(source, tracker, timer), timer, preview, recorder, lambda: source.fps)
    finally:
        if recorder is not None:
            recorder.close()
            log.info("saved %d frames to %s", recorder.frames, args.record)
        preview.close()


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log.info("Conjure starting (frame budget %.0f ms). Ctrl+C to quit.", config.FRAME_BUDGET_MS)
    try:
        run(args)
    except CameraError as e:
        log.error("%s", e)
        return 1
    except KeyboardInterrupt:
        pass
    log.info("Conjure stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
