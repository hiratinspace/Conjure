"""Synthetic mouse input: the only module that touches the OS cursor.

`enabled = False` makes every call a no-op; auto-pause (CONJ-15) and dry runs
(--no-inject, replays) rely on that. RecordingInjector logs calls instead of
posting them, for tests and replays.
"""

import logging

log = logging.getLogger("conjure.injector")

LEFT = "left"
RIGHT = "right"


class PynputInjector:
    def __init__(self):
        from pynput.mouse import Button, Controller

        self._mouse = Controller()
        self._buttons = {LEFT: Button.left, RIGHT: Button.right}
        self.enabled = True

    def move(self, x, y):
        if self.enabled:
            self._mouse.position = (x, y)

    def click(self, button=LEFT, count=1):
        if self.enabled:
            self._mouse.click(self._buttons[button], count)

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
