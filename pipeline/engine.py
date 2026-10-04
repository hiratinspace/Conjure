"""The per-frame pipeline after tracking: LandmarkFrame in, cursor and clicks out.

Engine knows nothing about cameras or windows. main.py feeds it live frames,
replays feed it recorded frames, and tests feed it synthetic ones, all
through the same `step(t, hand)`.

Per frame: hand shape -> cursor target -> filter -> inject move -> the active
click mode's detector -> ClickEvents -> ActionMapper. While PAUSED nothing is
injected. Switching modes cancels the old mode's half-finished gesture.
"""

import queue
from collections import deque
from dataclasses import dataclass, field

from pipeline.gestures import normalize
from pipeline.hand_pose import analyze
from pipeline.modes import Mode

ORDINARY_FRAMES = 450  # ~15 s of the user's normal movement, for the gesture recorder's distinctness check


@dataclass
class StepResult:
    """What happened this frame, for the preview overlay and for tests."""

    cursor: tuple = None  # screen position after this frame, or None if the hand was not tracked
    events: list = field(default_factory=list)  # ClickEvents emitted this frame
    dwell_progress: float = None  # 0..1 while a dwell is counting down (drives the ring)
    prompt: str = ""  # big instruction text for the overlay (gesture recording, calibration)
    message: str = ""  # secondary text under the prompt
    lines: list = field(default_factory=list)  # overlay text


class Engine:
    def __init__(self, mapper, pointer_filter, injector, actions, modes, pinch, dwell, scroll, recorder, timer,
                 aspect, edge_margin):
        self.mapper = mapper
        self.filter = pointer_filter
        self.injector = injector
        self.actions = actions
        self.modes = modes
        self.pinch = pinch
        self.dwell = dwell
        self.scroll = scroll
        self.recorder = recorder
        self.gestures = []  # [GestureTemplate]; one spell only by scope (scope.md section 4)
        self.notice = ""  # one-off message for the user (e.g. gesture warnings)
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
        return []

    def finish_recording(self, name):
        """Turn the recorder's 3 samples into the (single) named gesture template."""
        from pipeline.profile_schema import GestureTemplate

        samples, threshold, warnings = self.recorder.result(ordinary=list(self.ordinary))
        self.gestures = [GestureTemplate(name=name, samples=samples, threshold=threshold)]
        self.recorder.cancel()
        self.notice = " ".join(warnings) or f"Spell '{name}' is ready. Switch to custom mode to cast it."
        return self.gestures[0], warnings

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

    def _emit(self, events, result):
        for event in events:
            if self.actions.handle(event):
                result.events.append(event)

    def step(self, t, hand):
        self._run_commands()
        result = StepResult()
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
        mode = self.modes.mode
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
            self._emit(scroll_events, result)
            result.cursor = self.cursor
            result.lines.append(self.scroll.status())
            return result

        with self.timer.stage("filter"):
            self.cursor = self.filter.update(target, t)
        result.cursor = self.cursor
        with self.timer.stage("inject"):
            self.injector.move(*self.cursor)
        with self.timer.stage("gesture"):
            if mode == Mode.PINCH:
                self._emit(self.pinch.update(pose, t, self.cursor, self.filter), result)
                result.lines.append(self.pinch.status())
            elif mode == Mode.DWELL:
                self._emit(self.dwell.update(self.cursor, t), result)
                result.dwell_progress = self.dwell.progress
                result.lines.append(self.dwell.status())

        x, y = self.cursor
        result.lines.append(f"{hand.handedness} hand  conf {hand.confidence:.2f}  cursor {x:.0f},{y:.0f}")
        result.lines.append(f"speed {self.filter.speed:.0f} px/s  gain {self.filter.gain(self.filter.speed):.2f}")
        return result
