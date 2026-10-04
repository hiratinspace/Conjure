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
import time

import numpy as np

import config
from pipeline.action_mapper import ActionMapper
from pipeline.auto_pause import AutoPause
from pipeline.calibration import Calibrator
from pipeline.cursor_mapper import CONTROL_POINT, Box, BoxCalibration, CursorMapper
from pipeline.dwell import DwellDetector
from pipeline.engine import Engine
from pipeline.filter import PointerFilter
from pipeline.frame_source import CameraError, FrameSource
from pipeline.gesture_matcher import GestureMatcher
from pipeline.gesture_recorder import GestureRecorder
from pipeline.hand_tracker import HandTracker
from pipeline.injector import PynputInjector, RecordingInjector
from pipeline.modes import HAND_LOST, Mode, ModeState
from pipeline.permissions import PermissionWatch, main_screen_size
from pipeline.pinch import PinchDetector
from pipeline.profile_store import ProfileStore
from pipeline.relative import BasePixelMapper, RelativePointer
from pipeline.scroll import ScrollDetector
from pipeline.touch import TouchDetector
from pipeline.tuner import Tuner
from pipeline.preview import QUIT, Preview, draw_hand
from pipeline.recorder import LandmarkRecorder, replay
from pipeline.timing import StageTimer

log = logging.getLogger("conjure")


def add_file_log():
    """Also write this run's log to logs/conjure-<timestamp>.log, so a bad demo can be read afterwards."""
    try:
        config.LOG_DIR.mkdir(exist_ok=True)
        path = config.LOG_DIR / time.strftime("conjure-%Y%m%d-%H%M%S.log")
        handler = logging.FileHandler(path)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(handler)
        return path
    except OSError as e:
        log.warning("no file log: %s", e)
        return None


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Conjure: hand-tracking pointer for macOS")
    parser.add_argument("--preview", action="store_true", help="show the debug preview window (p hides it, q quits)")
    parser.add_argument("--no-ui", action="store_true",
                        help="no overlay: single-thread loop with the OpenCV preview (debugging fallback)")
    parser.add_argument("--camera", type=int, default=config.CAMERA_INDEX, help="camera index")
    parser.add_argument("--record", metavar="PATH", help="record the landmark stream to a JSONL file")
    parser.add_argument("--replay", metavar="PATH", help="run from a JSONL recording instead of the camera")
    parser.add_argument("--profile", metavar="PATH", default=str(config.PROFILE_PATH),
                        help="profile file (calibration, spell, settings)")
    parser.add_argument("--venue", metavar="PATH", default=str(config.VENUE_PATH),
                        help="demo-day threshold overrides (default venue.json)")
    parser.add_argument("--no-inject", action="store_true", help="dry run: never move the real cursor or click")
    parser.add_argument("--inject", action="store_true", help="with --replay: drive the real cursor from the recording")
    parser.add_argument("--spellbook", action="store_true",
                        help="also open the spellbook demo screen in the default browser (offline file)")
    parser.add_argument("--quit-after", type=float, metavar="SECONDS", help="quit automatically (smoke tests)")
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
                         config.POSITION_HISTORY_FRAMES, config.PRECISION_RAMP_S, config.STILL_DEADBAND_PX)


def make_mouse_pointer(screen_size):
    return RelativePointer(config.FILTER_MIN_CUTOFF, config.FILTER_BETA, config.FILTER_D_CUTOFF, screen_size,
                           config.POSITION_HISTORY_FRAMES, config.MOUSE_DEAD_SPEED, config.MOUSE_SLOW_SPEED,
                           config.MOUSE_FAST_SPEED, config.MOUSE_LOW_GAIN, config.MOUSE_HIGH_GAIN,
                           sensitivity=config.SENSITIVITY)


def make_pinch():
    return PinchDetector(config.PINCH_ENGAGE_RATIO, config.PINCH_RELEASE_RATIO, config.PINCH_HOLD_MS / 1000,
                         config.PINCH_OPEN_EXTENSION, config.DRAG_START_PX, config.PINCH_LATCH_LOOKBACK_S,
                         config.PINCH_REQUIRE_OPEN_FINGERS,
                         None if config.PINCH_QUICK_CLOSE_MS is None else config.PINCH_QUICK_CLOSE_MS / 1000,
                         config.PINCH_MAX_SPEED_PX_S)


def make_touch():
    return TouchDetector(config.CAMERA_WIDTH / config.CAMERA_HEIGHT, config.FINGERTIP_EDGE_MARGIN,
                         config.TOUCH_HOVER_STRAIGHTNESS, config.TOUCH_DOWN_STRAIGHTNESS, config.TOUCH_UP_STRAIGHTNESS,
                         config.TOUCH_ARM_MS / 1000, config.TOUCH_MIN_MS / 1000, config.TAP_MAX_MS / 1000,
                         config.LONG_PRESS_MS / 1000, config.TOUCH_DRAG_PX, config.TOUCH_MAX_SPEED_PX_S,
                         config.TOUCH_DRAG_HOLD_MS / 1000)


def make_scroll():
    return ScrollDetector(config.SCROLL_EXTENDED, config.SCROLL_FOLDED, config.SCROLL_EXIT_EXTENDED,
                          config.SCROLL_EXIT_FOLDED, config.SCROLL_ENTER_MS / 1000, config.SCROLL_EXIT_MS / 1000,
                          config.SCROLL_DEAD_ZONE, config.SCROLL_GAIN, config.SCROLL_MAX_RATE)


def make_gesture_recorder():
    return GestureRecorder(config.CAMERA_WIDTH / config.CAMERA_HEIGHT, config.GESTURE_COUNTDOWN_S,
                           config.GESTURE_SAMPLE_S, config.GESTURE_ACTIVE_THRESHOLD, config.GESTURE_MARGIN_FRAMES,
                           config.GESTURE_THRESHOLD_SCALE, config.GESTURE_THRESHOLD_FLOOR,
                           config.GESTURE_THRESHOLD_CEILING, config.GESTURE_DISTINCT_FACTOR)


def make_gesture_matcher():
    return GestureMatcher(config.CAMERA_WIDTH / config.CAMERA_HEIGHT, config.GESTURE_SCALES,
                          config.GESTURE_MATCH_SCALE, config.GESTURE_REARM_FACTOR, config.GESTURE_REFRACTORY_S,
                          config.GESTURE_BUFFER_FRAMES)


def make_tuner():
    return Tuner(config.TUNE_COUNTDOWN_S, config.TUNE_MEASURE_S, config.TUNE_MARGIN, config.TUNE_MIN_DEAD,
                 config.TUNE_MAX_DEAD, config.TUNE_SLOW_RATIO, config.TUNE_MIN_SLOW, config.TUNE_MOVING_SPEED)


def make_calibrator():
    return Calibrator(config.CALIBRATION_COUNTDOWN_S, config.CALIBRATION_TRACE_S, config.CALIBRATION_LOW_PCT,
                      config.CALIBRATION_HIGH_PCT, config.CALIBRATION_MIN_SIZE)


def make_voice(player):
    """ElevenLabs in front of the offline voice when ELEVENLABS_API_KEY is set; offline only otherwise."""
    import os

    from pipeline.voice import LocalVoice

    local = LocalVoice(player, [config.VOICE_DIR, config.VOICE_CACHE_DIR])
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        log.info("voice: offline (set ELEVENLABS_API_KEY to enable ElevenLabs)")
        return local
    from pipeline.voice_elevenlabs import ElevenLabsVoice

    log.info("voice: ElevenLabs with offline fallback")
    return ElevenLabsVoice(api_key, os.environ.get("ELEVENLABS_VOICE_ID", config.ELEVENLABS_VOICE_ID),
                           config.ELEVENLABS_MODEL_ID, [config.VOICE_DIR], config.VOICE_CACHE_DIR, player, local,
                           config.TTS_DEADLINE_S)


def make_feedback(engine, modes, enabled):
    """Sounds and voice for clicks, spells, and mode changes. Silent for dry runs and replays."""
    from pipeline.audio import AudioPlayer, SoundBank
    from pipeline.feedback import Feedback, FeedbackSettings

    player = AudioPlayer()
    settings = FeedbackSettings() if enabled else FeedbackSettings(trail=True, sound=False, voice=False)
    sounds = SoundBank(player)
    sounds.preload(config.CLICK_SOUND, config.SPELL_SOUND)
    feedback = Feedback(player, make_voice(player), config.CLICK_SOUND, config.SPELL_SOUND, settings, sounds)
    engine.actions.subscribe(feedback.on_click)
    engine.spell_listeners.append(feedback.on_spell)
    engine.next_action.subscribe(feedback.on_next_action)
    modes.subscribe(feedback.on_mode)
    return feedback


def make_injector(dry_run):
    if dry_run:
        return RecordingInjector()
    return PynputInjector(config.DOUBLE_CLICK_INTERVAL_S, config.DOUBLE_CLICK_RADIUS_PX)


def make_engine(injector, timer, screen_size, modes=None, pointer_style=None):
    modes = modes or ModeState(Mode(config.DEFAULT_CLICK_MODE))
    # Second guard for CONJ-15: while paused the injector itself is off, whatever the engine does.
    modes.subscribe(lambda _old, new: setattr(injector, "enabled", new != Mode.PAUSED))
    calibration = BoxCalibration(Box(**config.DEFAULT_CALIBRATION), screen_size, config.SENSITIVITY)
    actions = ActionMapper(injector, modes, config.CLICK_REFRACTORY_MS / 1000)
    direct = (CursorMapper(calibration), make_pointer_filter(screen_size))
    mouse = (BasePixelMapper(CONTROL_POINT, config.CAMERA_WIDTH / config.CAMERA_HEIGHT, config.MOUSE_BASE_PX,
                             calibration), make_mouse_pointer(screen_size))
    engine = Engine(direct[0], direct[1], injector, actions,
                  modes, make_pinch(), DwellDetector(config.DWELL_MS / 1000, config.DWELL_RADIUS_PX), make_scroll(),
                  make_gesture_recorder(), make_gesture_matcher(), make_calibrator(),
                  AutoPause(modes, config.PAUSE_AFTER_FRAMES, config.RESUME_AFTER_FRAMES,
                            config.CONTROL_POINT_EDGE_MARGIN), timer,
                  config.EDGE_FREEZE_MARGIN,
                  config.CAMERA_WIDTH / config.CAMERA_HEIGHT, config.FINGERTIP_EDGE_MARGIN, make_touch(),
                  make_tuner())
    engine.pointers = {"direct": direct, "mouse": mouse}
    engine.base_mapper = mouse[0]  # hand speed in frame units, whichever pointer is active
    engine.set_pointer_style(pointer_style or config.POINTER_STYLE)
    return engine


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
        if not preview.enabled or image is None:
            return False
        if hand is not None:
            draw_hand(image, hand)
        return preview.show(image, [f"{fps:.1f} fps"] + result.lines) == QUIT
    return on_frame


def run_pipeline(args, engine, timer, permissions, on_frame, should_stop):
    """Open the source (camera or replay) and run until it ends or should_stop().

    A camera that stops delivering frames (unplugged, grabbed by another app, permission revoked)
    is retried every CAMERA_RETRY_S with a notice on screen, instead of ending the session."""
    if args.replay:
        log.info("replaying %s", args.replay)
        run_loop(replay_stream(args.replay), engine, timer, None, lambda: timer.last_summary.get("fps", 0.0),
                 on_frame, should_stop, permissions)
        return
    recorder = None
    if args.record:
        recorder = LandmarkRecorder(args.record, name="manual",
                                    frame_size=[config.CAMERA_WIDTH, config.CAMERA_HEIGHT], mirror=config.MIRROR)
        log.info("recording to %s", args.record)
    try:
        with make_tracker() as tracker:
            attempt = 0
            first = True
            while not should_stop():
                source = make_frame_source(args.camera)
                try:
                    with source:
                        if engine.notice.startswith("Camera lost"):
                            engine.notice = ""
                        run_loop(live_stream(source, tracker, timer), engine, timer, recorder, lambda: source.fps,
                                 on_frame, should_stop, permissions)
                        return
                except CameraError as e:
                    if source.frames >= config.CAMERA_HEALTHY_FRAMES:
                        attempt = 0  # it worked for a while: this is a new outage, not the same one
                    attempt += 1
                    if attempt > config.CAMERA_MAX_RETRIES or (attempt == 1 and source.frames == 0 and first):
                        raise  # a camera that never delivered a frame at launch is a setup problem: say so now
                    first = False
                    engine.recover(e)
                    engine.modes.pause(HAND_LOST)  # nothing may click while the camera is gone
                    engine.notice = f"Camera lost ({e}). Retrying... ({attempt}/{config.CAMERA_MAX_RETRIES})"
                    log.warning("camera lost: %s (retry %d in %.0f s)", e, attempt, config.CAMERA_RETRY_S)
                    on_frame(None, None, engine.step(time.monotonic(), None), 0.0)
                    deadline = time.monotonic() + config.CAMERA_RETRY_S
                    while time.monotonic() < deadline and not should_stop():
                        time.sleep(0.1)
    finally:
        if recorder is not None:
            recorder.close()
            log.info("saved %d frames to %s", recorder.frames, args.record)


def run(args):
    from pathlib import Path

    from pipeline.venue import apply_venue

    _, venue_errors, stage_mode = apply_venue(Path(args.venue), config)
    timer = StageTimer(config.FRAME_BUDGET_MS, config.TIMING_LOG_INTERVAL_S)
    screen_size = main_screen_size()
    dry_run = args.no_inject or (args.replay and not args.inject)
    injector = make_injector(dry_run)
    permissions = None if dry_run else PermissionWatch(config.PERMISSION_CHECK_INTERVAL_S)
    modes = ModeState(Mode(config.DEFAULT_CLICK_MODE))
    engine = make_engine(injector, timer, screen_size, modes)
    store = ProfileStore(args.profile)
    profile, warning = store.load()
    engine.apply_profile(profile)
    engine.store = store
    if warning:
        engine.notice = warning
    if stage_mode:
        modes.set_click_mode(Mode(stage_mode))
    if config.CALIBRATE_ON_FIRST_RUN and not engine.calibrated and not dry_run and engine.pointer_style == "direct":
        # First run: fit Conjure to the user's comfortable range before anything else.
        engine.submit(lambda e: e.calibrator.start())
        log.info("no saved calibration: starting calibration (rest your forearm and trace a small area)")
    if venue_errors:
        engine.notice = f"venue.json has {len(venue_errors)} problem(s); see the terminal."
    feedback = make_feedback(engine, modes, enabled=not dry_run)
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
        if engine.show_metrics or engine.tutorial is not None:
            result.metrics = engine.metrics(fps)
        ui.publish(image, hand, result, fps, modes.mode.value, permissions.trusted if permissions else True,
                   engine.recorder.state, engine.gestures[0].name if engine.gestures else "",
                   tutorial=engine.tutorial is not None)
        return False

    if config.PANIC_KEY and not dry_run:
        from pipeline import settings_model
        from pipeline.panic_key import start_panic_key

        start_panic_key(config.PANIC_KEY, engine, settings_model.toggle_user_pause)
    app = App(ui, modes, engine, feedback, screen_size, show_preview=args.preview)
    if args.quit_after:
        app.root.after(int(args.quit_after * 1000), app.quit)
    app.run(lambda should_stop: run_pipeline(args, engine, timer, permissions, on_frame, should_stop))


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log_path = add_file_log()
    log.info("Conjure starting (frame budget %.0f ms). Ctrl+C to quit. Log: %s", config.FRAME_BUDGET_MS, log_path)
    if args.spellbook:
        import webbrowser
        webbrowser.open(config.SPELLBOOK_PATH.as_uri())
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
