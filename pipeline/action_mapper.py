"""ActionMapper: the single consumer of ClickEvents.

Every click path emits ClickEvents here; this turns them into injector calls.
While paused, events are dropped (except DRAG_END, so a pause can never leave
the button held), and pausing mid-drag releases the button.

A refractory period applies to every click source: a click (left, right,
double, drag start) within `refractory_s` of the previous one is dropped as
an accident. Real double-clicks are not two clicks squeezed together here;
the injector's ClickCounter turns clicks that land close in time and place
into a double-click. Times are frame timestamps, so replays behave like live.

Listeners (click sound, spell flash, voice) get every event that was applied.
"""

import logging
import time

from pipeline.events import Action
from pipeline.injector import LEFT, RIGHT
from pipeline.modes import Mode

log = logging.getLogger("conjure.actions")


CLICKS = (Action.LEFT, Action.RIGHT, Action.DOUBLE, Action.DRAG_START)


class ActionMapper:
    def __init__(self, injector, modes, refractory_s=0.0):
        self.injector = injector
        self.modes = modes
        self.refractory_s = refractory_s
        self.suppressed = 0  # clicks dropped by the refractory period (metrics)
        self._t_last_click = None
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

    def handle(self, event, t=None):
        """Apply one ClickEvent at frame time t. Returns True if it was applied."""
        if self.modes.paused and event.action != Action.DRAG_END:
            log.debug("dropped %s while paused", event.action.value)
            return False
        if event.action in CLICKS:
            t = time.monotonic() if t is None else t
            if self._t_last_click is not None and t - self._t_last_click < self.refractory_s:
                self.suppressed += 1
                log.info("dropped %s: within %.0f ms of the previous click", event.action.value,
                         self.refractory_s * 1000)
                return False
            self._t_last_click = t
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
                if self.dragging:
                    return False  # already holding the button
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
