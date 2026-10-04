"""FROZEN CONTRACT: the mode state machine (build-plan section 1).

One enum, one owner. Pinch, dwell, custom-gesture, settings panel, and
auto-pause all read and write the mode through a single ModeState instance;
nothing else may keep its own copy of "the current mode".

The click mode (PINCH | DWELL | CUSTOM) and pausing are separate: pausing
remembers the click mode and resuming returns to it. Several things can pause
at once (the hand left the frame, the user paused from the panel), so pauses
are tracked by reason, and input resumes only when every reason is cleared.
Thread-safe: the settings panel writes from the UI thread.
"""

import threading
from enum import Enum


class Mode(str, Enum):
    PINCH = "pinch"
    DWELL = "dwell"
    CUSTOM = "custom"
    PAUSED = "paused"


CLICK_MODES = (Mode.PINCH, Mode.DWELL, Mode.CUSTOM)

# Pause reasons
HAND_LOST = "hand_lost"
USER = "user"


class ModeState:
    def __init__(self, click_mode=Mode.PINCH):
        self._lock = threading.RLock()
        self._click_mode = self._check_click_mode(click_mode)
        self._pause_reasons = set()
        self._listeners = []

    @staticmethod
    def _check_click_mode(mode):
        mode = Mode(mode)
        if mode not in CLICK_MODES:
            raise ValueError(f"{mode} is not a click mode; use pause() instead")
        return mode

    @property
    def mode(self):
        """The effective mode: PAUSED while any pause reason is active, else the click mode."""
        with self._lock:
            return Mode.PAUSED if self._pause_reasons else self._click_mode

    @property
    def click_mode(self):
        with self._lock:
            return self._click_mode

    @property
    def paused(self):
        with self._lock:
            return bool(self._pause_reasons)

    @property
    def pause_reasons(self):
        with self._lock:
            return frozenset(self._pause_reasons)

    def subscribe(self, listener):
        """listener(old_mode, new_mode) is called after every effective mode change."""
        self._listeners.append(listener)

    def _change(self, mutate):
        with self._lock:
            before = self.mode
            mutate()
            after = self.mode
        if after != before:
            for listener in self._listeners:
                listener(before, after)
        return after

    def set_click_mode(self, mode):
        mode = self._check_click_mode(mode)
        return self._change(lambda: setattr(self, "_click_mode", mode))

    def pause(self, reason):
        return self._change(lambda: self._pause_reasons.add(reason))

    def resume(self, reason):
        return self._change(lambda: self._pause_reasons.discard(reason))
