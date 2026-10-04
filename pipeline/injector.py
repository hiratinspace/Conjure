"""Synthetic mouse input: the only module that touches the OS cursor.

`enabled = False` makes every call a no-op; auto-pause (CONJ-15) and dry runs
(--no-inject, replays) rely on that. RecordingInjector logs calls instead of
posting them, for tests and replays.

Clicks are posted through Quartz (installed with pynput) so each carries a
click count. macOS only treats a click as the second half of a double-click
if its event says so, which is normally the mouse driver's job: ClickCounter
does that job, so two quick pinches on the same spot are a real double-click.
"""

import logging
import math
import time

log = logging.getLogger("conjure.injector")

LEFT = "left"
RIGHT = "right"


class ClickCounter:
    """Assigns macOS click counts: a click within `interval_s` and `radius_px` of the previous
    one on the same button continues the sequence (2 = double-click, 3 = triple)."""

    def __init__(self, interval_s, radius_px):
        self.interval_s = interval_s
        self.radius_px = radius_px
        self._last = None  # (button, t, position, count)

    def register(self, button, t, position):
        count = 1
        if self._last is not None:
            b, lt, lpos, lcount = self._last
            if b == button and t - lt <= self.interval_s and math.dist(lpos, position) <= self.radius_px:
                count = lcount + 1
        self._last = (button, t, position, count)
        return count


class PynputInjector:
    def __init__(self, double_click_interval_s, double_click_radius_px):
        import Quartz
        from pynput.mouse import Button, Controller

        self._q = Quartz
        self._mouse = Controller()
        self._buttons = {LEFT: Button.left, RIGHT: Button.right}
        self._quartz_buttons = {
            LEFT: (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp, Quartz.kCGMouseButtonLeft),
            RIGHT: (Quartz.kCGEventRightMouseDown, Quartz.kCGEventRightMouseUp, Quartz.kCGMouseButtonRight),
        }
        self.counter = ClickCounter(double_click_interval_s, double_click_radius_px)
        self.enabled = True

    def move(self, x, y):
        if self.enabled:
            self._mouse.position = (x, y)

    def _post_click(self, button, position, click_state):
        q = self._q
        down, up, qbutton = self._quartz_buttons[button]
        for event_type in (down, up):
            event = q.CGEventCreateMouseEvent(None, event_type, position, qbutton)
            q.CGEventSetIntegerValueField(event, q.kCGMouseEventClickState, click_state)
            q.CGEventPost(q.kCGHIDEventTap, event)

    def click(self, button=LEFT, count=1):
        if not self.enabled:
            return
        position = tuple(self._mouse.position)
        for _ in range(count):
            self._post_click(button, position, self.counter.register(button, time.monotonic(), position))

    def press(self, button=LEFT):
        if self.enabled:
            self._mouse.press(self._buttons[button])

    def release(self, button=LEFT):
        # Releases go through even when disabled: pausing mid-drag must never leave a button stuck down.
        self._mouse.release(self._buttons[button])

    def scroll(self, dy):
        if self.enabled and dy:
            self._mouse.scroll(0, dy)


class RecordingInjector:
    """Same interface; records calls instead of posting events."""

    def __init__(self):
        self.enabled = True
        self.calls = []
        self.position = None

    def move(self, x, y):
        if self.enabled:
            self.position = (x, y)
            self.calls.append(("move", x, y))

    def click(self, button=LEFT, count=1):
        if self.enabled:
            self.calls.append(("click", button, count))

    def press(self, button=LEFT):
        if self.enabled:
            self.calls.append(("press", button))

    def release(self, button=LEFT):
        self.calls.append(("release", button))

    def scroll(self, dy):
        if self.enabled and dy:
            self.calls.append(("scroll", dy))

    def actions(self):
        """All calls except moves."""
        return [c for c in self.calls if c[0] != "move"]
