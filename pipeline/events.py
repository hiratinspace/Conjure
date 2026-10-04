"""FROZEN CONTRACT: ClickEvent (build-plan section 1).

Pinch, dwell, and the custom gesture all emit this one type into one
ActionMapper, so nothing downstream cares which mode fired it.

`position` is in screen points: where the action lands (for a pinch, the
pre-pinch cursor position from the filter history). `amount` is only used by
SCROLL (positive scrolls up, in scroll-wheel steps); the build plan's field
list has no magnitude, and scroll needs one.
"""

from dataclasses import dataclass
from enum import Enum


class Action(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    DOUBLE = "double"
    DRAG_START = "drag_start"
    DRAG_END = "drag_end"
    SCROLL = "scroll"


@dataclass(frozen=True, slots=True)
class ClickEvent:
    action: Action
    position: tuple  # (x, y) screen points
    amount: float = 0.0  # SCROLL only
