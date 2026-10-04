"""The per-frame pipeline after tracking: LandmarkFrame in, cursor and clicks out.

Engine knows nothing about cameras or windows. main.py feeds it live frames,
replays feed it recorded frames, and tests feed it synthetic ones, all
through the same `step(t, hand)`.
"""

from dataclasses import dataclass, field


@dataclass
class StepResult:
    """What happened this frame, for the preview overlay and for tests."""

    cursor: tuple = None  # screen position after this frame, or None if the hand was not tracked
    lines: list = field(default_factory=list)  # overlay text


class Engine:
    def __init__(self, mapper, injector, timer):
        self.mapper = mapper
        self.injector = injector
        self.timer = timer
        self.cursor = None

    def step(self, t, hand):
        result = StepResult()
        if hand is None:
            result.lines.append("no hand")
            return result
        with self.timer.stage("map"):
            x, y = self.mapper.target(hand)
        with self.timer.stage("inject"):
            self.injector.move(x, y)
        self.cursor = (x, y)
        result.cursor = self.cursor
        result.lines.append(f"{hand.handedness} hand  conf {hand.confidence:.2f}  cursor {x:.0f},{y:.0f}")
        return result
