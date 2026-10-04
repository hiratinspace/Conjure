"""Thread-safe hand-off between the pipeline thread and the Tk UI thread.

The pipeline thread calls `publish` once per frame; the UI thread calls
`snapshot` on its own schedule (~30 Hz) and `drain_events` for one-shot
effects (click flashes, spell names). Nothing else is shared between the
two threads except ModeState, which is itself thread-safe.
"""

import threading
from collections import deque
from dataclasses import dataclass, field

from pipeline.preview import draw_hand, draw_text_lines


@dataclass(frozen=True)
class NaiveClick:
    """UI event: tutorial mode's naive detector would have clicked here (shown, never injected)."""

    position: tuple


@dataclass(frozen=True)
class SpellCast:
    """UI event: the custom gesture fired (drives the spell-name flash)."""

    name: str
    position: tuple


@dataclass
class UiSnapshot:
    cursor: tuple = None
    dwell_progress: float = None
    mode: str = ""
    hand_visible: bool = False
    permission_ok: bool = True
    fps: float = 0.0
    lines: list = field(default_factory=list)
    prompt: str = ""
    message: str = ""
    recorder_state: str = ""
    gesture_name: str = ""
    pinch_progress: float = None
    pinch_state: str = ""
    tracking: str = ""
    next_action: str = ""
    metrics: dict = field(default_factory=dict)
    tutorial: bool = False
    preview: object = None  # annotated BGR frame, only while the preview is visible


class UiState:
    def __init__(self):
        self._lock = threading.Lock()
        self._snapshot = UiSnapshot()
        self._events = deque(maxlen=50)
        self.preview_visible = False  # written by the UI thread, read by the pipeline thread

    def publish(self, image, hand, result, fps, mode, permission_ok=True, recorder_state="", gesture_name="",
                tutorial=False):
        preview = None
        if self.preview_visible and image is not None:
            preview = image.copy()
            if hand is not None:
                draw_hand(preview, hand)
            draw_text_lines(preview, [f"{fps:.1f} fps"] + result.lines)
        snap = UiSnapshot(cursor=result.cursor, dwell_progress=result.dwell_progress, mode=mode,
                          hand_visible=hand is not None, permission_ok=permission_ok, fps=fps,
                          lines=list(result.lines), prompt=result.prompt, message=result.message,
                          recorder_state=recorder_state, gesture_name=gesture_name,
                          pinch_progress=result.pinch_progress, pinch_state=result.pinch_state,
                          tracking=result.tracking, next_action=result.next_action, metrics=dict(result.metrics),
                          tutorial=tutorial,
                          preview=preview)
        with self._lock:
            self._snapshot = snap
            self._events.extend(result.events)
            self._events.extend(NaiveClick(p) for p in result.naive_clicks)
            if result.spell:
                position = result.events[0].position if result.events else result.cursor
                self._events.append(SpellCast(result.spell, position))

    def snapshot(self):
        with self._lock:
            return self._snapshot

    def push_event(self, event):
        with self._lock:
            self._events.append(event)

    def drain_events(self):
        with self._lock:
            events = list(self._events)
            self._events.clear()
        return events
