"""CONJ-3: debug preview window.

The preview is the debugging surface for every later stage: each one adds its
state to the overlay through `Preview.show(frame, lines=...)`. Turning the
preview off (demo mode) only stops drawing; capture and tracking keep running.

Keys while the window has focus: p hides the preview, q or Esc quits.
"""

import cv2

WINDOW = "Conjure preview"
FONT = cv2.FONT_HERSHEY_SIMPLEX
TEXT_COLOR = (255, 255, 255)
SHADOW_COLOR = (0, 0, 0)

QUIT = "quit"
TOGGLE = "toggle"


def draw_text_lines(frame, lines, origin=(10, 24), line_height=22, scale=0.55):
    x, y = origin
    for line in lines:
        cv2.putText(frame, line, (x + 1, y + 1), FONT, scale, SHADOW_COLOR, 3, cv2.LINE_AA)
        cv2.putText(frame, line, (x, y), FONT, scale, TEXT_COLOR, 1, cv2.LINE_AA)
        y += line_height
    return frame


class Preview:
    def __init__(self, enabled):
        self.enabled = enabled
        self._window_open = False

    def toggle(self):
        self.enabled = not self.enabled
        if not self.enabled:
            self._close_window()

    def show(self, frame, lines=()):
        """Draw overlays and display. Returns QUIT, TOGGLE, or None."""
        if not self.enabled:
            return None
        draw_text_lines(frame, lines)
        cv2.imshow(WINDOW, frame)
        self._window_open = True
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), 27):
            return QUIT
        if key == ord("p"):
            self.toggle()
            return TOGGLE
        return None

    def _close_window(self):
        if self._window_open:
            cv2.destroyWindow(WINDOW)
            cv2.waitKey(1)
            self._window_open = False

    def close(self):
        self._close_window()
