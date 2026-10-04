"""The action bar: big buttons that choose what the next click does.

A small always-on-top window (top right, under the status pill) with Left,
Right, Double, Drag, and Keep. It is meant to be operated with Conjure
itself, by dwell or any click, so every button is a BigButton (>= 60 px).
Like the settings panel it is a normal window, not click-through.

Changes go to the engine through engine.submit, like everything else the UI
does, and the bar highlights the current choice on refresh.
"""

import logging
import tkinter as tk

from pipeline import next_action as na
from pipeline import palette as P
from pipeline.settings_panel import ACCENT, BG, BigButton

log = logging.getLogger("conjure.actionbar")

TITLE = "Conjure actions"
BUTTONS = ((na.CHOICES[0], "Left"), (na.CHOICES[1], "Right"), (na.CHOICES[2], "Double"), (na.DRAG, "Drag"))


def make_non_activating(title):
    """Keep the bar from stealing focus from the app being controlled, where macOS allows it."""
    try:
        import AppKit
        for window in AppKit.NSApp.windows():
            if window.title() == title:
                window.setLevel_(AppKit.NSFloatingWindowLevel)
                window.setHidesOnDeactivate_(False)
                window.setCollectionBehavior_(AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                                              | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary)
                return True
    except Exception:
        log.debug("could not adjust the action bar window", exc_info=True)
    return False


class ActionBar:
    def __init__(self, root, engine, screen_size):
        self.engine = engine
        self.win = tk.Toplevel(root, bg=BG)
        self.win.title(TITLE)
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.hide)
        body = tk.Frame(self.win, bg=BG, padx=10, pady=8)
        body.pack()
        self.caption = tk.Label(body, text="Next click", font=("Helvetica", 13, "bold"), bg=BG, fg=ACCENT)
        self.caption.grid(row=0, column=0, columnspan=len(BUTTONS) + 1, sticky="w", padx=4, pady=(0, 4))
        self.buttons = {}
        for i, (choice, label) in enumerate(BUTTONS):
            b = BigButton(body, label, lambda c=choice: self._choose(c), width=6)
            b.grid(row=1, column=i, padx=3)
            self.buttons[choice] = b
        self.keep = BigButton(body, "Keep", self._toggle_sticky, width=5)
        self.keep.grid(row=1, column=len(BUTTONS), padx=(12, 3))
        self.hint = tk.Label(body, text="then click the target; falls back to Left after one use",
                             font=("Helvetica", 12), bg=BG, fg=P.MUTED)
        self.hint.grid(row=2, column=0, columnspan=len(BUTTONS) + 1, sticky="w", padx=4, pady=(4, 0))
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        self.win.geometry(f"+{screen_size[0] - w - 16}+56")
        make_non_activating(TITLE)

    def _choose(self, choice):
        self.engine.submit(lambda e: e.next_action.set(choice))

    def _toggle_sticky(self):
        self.engine.submit(lambda e: setattr(e.next_action, "sticky", not e.next_action.sticky))

    def refresh(self):
        na_ = self.engine.next_action
        for choice, button in self.buttons.items():
            button.set_selected(choice == na_.choice and not (choice == na.DRAG and na_.actions.dragging))
        if na_.actions.dragging:
            self.buttons[na.DRAG].configure(text="Drop")
            self.hint.configure(text="dragging: any click drops it")
        else:
            self.buttons[na.DRAG].configure(text="Drag")
            self.hint.configure(text="stays until used" if na_.sticky
                                else "then click the target; falls back to Left after one use")
        self.keep.set_selected(na_.sticky)

    def show(self):
        self.win.deiconify()
        self.win.lift()

    def hide(self):
        self.win.withdraw()

    @property
    def visible(self):
        return self.win.state() != "withdrawn"
