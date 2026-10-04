"""The per-frame pipeline after tracking: LandmarkFrame in, cursor and clicks out.

Engine knows nothing about cameras or windows. main.py feeds it live frames,
replays feed it recorded frames, and tests feed it synthetic ones, all
through the same `step(t, hand)`.

Per frame: hand shape -> cursor target -> filter -> inject move -> the active
click mode's detector -> ClickEvents -> ActionMapper. While PAUSED nothing is
injected. Switching modes cancels the old mode's half-finished gesture.
"""

from dataclasses import dataclass, field

from pipeline.hand_pose import analyze
from pipeline.modes import Mode


@dataclass
class StepResult:
    """What happened this frame, for the preview overlay and for tests."""

    cursor: tuple = None  # screen position after this frame, or None if the hand was not tracked
    events: list = field(default_factory=list)  # ClickEvents emitted this frame
    dwell_progress: float = None  # 0..1 while a dwell is counting down (drives the ring)
    lines: list = field(default_factory=list)  # overlay text


class Engine:
    def __init__(self, mapper, pointer_filter, injector, actions, modes, pinch, dwell, timer, aspect, edge_margin):
        self.mapper = mapper
        self.filter = pointer_filter
        self.injector = injector
        self.actions = actions
        self.modes = modes
        self.pinch = pinch
        self.dwell = dwell
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

    def _emit(self, events, result):
        for event in events:
            if self.actions.handle(event):
                result.events.append(event)

    def step(self, t, hand):
        result = StepResult()
        mode = self.modes.mode
        if mode != self._last_mode:
            self._emit(self._detectors_reset(self._last_mode), result)
            self._last_mode = mode
        result.lines.append(f"mode: {mode.value}")

        if hand is None:
            self.filter.reset()
            self._emit(self._detectors_reset(mode), result)
            result.lines.append("no hand")
            return result

        with self.timer.stage("map"):
            pose = analyze(hand, self.aspect, self.edge_margin)
            target = self.mapper.target(hand)
        with self.timer.stage("filter"):
            self.cursor = self.filter.update(target, t)
        result.cursor = self.cursor
        if mode == Mode.PAUSED:
            return result

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
