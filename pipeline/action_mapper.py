"""ActionMapper: the single consumer of ClickEvents.

Every click path emits ClickEvents here; this turns them into injector calls.
While paused, events are dropped (except DRAG_END, so a pause can never leave
the button held), and pausing mid-drag releases the button.

Listeners (click sound, spell flash, voice) get every event that was applied.
"""

import logging

from pipeline.events import Action
from pipeline.injector import LEFT, RIGHT
from pipeline.modes import Mode

log = logging.getLogger("conjure.actions")


class ActionMapper:
    def __init__(self, injector, modes):
        self.injector = injector
        self.modes = modes
        self.dragging = False
        self._listeners = []
        modes.subscribe(self._on_mode_change)

    def subscribe(self, listener):
        """listener(event) is called after each applied event."""
        self._listeners.append(listener)

    def _on_mode_change(self, _old, new):
        if new == Mode.PAUSED and self.dragging:
            self.injector.release(LEFT)
            self.dragging = False
            log.info("paused mid-drag: button released")

    def handle(self, event):
        """Apply one ClickEvent. Returns True if it was applied."""
        if self.modes.paused and event.action != Action.DRAG_END:
            log.debug("dropped %s while paused", event.action.value)
            return False
        x, y = event.position
        action = event.action
        if action == Action.SCROLL:
            self.injector.scroll(event.amount)
        else:
            self.injector.move(x, y)
            if action == Action.LEFT:
                self.injector.click(LEFT, 1)
            elif action == Action.RIGHT:
                self.injector.click(RIGHT, 1)
            elif action == Action.DOUBLE:
                self.injector.click(LEFT, 2)
            elif action == Action.DRAG_START:
                self.injector.press(LEFT)
                self.dragging = True
            elif action == Action.DRAG_END:
                if not self.dragging:
                    return False
                self.injector.release(LEFT)
                self.dragging = False
        log.info("%s at %.0f,%.0f", action.value, x, y)
        for listener in self._listeners:
            listener(event)
        return True
