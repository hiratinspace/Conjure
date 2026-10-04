"""The per-frame pipeline after tracking: LandmarkFrame in, cursor and clicks out.

Engine knows nothing about cameras or windows. main.py feeds it live frames,
replays feed it recorded frames, and tests feed it synthetic ones, all
through the same `step(t, hand)`.

Per frame: hand shape -> cursor target -> filter -> inject move -> the active
click mode's detector -> ClickEvents -> ActionMapper. While PAUSED nothing is
injected. Switching modes cancels the old mode's half-finished gesture.
"""

import logging
import math
import queue

import config
from collections import deque
from dataclasses import asdict, dataclass, field

from pipeline import calibration
from pipeline.cursor_mapper import CONTROL_POINT, Box, BoxCalibration
from pipeline.gestures import normalize
from pipeline.hand_pose import analyze
from pipeline.modes import Mode
from pipeline.next_action import NextAction
from pipeline.relative import GateView, HandSpeed
from pipeline.spell_check import SpellCheck
from pipeline.events import Action
from pipeline.profile_schema import FilterSettings, GestureTemplate, PointerSettings, Profile, Settings

log = logging.getLogger("conjure.engine")

ORDINARY_FRAMES = 450  # ~15 s of the user's normal movement, for the gesture recorder's distinctness check


@dataclass
class StepResult:
    """What happened this frame, for the preview overlay and for tests."""

    cursor: tuple = None  # screen position after this frame, or None if the hand was not tracked
    events: list = field(default_factory=list)  # ClickEvents emitted this frame
    dwell_progress: float = None  # 0..1 while a dwell is counting down (drives the ring)
    spell: str = ""  # name of the custom gesture cast this frame (spell flash, voice)
    pinch_progress: float = None  # 0 = fingers open .. 1 = closed enough to engage (pinch mode only)
    pinch_state: str = ""  # open / pending / confirmed / dragging
    tracking: str = ""  # status pill: "tracking", "edge", "paused", "no hand"
    next_action: str = ""  # pill suffix: "next: right click", "click to drop", or empty
    metrics: dict = field(default_factory=dict)  # live metrics overlay (filled by main's frame loop)
    naive_clicks: list = field(default_factory=list)  # tutorial mode: where the naive detector "clicked"
    prompt: str = ""  # big instruction text for the overlay (gesture recording, calibration)
    message: str = ""  # secondary text under the prompt
    lines: list = field(default_factory=list)  # overlay text


class Engine:
    def __init__(self, mapper, pointer_filter, injector, actions, modes, pinch, dwell, scroll, recorder, matcher,
                 calibrator, auto_pause, timer, edge_freeze_margin, aspect, edge_margin, touch=None, tuner=None):
        self.mapper = mapper
        self.filter = pointer_filter
        self.injector = injector
        self.actions = actions
        self.next_action = NextAction(actions)  # what the next plain click becomes (right, double, drag lock)
        self.modes = modes
        self.pinch = pinch
        self.dwell = dwell
        self.touch = touch
        self.scroll = scroll
        self.recorder = recorder
        self.matcher = matcher
        self.calibrator = calibrator
        self.auto_pause = auto_pause
        self.tuner = tuner
        self.spell_check = SpellCheck(config.SPELL_CHECK_CASTS, config.SPELL_CHECK_TIMEOUT_S)
        self.edge_freeze_margin = edge_freeze_margin
        self.pointers = {}  # style -> (mapper, filter); see set_pointer_style
        self.pointer_style = None
        self.hand_speed = HandSpeed(config.FILTER_MIN_CUTOFF, config.FILTER_BETA, config.FILTER_D_CUTOFF)
        self.base_mapper = None  # control point -> base px, for hand speed (set by make_engine)
        self.gates = GateView(self.hand_speed, pointer_filter)
        self.gestures = []  # [GestureTemplate]; one spell only by scope (scope.md section 4)
        self.store = None  # ProfileStore; when set, persist() saves after every change
        self.calibrated = False  # False while the naive default box is in use
        self.tuned = False  # True once the resting threshold came from the user's own hand
        self.pinch_close_s = None  # auto-tuned pinch window, None = config default
        self.pinch_engage = None  # auto-tuned engage ratio, None = config default
        self.feel = "balanced"  # mouse-pointer preset name
        self.notice = ""  # one-off message for the user (e.g. gesture warnings)
        self.spell_listeners = []  # fn(name) called when the custom gesture is cast
        self.tutorial = None  # a NaivePointer while tutorial mode is on (the "before" half of the pitch)
        self.show_metrics = False  # live metrics overlay (fps, jitter, clicks, misfires blocked); k or the panel
        self.shadow_clicks = 0  # clicks Conjure's own detector would have made during tutorial mode
        self.clicks = 0  # clicks applied this session
        self._recent = deque(maxlen=30)  # (cursor, speed) for the live jitter metric
        self.frames_seen = 0
        self.frame_errors = 0  # consecutive failed frames (reset by a good one)
        self.ordinary = deque(maxlen=ORDINARY_FRAMES)
        self._commands = queue.Queue()
        self.timer = timer
        self.aspect = aspect
        self.edge_margin = edge_margin
        self.cursor = None
        self._last_mode = modes.mode

    def _detectors_reset(self, mode):
        """Cancel whatever the given mode's detector was in the middle of."""
        if mode == Mode.PINCH and self.cursor is not None:
            return self.pinch.reset(self.cursor)
        if mode == Mode.DWELL:
            self.dwell.reset()
        if mode == Mode.TOUCH and self.touch is not None and self.cursor is not None:
            return self.touch.reset(self.cursor)
        if mode == Mode.CUSTOM:
            self.matcher.reset()
        return []

    def finish_recording(self, name):
        """Turn the recorder's 3 samples into the (single) named gesture template."""
        samples, threshold, warnings = self.recorder.result(ordinary=list(self.ordinary))
        self.set_gestures([GestureTemplate(name=name, samples=samples, threshold=threshold)])
        self.recorder.cancel()
        self.persist()
        self.notice = " ".join(warnings)
        self.spell_check.start(name)  # prove it works before trusting it
        return self.gestures[0], warnings

    def start_flow(self, name):
        """Start one guided flow (tune, calibrate, record) and cancel any other, so they never overlap."""
        for flow in (self.tuner, self.calibrator, self.recorder, self.spell_check):
            if flow is not None:
                flow.cancel()
        if self.tutorial is not None:
            self.set_tutorial(None)
        {"tune": self.tuner, "calibrate": self.calibrator, "record": self.recorder}[name].start()

    def set_pointer_style(self, style):
        """Switch between "mouse" (relative, accelerated) and "direct" (calibrated box) pointing."""
        if style not in self.pointers:
            raise ValueError(f"unknown pointer style {style!r}")
        sensitivity = self.mapper.calibration.sensitivity
        self.mapper, self.filter = self.pointers[style]
        self.gates = GateView(self.hand_speed, self.filter)
        self.pointer_style = style
        self.filter.reset()
        self.set_sensitivity(sensitivity)

    @property
    def calibration_box(self):
        return self.mapper.calibration.box

    def set_calibration(self, box):
        """Map `box` (normalized frame coords) to the whole screen, keeping the current sensitivity."""
        old = self.mapper.calibration
        new = BoxCalibration(box, (old.screen_w, old.screen_h), old.sensitivity)
        for mapper in [self.mapper] + [m for m, _ in self.pointers.values()]:
            mapper.calibration = new
        self.calibrated = True
        self.filter.reset()

    def set_sensitivity(self, sensitivity):
        old = self.mapper.calibration
        new = BoxCalibration(old.box, (old.screen_w, old.screen_h), sensitivity)
        for mapper in [self.mapper] + [m for m, _ in self.pointers.values()]:
            mapper.calibration = new
        for _, pointer in self.pointers.values():
            if hasattr(pointer, "sensitivity"):
                pointer.sensitivity = sensitivity

    def apply_profile(self, profile):
        """Load a validated Profile into the live pipeline (startup, or after an external change)."""
        s = profile.settings
        self.modes.set_click_mode(Mode(s.click_mode))
        self.dwell.configure(dwell_s=s.dwell_ms / 1000, radius_px=s.dwell_radius_px)
        self.filter.configure(min_cutoff=s.filter.min_cutoff, beta=s.filter.beta,
                              precision_gain=s.filter.precision_gain)
        for _, pointer in self.pointers.values():  # both pointer styles share the smoothing settings
            pointer.configure(min_cutoff=s.filter.min_cutoff, beta=s.filter.beta, precision_gain=s.filter.precision_gain)
        if profile.calibration is not None:
            self.set_calibration(Box(**profile.calibration))
        self.set_sensitivity(s.sensitivity)
        self.set_gestures(profile.gestures)
        if profile.pointer.dead_speed is not None:
            self.set_dead_speed(profile.pointer.dead_speed)
        if profile.pointer.pinch_close_ms is not None:
            self.set_pinch_close(profile.pointer.pinch_close_ms / 1000)
        if profile.pointer.pinch_engage is not None:
            self.set_pinch_engage(profile.pointer.pinch_engage)
        if profile.pointer.feel in config.MOUSE_FEELS and "mouse" in self.pointers:
            low, high, fast = config.MOUSE_FEELS[profile.pointer.feel]
            pointer = self.pointers["mouse"][1]
            pointer.low_gain, pointer.high_gain, pointer.fast_speed = low, high, fast
            self.feel = profile.pointer.feel
        if profile.pointer.style in self.pointers:
            self.set_pointer_style(profile.pointer.style)

    def set_pinch_close(self, seconds):
        """Pinch snap window from the user's own pinches (auto-tune)."""
        self.pinch.configure(quick_close_s=seconds)
        self.pinch_close_s = seconds

    def set_pinch_engage(self, engage):
        """Engage ratio from the user's own pinches; release keeps the same hysteresis gap."""
        self.pinch.configure(engage=engage, release=engage + config.TUNE_HYSTERESIS)
        self.pinch_engage = engage

    def set_dead_speed(self, dead, slow=None):
        """Resting threshold of the mouse-style pointer (auto-tune), with the careful band scaled to match."""
        if "mouse" not in self.pointers:
            return
        pointer = self.pointers["mouse"][1]
        pointer.dead_speed = dead
        pointer.slow_speed = slow if slow is not None else max(config.TUNE_MIN_SLOW, dead * config.TUNE_SLOW_RATIO)
        self.tuned = True

    def to_profile(self):
        """Snapshot the live settings, calibration, and spell as a Profile."""
        settings = Settings(
            click_mode=self.modes.click_mode.value,
            dwell_ms=round(self.dwell.dwell_s * 1000),
            dwell_radius_px=round(self.dwell.radius_px),
            filter=FilterSettings(min_cutoff=self.filter.euro.min_cutoff, beta=self.filter.euro.beta,
                                  precision_gain=self.filter.precision_gain),
            sensitivity=self.mapper.calibration.sensitivity,
        )
        calibration = asdict(self.calibration_box) if self.calibrated else None
        mouse = self.pointers["mouse"][1] if "mouse" in self.pointers else None
        pointer = PointerSettings(style=self.pointer_style or config.POINTER_STYLE,
                                  dead_speed=mouse.dead_speed if (mouse and self.tuned) else None,
                                  pinch_close_ms=round(self.pinch_close_s * 1000) if self.pinch_close_s else None,
                                  pinch_engage=self.pinch_engage,
                                  feel=self.feel)
        return Profile(calibration=calibration, gestures=list(self.gestures), settings=settings, pointer=pointer)

    def persist(self):
        if self.store is None:
            return
        try:
            self.store.save(self.to_profile())
        except OSError as e:
            log.error("could not save profile: %s", e)
            self.notice = f"Could not save your settings ({e}). They will be lost when Conjure quits."

    def set_gestures(self, gestures):
        self.gestures = list(gestures)
        self.matcher.set_templates(self.gestures)

    def submit(self, fn):
        """Run fn(engine) on the pipeline thread at the start of the next frame (thread-safe)."""
        self._commands.put(fn)

    def _run_commands(self):
        while True:
            try:
                fn = self._commands.get_nowait()
            except queue.Empty:
                return
            fn(self)

    def _emit(self, events, result, t=None):
        for raw in events:
            translated, used_choice = self.next_action.translate(raw)
            for event in translated:
                if not self.actions.handle(event, t):
                    continue
                if used_choice:
                    self.next_action.commit()  # the choice is spent only once its click really happened
                result.events.append(event)
                if event.action in (Action.LEFT, Action.RIGHT, Action.DOUBLE, Action.DRAG_START):
                    self.clicks += 1

    def recover(self, error):
        """A frame failed. Release anything held, forget motion state, and keep going: a demo must
        not die on one bad frame. Returns the number of consecutive failures so far."""
        self.frame_errors += 1
        log.exception("frame %d failed (%d in a row): %s", self.frames_seen, self.frame_errors, error)
        try:
            if self.actions.dragging:
                self.injector.release()
                self.actions.dragging = False
            self.filter.reset()
            self.scroll.reset()
            self.pinch.reset(self.cursor or (0, 0))
            self.dwell.reset()
            self.matcher.reset()
        except Exception:  # recovery itself must never raise
            log.exception("recovery failed")
        return self.frame_errors

    def set_tutorial(self, naive_pointer):
        """Turn tutorial mode on (a NaivePointer) or off (None)."""
        self.tutorial = naive_pointer
        self.shadow_clicks = 0
        self.filter.reset()
        self._emit(self._detectors_reset(self.modes.mode), StepResult())

    def blocked(self):
        """Misfires prevented this session: pinch blips, curled-hand contacts, refractory drops."""
        return self.pinch.blocked + self.actions.suppressed + (self.touch.blocked if self.touch else 0)

    def jitter_px(self):
        """Cursor shake over the last second while the hand is nearly still, else None (moving)."""
        speeds = sorted(s for _, s in self._recent)
        if len(speeds) < 15 or speeds[len(speeds) // 2] > config.JITTER_STILL_SPEED_PX_S:
            return None
        xs = [c[0] for c, _ in self._recent]
        ys = [c[1] for c, _ in self._recent]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        return math.sqrt(sum((x - mx) ** 2 + (y - my) ** 2 for x, y in zip(xs, ys)) / len(xs))

    def metrics(self, fps):
        jitter = self.jitter_px()
        m = {"fps": f"{fps:.0f}", "jitter": "moving" if jitter is None else f"{jitter:.1f}px",
             "clicks": str(self.clicks), "misfires blocked": str(self.blocked())}
        if self.tutorial is not None:
            m = {"fps": m["fps"], "tutorial clicks": str(self.tutorial.clicks),
                 "Conjure clicks": str(self.shadow_clicks)}
        return m

    def _tutorial_step(self, t, hand, result):
        """Tutorial mode: raw fingertip cursor and naive clicks (shown, never injected);
        Conjure's pinch detector runs in shadow for the side-by-side count."""
        result.lines.append("tutorial mode: raw fingertip, no smoothing, naive pinch")
        result.tracking = "tracking" if hand is not None else "no hand"
        if hand is None:
            self.tutorial.update(None)
            self.filter.reset()
            self.hand_speed.reset()
            self.pinch.reset(self.cursor or (0, 0))
            return result
        if self.base_mapper is not None:
            self.hand_speed.update(self.base_mapper.target(hand), t)
        target = self.tutorial.target(hand)
        self.cursor = target
        result.cursor = target
        self.injector.move(*target)
        if self.tutorial.update(hand):
            result.naive_clicks.append(target)
        shadow_cursor = self.filter.update(self.mapper.target(hand), t)
        pose = analyze(hand, self.aspect, self.edge_margin)
        shadow = self.pinch.update(pose, t, shadow_cursor, self.gates)
        self.shadow_clicks += sum(1 for e in shadow if e.action in (Action.LEFT, Action.RIGHT, Action.DRAG_START))
        return result

    def step(self, t, hand):
        """One frame. Never raises: a failing frame is logged, state is reset, and an empty result returned."""
        self.frames_seen += 1
        try:
            result = self._step(t, hand)
            self.frame_errors = 0
            return result
        except Exception as e:
            self.recover(e)
            result = StepResult(cursor=self.cursor)
            result.lines.append("frame error (recovered)")
            return result

    def _step(self, t, hand):
        self._run_commands()
        result = StepResult()
        if self.spell_check.active:
            if self.cursor is not None:
                self._emit(self._detectors_reset(self.modes.mode), result)
            self.filter.reset()
            matched = bool(self.matcher.update(hand, t, self.gates)) if hand is not None else False
            if hand is None:
                self.matcher.reset()
            if self.spell_check.update(matched, t):
                self.notice = self.spell_check.verdict
                if self.spell_check.hits >= self.spell_check.casts_wanted:
                    self.modes.set_click_mode(Mode.CUSTOM)  # it works: use it
                    self.persist()
            result.cursor = self.cursor
            result.prompt = self.spell_check.prompt
            result.lines.append(f"spell check: {self.spell_check.hits} hits")
            return result
        if self.tuner is not None and self.tuner.active:
            if self.cursor is not None:
                self._emit(self._detectors_reset(self.modes.mode), result)
            speed, ratio = None, None
            if hand is not None and self.base_mapper is not None:
                speed = self.hand_speed.update(self.base_mapper.target(hand), t)
                pose = analyze(hand, self.aspect, self.edge_margin)
                ratio = pose.pinch_index if pose.index_pinch_inside else None
            else:
                self.hand_speed.reset()
            self.tuner.update(speed, t, ratio)
            if self.tuner.state == "done":
                dead, slow, p95 = self.tuner.result
                self.set_dead_speed(dead, slow)
                parts = [f"Tuned to your hand: resting tremor {p95:.0f}, threshold {dead:.0f}"]
                if self.tuner.pinch_close_s is not None:
                    self.set_pinch_close(self.tuner.pinch_close_s)
                    engage, _ = self.tuner.pinch_engage_out
                    self.set_pinch_engage(engage)
                    parts.append(f"your pinches close in up to {max(self.tuner.close_times) * 1000:.0f} ms, "
                                 f"window set to {self.tuner.pinch_close_s * 1000:.0f} ms, engage at {engage:.2f}")
                else:
                    parts.append("no pinch was seen, so the pinch window is unchanged")
                self.tuner.cancel()
                self.notice = "; ".join(parts) + "."
                self.persist()
            result.cursor = self.cursor
            result.prompt, result.message = self.tuner.prompt, self.tuner.message
            result.lines.append(f"tuning: {self.tuner.state}")
            return result
        if self.calibrator.active:
            if self.cursor is not None:
                self._emit(self._detectors_reset(self.modes.mode), result)
            self.calibrator.update(hand, t)
            if self.calibrator.state == calibration.DONE:
                self.set_calibration(self.calibrator.box)
                self.calibrator.cancel()
                self.persist()
                self.notice = "Calibrated: your comfortable area now covers the whole screen."
            result.cursor = self.cursor
            result.prompt, result.message = self.calibrator.prompt, self.calibrator.message
            result.lines.append(f"calibrating: {self.calibrator.state}")
            return result
        if self.recorder.active:
            # Recording a gesture: no cursor movement and no clicks until it is done.
            if self.cursor is not None:
                self._emit(self._detectors_reset(self.modes.mode), result)
            self.recorder.update(hand, t)
            self.filter.reset()
            result.cursor = self.cursor
            result.prompt, result.message = self.recorder.prompt, self.recorder.message
            result.lines.append(f"recording gesture: {self.recorder.state} ({len(self.recorder.samples)}/3)")
            return result
        if self.tutorial is not None:
            return self._tutorial_step(t, hand, result)
        if not self.auto_pause.update(hand):
            hand = None  # a hand at the very edge of the frame is a hand leaving
        mode = self.modes.mode
        result.tracking = "paused" if mode == Mode.PAUSED else "tracking" if hand is not None else "no hand"
        if mode != self._last_mode:
            self._emit(self._detectors_reset(self._last_mode), result)
            self._last_mode = mode
        result.lines.append(f"mode: {mode.value}")
        result.next_action = self.next_action.label()

        if hand is None:
            self.filter.reset()
            self.hand_speed.reset()
            self.scroll.reset()
            self._emit(self._detectors_reset(mode), result)
            result.lines.append("no hand")
            return result

        with self.timer.stage("map"):
            pose = analyze(hand, self.aspect, self.edge_margin)
            target = self.mapper.target(hand)
            if self.base_mapper is not None:
                self.hand_speed.update(self.base_mapper.target(hand), t)
            self.ordinary.append(normalize(hand, self.aspect))
        if self.cursor is None:
            self.cursor = getattr(self.filter, "cursor", None) or target
        if mode == Mode.PAUSED:
            self.scroll.reset()
            self.filter.reset()
            result.cursor = self.cursor
            return result

        with self.timer.stage("gesture"):
            was_scrolling = self.scroll.active
            scroll_events = self.scroll.update(hand, pose, t, self.cursor)
        if self.scroll.active or was_scrolling:
            # Cursor frozen while scrolling; forget the hand's travel so the pointer does not jump after.
            if not was_scrolling:
                self._emit(self._detectors_reset(mode), result)
            self.filter.reset()
            self._emit(scroll_events, result, t)
            result.cursor = self.cursor
            result.lines.append(self.scroll.status())
            return result

        kx, ky = hand.point(CONTROL_POINT)
        m = self.edge_freeze_margin
        if not (m <= kx <= 1 - m and m <= ky <= 1 - m):
            # Near the frame edge landmarks degrade: hold the cursor rather than follow guesses.
            self.filter.reset()
            result.cursor = self.cursor
            result.tracking = "edge"
            result.lines.append("hand near the camera edge: cursor held")
            with self.timer.stage("gesture"):
                if mode == Mode.PINCH:
                    self._emit(self.pinch.update(pose, t, self.cursor, self.gates), result, t)
            return result
        with self.timer.stage("filter"):
            self.cursor = self.filter.update(target, t)
        result.cursor = self.cursor
        self._recent.append((self.cursor, self.hand_speed.speed))
        with self.timer.stage("inject"):
            self.injector.move(*self.cursor)
        with self.timer.stage("gesture"):
            if mode == Mode.TOUCH:
                self._emit(self.touch.update(hand, t, self.cursor, self.gates), result, t)
                result.lines.append(self.touch.status())
                progress, state = self.touch.progress()
                if state == "touch":
                    result.dwell_progress = progress  # ring around the cursor: hold for right click
                    result.pinch_progress, result.pinch_state = 1.0, "confirmed"
                else:
                    result.pinch_progress, result.pinch_state = progress, state
            elif mode == Mode.PINCH:
                self._emit(self.pinch.update(pose, t, self.cursor, self.gates), result, t)
                result.lines.append(self.pinch.status())
                result.pinch_progress, result.pinch_state = self.pinch.progress()
            elif mode == Mode.DWELL:
                self._emit(self.dwell.update(self.cursor, t), result, t)
                result.dwell_progress = self.dwell.progress
                result.lines.append(self.dwell.status())
            elif mode == Mode.CUSTOM:
                fired = self.matcher.update(hand, t, self.gates)
                self._emit(fired, result, t)
                if fired:
                    result.spell = self.matcher.last_match
                    for listener in self.spell_listeners:
                        listener(result.spell)
                result.lines.append(self.matcher.status())

        x, y = self.cursor
        result.lines.append(f"{hand.handedness} hand  conf {hand.confidence:.2f}  cursor {x:.0f},{y:.0f}")
        result.lines.append(f"hand {self.hand_speed.speed:.0f}/s  gain {self.filter.current_gain:.2f}")
        return result
