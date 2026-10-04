"""Conjure: webcam hand tracking as a mouse replacement.

The single process loop. Each stage is a module in pipeline/; this file only
wires them together and owns startup and shutdown.

The loop consumes (timestamp, image, LandmarkFrame | None) from either the live
camera + tracker or a JSONL recording (--replay), and hands each frame to the
Engine, so every stage after the tracker runs identically on recorded sessions.
"""

import argparse
import logging
import sys

import numpy as np

import config
from pipeline.cursor_mapper import Box, BoxCalibration, CursorMapper
from pipeline.engine import Engine
from pipeline.filter import PointerFilter
from pipeline.frame_source import CameraError, FrameSource
from pipeline.hand_tracker import HandTracker
from pipeline.injector import PynputInjector, RecordingInjector
from pipeline.permissions import PermissionWatch, main_screen_size
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
    parser.add_argument("--no-inject", action="store_true", help="dry run: never move the real cursor or click")
    parser.add_argument("--inject", action="store_true", help="with --replay: drive the real cursor from the recording")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def make_tracker():
    return HandTracker(config.HAND_MODEL_PATH, config.MAX_HANDS, config.MIN_DETECTION_CONFIDENCE,
                       config.MIN_PRESENCE_CONFIDENCE, config.MIN_TRACKING_CONFIDENCE, config.MIN_HAND_CONFIDENCE,
                       config.MAX_WRIST_JUMP, config.SWAP_HANDEDNESS)


def make_frame_source(camera):
    return FrameSource(camera, config.CAMERA_WIDTH, config.CAMERA_HEIGHT, config.CAMERA_FPS,
                       config.MIRROR, config.CAMERA_WARMUP_FRAMES, config.FPS_SMOOTHING)


def make_pointer_filter(screen_size):
    return PointerFilter(config.FILTER_MIN_CUTOFF, config.FILTER_BETA, config.FILTER_D_CUTOFF, config.PRECISION_GAIN,
                         config.PRECISION_SPEED_PX_S, config.FAST_SPEED_PX_S, config.REANCHOR_RATE, screen_size,
                         config.POSITION_HISTORY_FRAMES)


def make_engine(injector, timer, screen_size):
    calibration = BoxCalibration(Box(**config.DEFAULT_CALIBRATION), screen_size, config.SENSITIVITY)
    return Engine(CursorMapper(calibration), make_pointer_filter(screen_size), injector, timer)


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


def run_loop(stream, engine, timer, preview, recorder, fps_fn, permissions=None):
    for t, image, hand in stream:
        if recorder is not None:
            recorder.write(t, hand)
        result = engine.step(t, hand)
        if permissions is not None and not permissions.poll():
            result.lines.insert(0, "!!! NO ACCESSIBILITY PERMISSION: input is being dropped !!!")

        with timer.stage("preview"):
            if preview.enabled:
                if hand is not None:
                    draw_hand(image, hand)
                lines = [f"{fps_fn():.1f} fps"] + result.lines
                if recorder is not None:
                    lines.append(f"REC {recorder.frames} frames")
                if preview.show(image, lines) == QUIT:
                    return
        timer.end_frame()


def run(args):
    timer = StageTimer(config.FRAME_BUDGET_MS, config.TIMING_LOG_INTERVAL_S)
    preview = Preview(enabled=args.preview)
    screen_size = main_screen_size()
    dry_run = args.no_inject or (args.replay and not args.inject)
    injector = RecordingInjector() if dry_run else PynputInjector()
    permissions = None if dry_run else PermissionWatch(config.PERMISSION_CHECK_INTERVAL_S)
    engine = make_engine(injector, timer, screen_size)
    log.info("screen %dx%d, %s", *screen_size, "dry run (no real input)" if dry_run else "driving the real cursor")
    recorder = None
    try:
        if args.replay:
            log.info("replaying %s", args.replay)
            run_loop(replay_stream(args.replay), engine, timer, preview, None,
                     lambda: timer.last_summary.get("fps", 0.0), permissions)
            return
        source = make_frame_source(args.camera)
        with source, make_tracker() as tracker:
            if args.record:
                recorder = LandmarkRecorder(args.record, name="manual", frame_size=[config.CAMERA_WIDTH, config.CAMERA_HEIGHT],
                                            mirror=config.MIRROR)
                log.info("recording to %s", args.record)
            run_loop(live_stream(source, tracker, timer), engine, timer, preview, recorder, lambda: source.fps,
                     permissions)
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
