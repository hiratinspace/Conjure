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
from pipeline.action_mapper import ActionMapper
from pipeline.cursor_mapper import Box, BoxCalibration, CursorMapper
from pipeline.dwell import DwellDetector
from pipeline.engine import Engine
from pipeline.filter import PointerFilter
from pipeline.frame_source import CameraError, FrameSource
from pipeline.gesture_recorder import GestureRecorder
from pipeline.hand_tracker import HandTracker
from pipeline.injector import PynputInjector, RecordingInjector
from pipeline.modes import Mode, ModeState
from pipeline.permissions import PermissionWatch, main_screen_size
from pipeline.pinch import PinchDetector
from pipeline.scroll import ScrollDetector
from pipeline.preview import QUIT, Preview, draw_hand
from pipeline.recorder import LandmarkRecorder, replay
from pipeline.timing import StageTimer

log = logging.getLogger("conjure")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Conjure: hand-tracking pointer for macOS")
    parser.add_argument("--preview", action="store_true", help="show the debug preview window (p hides it, q quits)")
    parser.add_argument("--no-ui", action="store_true",
                        help="no overlay: single-thread loop with the OpenCV preview (debugging fallback)")
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


def make_pinch():
    return PinchDetector(config.PINCH_ENGAGE_RATIO, config.PINCH_RELEASE_RATIO, config.PINCH_HOLD_MS / 1000,
                         config.PINCH_OPEN_EXTENSION, config.DRAG_START_PX, config.PINCH_LATCH_LOOKBACK_S)


def make_scroll():
    return ScrollDetector(config.SCROLL_EXTENDED, config.SCROLL_FOLDED, config.SCROLL_EXIT_EXTENDED,
                          config.SCROLL_EXIT_FOLDED, config.SCROLL_ENTER_MS / 1000, config.SCROLL_EXIT_MS / 1000,
                          config.SCROLL_DEAD_ZONE, config.SCROLL_GAIN, config.SCROLL_MAX_RATE)


def make_gesture_recorder():
    return GestureRecorder(config.CAMERA_WIDTH / config.CAMERA_HEIGHT, config.GESTURE_COUNTDOWN_S,
                           config.GESTURE_SAMPLE_S, config.GESTURE_ACTIVE_THRESHOLD, config.GESTURE_MARGIN_FRAMES,
                           config.GESTURE_THRESHOLD_SCALE, config.GESTURE_THRESHOLD_FLOOR,
                           config.GESTURE_THRESHOLD_CEILING, config.GESTURE_DISTINCT_FACTOR)


def make_injector(dry_run):
    if dry_run:
        return RecordingInjector()
    return PynputInjector(config.DOUBLE_CLICK_INTERVAL_S, config.DOUBLE_CLICK_RADIUS_PX)


def make_engine(injector, timer, screen_size, modes=None):
    modes = modes or ModeState(Mode(config.DEFAULT_CLICK_MODE))
    calibration = BoxCalibration(Box(**config.DEFAULT_CALIBRATION), screen_size, config.SENSITIVITY)
    return Engine(CursorMapper(calibration), make_pointer_filter(screen_size), injector, ActionMapper(injector, modes),
                  modes, make_pinch(), DwellDetector(config.DWELL_MS / 1000, config.DWELL_RADIUS_PX), make_scroll(),
                  make_gesture_recorder(), timer,
                  config.CAMERA_WIDTH / config.CAMERA_HEIGHT, config.FINGERTIP_EDGE_MARGIN)


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


def run_loop(stream, engine, timer, recorder, fps_fn, on_frame, should_stop, permissions=None):
    """Drive the engine from a stream. on_frame(image, hand, result, fps) returns True to stop."""
    for t, image, hand in stream:
        if should_stop():
            return
        if recorder is not None:
            recorder.write(t, hand)
        result = engine.step(t, hand)
        if permissions is not None and not permissions.poll():
            result.lines.insert(0, "!!! NO ACCESSIBILITY PERMISSION: input is being dropped !!!")
        if recorder is not None:
            result.lines.append(f"REC {recorder.frames} frames")
        with timer.stage("ui"):
            if on_frame(image, hand, result, fps_fn()):
                return
        timer.end_frame()


def cv2_preview_frame(preview):
    """on_frame for --no-ui: the synchronous OpenCV preview window."""
    def on_frame(image, hand, result, fps):
        if not preview.enabled:
            return False
        if hand is not None:
            draw_hand(image, hand)
        return preview.show(image, [f"{fps:.1f} fps"] + result.lines) == QUIT
    return on_frame


def run_pipeline(args, engine, timer, permissions, on_frame, should_stop):
    """Open the source (camera or replay) and run until it ends or should_stop()."""
    if args.replay:
        log.info("replaying %s", args.replay)
        run_loop(replay_stream(args.replay), engine, timer, None, lambda: timer.last_summary.get("fps", 0.0),
                 on_frame, should_stop, permissions)
        return
    recorder = None
    source = make_frame_source(args.camera)
    try:
        with source, make_tracker() as tracker:
            if args.record:
                recorder = LandmarkRecorder(args.record, name="manual",
                                            frame_size=[config.CAMERA_WIDTH, config.CAMERA_HEIGHT], mirror=config.MIRROR)
                log.info("recording to %s", args.record)
            run_loop(live_stream(source, tracker, timer), engine, timer, recorder, lambda: source.fps, on_frame,
                     should_stop, permissions)
    finally:
        if recorder is not None:
            recorder.close()
            log.info("saved %d frames to %s", recorder.frames, args.record)


def run(args):
    timer = StageTimer(config.FRAME_BUDGET_MS, config.TIMING_LOG_INTERVAL_S)
    screen_size = main_screen_size()
    dry_run = args.no_inject or (args.replay and not args.inject)
    injector = make_injector(dry_run)
    permissions = None if dry_run else PermissionWatch(config.PERMISSION_CHECK_INTERVAL_S)
    modes = ModeState(Mode(config.DEFAULT_CLICK_MODE))
    engine = make_engine(injector, timer, screen_size, modes)
    log.info("screen %dx%d, %s", *screen_size, "dry run (no real input)" if dry_run else "driving the real cursor")

    if args.no_ui:
        preview = Preview(enabled=args.preview)
        try:
            run_pipeline(args, engine, timer, permissions, cv2_preview_frame(preview), lambda: False)
        finally:
            preview.close()
        return

    from pipeline.app import App
    from pipeline.ui_state import UiState

    ui = UiState()

    def on_frame(image, hand, result, fps):
        ui.publish(image, hand, result, fps, modes.mode.value, permissions.trusted if permissions else True,
                   engine.recorder.state, engine.gestures[0].name if engine.gestures else "")
        return False

    app = App(ui, modes, engine, screen_size, show_preview=args.preview)
    app.run(lambda should_stop: run_pipeline(args, engine, timer, permissions, on_frame, should_stop))


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
