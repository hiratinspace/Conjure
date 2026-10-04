"""Full-screen, transparent, click-through overlay (Tk + AppKit).

Draws what the user needs to see without looking at a debug window: the
dwell countdown ring around the cursor (CONJ-8), the paused banner (CONJ-15),
the mode badge, and, later, the cursor trail and spell flash (CONJ-17).

The window ignores the mouse entirely (NSWindow.setIgnoresMouseEvents_), so
synthetic and real clicks pass straight through to the app underneath, and
it floats above everything on every Space.

`ring_arc` and `badge_text` are pure so the drawing decisions are testable
without a display.
"""

import logging

log = logging.getLogger("conjure.overlay")

RING_RADIUS = 30
RING_WIDTH = 6
RING_TRACK = "#3b2a5c"
NAIVE_RED = "#ff3b30"
RING_FILL = "#f5c542"
BANNER_BG = "#2a1b47"
BANNER_FG = "#f5c542"
WARN_BG = "#8b1e1e"
BADGE_FG = "#d9c8ff"
TITLE = "Conjure overlay"


def ring_arc(progress):
    """Tk arc (start, extent) for a countdown that fills clockwise from 12 o'clock."""
    progress = max(0.0, min(1.0, progress))
    return 90.0, -360.0 * progress


def trail_color(i, n):
    """Fades from deep violet (oldest) to gold (newest)."""
    f = (i + 1) / n
    lo, hi = (0x3b, 0x2a, 0x5c), (0xf5, 0xc5, 0x42)
    return "#%02x%02x%02x" % tuple(round(a + (b - a) * f) for a, b in zip(lo, hi))


STATUS = {  # tracking state -> (dot color, label)
    "tracking": ("#4cd964", "Tracking"),
    "edge": ("#f5a623", "Near edge"),
    "paused": ("#ff3b30", "Paused"),
    "no hand": ("#8e8e93", "No hand"),
}
MODE_LABELS = {"touch": "Touch", "pinch": "Pinch", "dwell": "Dwell", "custom": "Spell", "paused": ""}


def badge_text(snapshot):
    if not snapshot.mode:
        return ""
    status = STATUS.get(snapshot.tracking, ("", ""))[1]
    mode = MODE_LABELS.get(snapshot.mode, snapshot.mode)
    return "  |  ".join(part for part in (status, mode, snapshot.next_action) if part)


def pinch_dot_arc(progress):
    """Pie extent for the pinch dot: fills clockwise as the fingers close."""
    return ring_arc(progress)


def make_click_through(title):
    """Find our NSWindow by title and make it ignore the mouse, float on top, and join every Space."""
    try:
        import AppKit
    except ImportError:
        log.warning("AppKit unavailable: overlay will intercept clicks")
        return False
    for window in AppKit.NSApp.windows():
        if window.title() == title:
            window.setIgnoresMouseEvents_(True)
            window.setLevel_(AppKit.NSScreenSaverWindowLevel)
            window.setHasShadow_(False)
            window.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                                          | AppKit.NSWindowCollectionBehaviorStationary
                                          | AppKit.NSWindowCollectionBehaviorIgnoresCycle)
            return True
    log.warning("overlay NSWindow %r not found: it may intercept clicks", title)
    return False


class Overlay:
    def __init__(self, root, screen_size):
        import tkinter as tk

        self.w, self.h = screen_size
        self.win = tk.Toplevel(root)
        self.win.title(TITLE)
        self.win.overrideredirect(True)
        self.win.geometry(f"{self.w}x{self.h}+0+0")
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparent", True)
        self.win.config(bg="systemTransparent")
        self.canvas = tk.Canvas(self.win, width=self.w, height=self.h, bg="systemTransparent", highlightthickness=0)
        self.canvas.pack()
        self.win.update_idletasks()
        self.win.update()
        self.click_through = make_click_through(TITLE)

    def draw(self, snap, paused_message=None, notice="", trail=(), ripples=(), flash=None, naive=()):
        """trail: recent cursor points (oldest first); ripples: [(x, y, age 0..1)]; flash: (text, x, y) or None;
        naive: [(x, y, age 0..1)] tutorial-mode clicks, drawn red."""
        c = self.canvas
        c.delete("all")
        n = len(trail)
        for i, (x, y) in enumerate(trail):
            r = 3 + 7 * (i + 1) / n
            c.create_oval(x - r, y - r, x + r, y + r, fill=trail_color(i, n), outline="")
        for x, y, age in ripples:
            r = 14 + 40 * age
            c.create_oval(x - r, y - r, x + r, y + r, outline=RING_FILL, width=max(1, 5 * (1 - age)))
        for x, y, age in naive:
            r = 18 + 30 * age
            c.create_oval(x - r, y - r, x + r, y + r, outline=NAIVE_RED, width=max(1, 6 * (1 - age)))
            c.create_text(x, y - r - 14, text="click", fill=NAIVE_RED, font=("Helvetica", 16, "bold"))
        if snap.tutorial:
            self._banner("Tutorial mode: how most webcam mice behave", WARN_BG, y=110, size=24)
        if flash is not None:
            text, x, y = flash
            for dx, dy in ((2, 2), (-2, -2), (2, -2), (-2, 2)):
                c.create_text(x + dx, y - 70 + dy, text=text, fill=BANNER_BG, font=("Iowan Old Style", 44, "bold"))
            c.create_text(x, y - 70, text=text, fill=RING_FILL, font=("Iowan Old Style", 44, "bold"))
        if snap.prompt:
            self._banner(snap.prompt, BANNER_BG, y=self.h * 0.35, size=34)
            if snap.message:
                self._banner(snap.message, WARN_BG, y=self.h * 0.35 + 80, size=22)
        elif notice:
            self._banner(notice, BANNER_BG, y=self.h * 0.35, size=24)
        if snap.dwell_progress is not None and snap.cursor is not None:
            x, y = snap.cursor
            r = RING_RADIUS
            c.create_oval(x - r, y - r, x + r, y + r, outline=RING_TRACK, width=RING_WIDTH)
            start, extent = ring_arc(snap.dwell_progress)
            c.create_arc(x - r, y - r, x + r, y + r, start=start, extent=extent, style="arc",
                         outline=RING_FILL, width=RING_WIDTH)
        if snap.pinch_progress is not None and snap.cursor is not None and snap.pinch_progress > 0.05:
            x, y = snap.cursor[0] + 26, snap.cursor[1] + 26
            r = 9
            done = snap.pinch_state in ("confirmed", "dragging", "touch", "drag", "held")
            blocked = snap.pinch_state == "blocked"  # fingers closed but the pinch is not counting
            c.create_oval(x - r, y - r, x + r, y + r, outline=NAIVE_RED if blocked else RING_FILL, width=2)
            start, extent = pinch_dot_arc(snap.pinch_progress)
            c.create_arc(x - r, y - r, x + r, y + r, start=start, extent=extent, style="pieslice",
                         fill=NAIVE_RED if blocked else RING_FILL if done else BADGE_FG, outline="")
        badge = badge_text(snap)
        if badge:
            color = STATUS.get(snap.tracking, (BADGE_FG,))[0]
            text = c.create_text(self.w - 16, 16, text=badge, anchor="ne", fill=BADGE_FG,
                                 font=("Helvetica", 16, "bold"))
            x0, y0, x1, y1 = c.bbox(text)
            c.create_rectangle(x0 - 34, y0 - 8, x1 + 12, y1 + 8, fill=BANNER_BG, outline=color, width=2)
            c.create_oval(x0 - 24, (y0 + y1) / 2 - 6, x0 - 12, (y0 + y1) / 2 + 6, fill=color, outline="")
            c.tag_raise(text)
        if snap.metrics:
            m = snap.metrics
            lines = "   ".join(f"{k} {v}" for k, v in m.items())
            c.create_text(16, self.h - 16, text=lines, anchor="sw", fill=BADGE_FG, font=("Menlo", 14))
        if not snap.permission_ok:
            self._banner("Accessibility permission missing: clicks are being dropped", WARN_BG, y=60)
        elif paused_message:
            self._banner(paused_message, BANNER_BG, y=60)

    def _banner(self, text, bg, y, size=28):
        c = self.canvas
        item = c.create_text(self.w / 2, y, text=text, fill=BANNER_FG, font=("Helvetica", size, "bold"),
                             width=self.w * 0.8, justify="center")
        x0, y0, x1, y1 = c.bbox(item)
        rect = c.create_rectangle(x0 - 24, y0 - 14, x1 + 24, y1 + 14, fill=bg, outline=BANNER_FG, width=2)
        c.tag_raise(item, rect)
