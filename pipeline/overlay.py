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


def badge_text(snapshot):
    if not snapshot.mode:
        return ""
    return f"Conjure: {snapshot.mode}"


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

    def draw(self, snap, paused_message=None):
        c = self.canvas
        c.delete("all")
        if snap.dwell_progress is not None and snap.cursor is not None:
            x, y = snap.cursor
            r = RING_RADIUS
            c.create_oval(x - r, y - r, x + r, y + r, outline=RING_TRACK, width=RING_WIDTH)
            start, extent = ring_arc(snap.dwell_progress)
            c.create_arc(x - r, y - r, x + r, y + r, start=start, extent=extent, style="arc",
                         outline=RING_FILL, width=RING_WIDTH)
        badge = badge_text(snap)
        if badge:
            c.create_text(self.w - 16, 16, text=badge, anchor="ne", fill=BADGE_FG, font=("Helvetica", 16, "bold"))
        if not snap.permission_ok:
            self._banner("Accessibility permission missing: clicks are being dropped", WARN_BG, y=60)
        elif paused_message:
            self._banner(paused_message, BANNER_BG, y=60)

    def _banner(self, text, bg, y):
        c = self.canvas
        item = c.create_text(self.w / 2, y, text=text, fill=BANNER_FG, font=("Helvetica", 28, "bold"))
        x0, y0, x1, y1 = c.bbox(item)
        rect = c.create_rectangle(x0 - 24, y0 - 14, x1 + 24, y1 + 14, fill=bg, outline=BANNER_FG, width=2)
        c.tag_raise(item, rect)
