"""The per-frame pipeline after tracking: LandmarkFrame in, cursor and clicks out.

Engine knows nothing about cameras or windows. main.py feeds it live frames,
replays feed it recorded frames, and tests feed it synthetic ones, all
through the same `step(t, hand)`.

Per frame: hand shape -> cursor target -> filter -> inject move -> the active
click mode's detector -> ClickEvents -> ActionMapper. While PAUSED nothing is
injected. Switching modes cancels the old mode's half-finished gesture.
"""

import logging
import queue
from collections import deque
from dataclasses import asdict, dataclass, field

from pipeline import calibration
from pipeline.cursor_mapper import CONTROL_POINT, Box, BoxCalibration
from pipeline.gestures import normalize
from pipeline.hand_pose import analyze
from pipeline.modes import Mode
from pipeline.profile_schema import FilterSettings, GestureTemplate, Profile, Settings

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
    metrics: dict = field(default_factory=dict)  # live metrics overlay (filled by main's frame loop)
    prompt: str = ""  # big instruction text for the overlay (gesture recording, calibration)
    message: str = ""  # secondary text under the prompt
    lines: list = field(default_factory=list)  # overlay text


class Engine:
    def __init__(self, mapper, pointer_filter, injector, actions, modes, pinch, dwell, scroll, recorder, matcher,
                 calibrator, auto_pause, timer, edge_freeze_margin, aspect, edge_margin):
        self.mapper = mapper
        self.filter = pointer_filter
        self.injector = injector
        self.actions = actions
        self.modes = modes
        self.pinch = pinch
        self.dwell = dwell
        self.scroll = scroll
        self.recorder = recorder
        self.matcher = matcher
        self.calibrator = calibrator
        self.auto_pause = auto_pause
        self.edge_freeze_margin = edge_freeze_margin
        self.gestures = []  # [GestureTemplate]; one spell only by scope (scope.md section 4)
        self.store = None  # ProfileStore; when set, persist() saves after every change
        self.calibrated = False  # False while the naive default box is in use
        self.notice = ""  # one-off message for the user (e.g. gesture warnings)
        self.spell_listeners = []  # fn(name) called when the custom gesture is cast
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
        if mode == Mode.CUSTOM:
            self.matcher.reset()
        return []

    def finish_recording(self, name):
        """Turn the recorder's 3 samples into the (single) named gesture template."""
        samples, threshold, warnings = self.recorder.result(ordinary=list(self.ordinary))
        self.set_gestures([GestureTemplate(name=name, samples=samples, threshold=threshold)])
        self.recorder.cancel()
        self.persist()
        self.notice = " ".join(warnings) or f"Spell '{name}' is ready. Switch to custom mode to cast it."
        return self.gestures[0], warnings

    @property
    def calibration_box(self):
        return self.mapper.calibration.box

    def set_calibration(self, box):
        """Map `box` (normalized frame coords) to the whole screen, keeping the current sensitivity."""
        old = self.mapper.calibration
        self.mapper.calibration = BoxCalibration(box, (old.screen_w, old.screen_h), old.sensitivity)
        self.calibrated = True
        self.filter.reset()

    def set_sensitivity(self, sensitivity):
        old = self.mapper.calibration
        self.mapper.calibration = BoxCalibration(old.box, (old.screen_w, old.screen_h), sensitivity)

    def apply_profile(self, profile):
        """Load a validated Profile into the live pipeline (startup, or after an external change)."""
        s = profile.settings
        self.modes.set_click_mode(Mode(s.click_mode))
        self.dwell.configure(dwell_s=s.dwell_ms / 1000, radius_px=s.dwell_radius_px)
        self.filter.configure(min_cutoff=s.filter.min_cutoff, beta=s.filter.beta,
                              precision_gain=s.filter.precision_gain)
        if profile.calibration is not None:
            self.set_calibration(Box(**profile.calibration))
        self.set_sensitivity(s.sensitivity)
        self.set_gestures(profile.gestures)

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
        return Profile(calibration=calibration, gestures=list(self.gestures), settings=settings)

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
        for event in events:
            if self.actions.handle(event, t):
                result.events.append(event)

    def step(self, t, hand):
        self._run_commands()
        result = StepResult()
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
        if not self.auto_pause.update(hand):
            hand = None  # a hand at the very edge of the frame is a hand leaving
        mode = self.modes.mode
        result.tracking = "paused" if mode == Mode.PAUSED else "tracking" if hand is not None else "no hand"
        if mode != self._last_mode:
            self._emit(self._detectors_reset(self._last_mode), result)
            self._last_mode = mode
        result.lines.append(f"mode: {mode.value}")

        if hand is None:
            self.filter.reset()
            self.scroll.reset()
            self._emit(self._detectors_reset(mode), result)
            result.lines.append("no hand")
            return result

        with self.timer.stage("map"):
            pose = analyze(hand, self.aspect, self.edge_margin)
            target = self.mapper.target(hand)
            self.ordinary.append(normalize(hand, self.aspect))
        if self.cursor is None:
            self.cursor = target
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
                    self._emit(self.pinch.update(pose, t, self.cursor, self.filter), result, t)
            return result
        with self.timer.stage("filter"):
            self.cursor = self.filter.update(target, t)
        result.cursor = self.cursor
        with self.timer.stage("inject"):
            self.injector.move(*self.cursor)
        with self.timer.stage("gesture"):
            if mode == Mode.PINCH:
                self._emit(self.pinch.update(pose, t, self.cursor, self.filter), result, t)
                result.lines.append(self.pinch.status())
                result.pinch_progress, result.pinch_state = self.pinch.progress()
            elif mode == Mode.DWELL:
                self._emit(self.dwell.update(self.cursor, t), result, t)
                result.dwell_progress = self.dwell.progress
                result.lines.append(self.dwell.status())
            elif mode == Mode.CUSTOM:
                fired = self.matcher.update(hand, t, self.filter)
                self._emit(fired, result, t)
                if fired:
                    result.spell = self.matcher.last_match
                    for listener in self.spell_listeners:
                        listener(result.spell)
                result.lines.append(self.matcher.status())

        x, y = self.cursor
        result.lines.append(f"{hand.handedness} hand  conf {hand.confidence:.2f}  cursor {x:.0f},{y:.0f}")
        result.lines.append(f"speed {self.filter.speed:.0f} px/s  gain {self.filter.current_gain:.2f}")
        return result
