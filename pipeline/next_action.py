"""Next action: choose what the next click does, without a pinch.

Dwell, spell, and touch taps produce plain left clicks. Apple Dwell Control
and Tobii solve "how do I right-click or drag without a hand gesture" with a
toolbar: pick the next action, then click the target. This is that.

    next_action   what the next plain click becomes
    LEFT          a left click (default)
    RIGHT         a right click
    DOUBLE        a double-click
    DRAG          starts a drag and locks it; the following plain click ends it
                  ("drag lock": nobody has to hold a pinch)

After one use the choice falls back to LEFT (Apple's "fallback action"),
unless `sticky` is on. While a drag is locked, any plain click ends it, in
every click mode. Pinch mode's own natural drag (pinch, move, release) is
untouched: it never emits a plain click mid-drag.
"""

from pipeline.events import Action, ClickEvent

DRAG = "drag"
CHOICES = (Action.LEFT.value, Action.RIGHT.value, Action.DOUBLE.value, DRAG)


class NextAction:
    def __init__(self, actions):
        self.actions = actions  # the ActionMapper, which knows whether a drag is in progress
        self.choice = Action.LEFT.value
        self.sticky = False
        self._listeners = []

    def subscribe(self, listener):
        """listener(choice) after every change."""
        self._listeners.append(listener)

    def set(self, choice):
        if choice not in CHOICES:
            raise ValueError(f"unknown action {choice!r}")
        self.choice = choice
        for listener in self._listeners:
            listener(choice)

    def _consume(self):
        choice = self.choice
        if not self.sticky:
            self.set(Action.LEFT.value)
        return choice

    def apply(self, event):
        """Translate one event from a detector into the events to perform."""
        if event.action != Action.LEFT:
            return [event]
        if self.actions.dragging:  # drag lock: a plain click ends the drag
            return [ClickEvent(Action.DRAG_END, event.position)]
        choice = self._consume()
        if choice == Action.RIGHT.value:
            return [ClickEvent(Action.RIGHT, event.position)]
        if choice == Action.DOUBLE.value:
            return [ClickEvent(Action.DOUBLE, event.position)]
        if choice == DRAG:
            return [ClickEvent(Action.DRAG_START, event.position)]
        return [event]

    def label(self):
        if self.actions.dragging:
            return "click to drop"
        return {Action.LEFT.value: "", Action.RIGHT.value: "next: right click",
                Action.DOUBLE.value: "next: double-click", DRAG: "next: drag"}[self.choice]
