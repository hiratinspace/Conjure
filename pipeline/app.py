"""The Tk application: owns the main thread while the pipeline runs on a worker thread.

macOS requires every window (Tk and OpenCV alike) on the main thread, so the
camera, tracker, and engine run in `PipelineThread`, and this app polls
UiState to draw the overlay and the preview window.

Preview window keys: p hides it, m cycles the click mode, g records a spell, c calibrates,
q quits.
"""

import logging
import signal
import threading
import time
import tkinter as tk

import config
from pipeline.gesture_recorder import DONE
from pipeline.modes import CLICK_MODES, Mode
from pipeline.overlay import Overlay

log = logging.getLogger("conjure.app")

POLL_MS = 33
PREVIEW_EVERY = 2  # refresh the preview image every Nth poll (~15 Hz)
NOTICE_S = 6.0
BIG_FONT = ("Helvetica", 22, "bold")
BUTTON = dict(font=BIG_FONT, width=12, height=2, padx=10, pady=10)  # >= 60 px targets (CONJ-14 dogfooding)


def to_photo(frame_bgr):
    """numpy BGR frame -> Tk PhotoImage via binary PPM (no imaging library needed)."""
    h, w = frame_bgr.shape[:2]
    rgb = frame_bgr[:, :, ::-1].tobytes()
    return tk.PhotoImage(data=b"P6 %d %d 255\n" % (w, h) + rgb, format="PPM")


class PipelineThread(threading.Thread):
    def __init__(self, run_fn):
        super().__init__(name="conjure-pipeline", daemon=True)
        self._run_fn = run_fn
        self.stop_event = threading.Event()
        self.error = None

    def run(self):
        try:
            self._run_fn(self.stop_event.is_set)
        except Exception as e:  # surfaced on the UI thread, which owns shutdown
            self.error = e
            log.exception("pipeline thread crashed")
        finally:
            self.stop_event.set()


class App:
    def __init__(self, ui_state, modes, engine, screen_size, show_preview):
        self.ui = ui_state
        self.modes = modes
        self.engine = engine
        self.naming_win = None
        self._notice = ""
        self._notice_until = 0.0
        self.root = tk.Tk()
        self.root.withdraw()
        self._accessory_app()
        self.overlay = Overlay(self.root, screen_size)
        self.preview_win = None
        self.preview_label = None
        self._photo = None
        self._polls = 0
        self.thread = None
        if show_preview:
            self.toggle_preview()

    @staticmethod
    def _accessory_app():
        """No Dock icon and no focus stealing: Conjure must not take focus from the app being controlled."""
        try:
            import AppKit
            AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
        except Exception:
            log.debug("could not set accessory activation policy", exc_info=True)

    def toggle_preview(self):
        if self.preview_win is None:
            self.preview_win = tk.Toplevel(self.root)
            self.preview_win.title("Conjure preview (p hide, m mode, g spell, c calibrate, q quit)")
            self.preview_win.protocol("WM_DELETE_WINDOW", self.toggle_preview)
            self.preview_label = tk.Label(self.preview_win, bg="black")
            self.preview_label.pack()
            for key, fn in (("p", self.toggle_preview), ("m", self.cycle_mode), ("g", self.record_spell),
                            ("c", self.calibrate),
                            ("q", self.quit)):
                self.preview_win.bind(f"<KeyPress-{key}>", lambda _e, fn=fn: fn())
            self.ui.preview_visible = True
        else:
            self.ui.preview_visible = False
            self.preview_win.destroy()
            self.preview_win = self.preview_label = self._photo = None

    def cycle_mode(self):
        current = self.modes.click_mode
        nxt = CLICK_MODES[(CLICK_MODES.index(current) + 1) % len(CLICK_MODES)]
        self.modes.set_click_mode(nxt)
        log.info("click mode: %s", nxt.value)

    def calibrate(self):
        self.engine.submit(lambda e: e.calibrator.start())
        log.info("calibrating: follow the prompts on screen")

    def record_spell(self):
        self.engine.submit(lambda e: e.recorder.start())
        log.info("recording a spell: follow the prompts on screen")

    def _open_naming(self):
        """'Name your spell': big stock-name buttons (no typing needed) plus an optional typed name."""
        win = self.naming_win = tk.Toplevel(self.root)
        win.title("Name your spell")
        win.attributes("-topmost", True)
        tk.Label(win, text="Name your spell", font=("Helvetica", 30, "bold"), pady=16).pack()
        grid = tk.Frame(win)
        grid.pack(padx=20, pady=10)
        for i, name in enumerate(config.STOCK_SPELL_NAMES):
            tk.Button(grid, text=name, command=lambda n=name: self._name_chosen(n), **BUTTON).grid(
                row=i // 3, column=i % 3, padx=8, pady=8)
        row = tk.Frame(win)
        row.pack(pady=10)
        entry = tk.Entry(row, font=BIG_FONT, width=16)
        entry.pack(side="left", padx=8)
        tk.Button(row, text="Use typed name", command=lambda: self._name_chosen(entry.get().strip()),
                  **BUTTON).pack(side="left")
        tk.Button(win, text="Discard", command=self._discard_recording, **BUTTON).pack(pady=(0, 16))
        win.protocol("WM_DELETE_WINDOW", self._discard_recording)

    def _close_naming(self):
        if self.naming_win is not None:
            self.naming_win.destroy()
            self.naming_win = None

    def _name_chosen(self, name):
        if not name:
            return
        self._close_naming()

        def finish(engine):
            template, warnings = engine.finish_recording(name)
            log.info("spell %r recorded (threshold %.2f)%s", template.name, template.threshold,
                     "; " + " ".join(warnings) if warnings else "")
        self.engine.submit(finish)

    def _discard_recording(self):
        self._close_naming()
        self.engine.submit(lambda e: e.recorder.cancel())

    def paused_message(self, snap):
        if self.modes.mode != Mode.PAUSED:
            return None
        return "Paused: raise your hand to continue" if not snap.hand_visible else "Paused"

    def _poll(self):
        if self.thread is not None and self.thread.stop_event.is_set():
            self.quit()
            return
        snap = self.ui.snapshot()
        if snap.recorder_state == DONE and self.naming_win is None:
            self._open_naming()
        if self.engine.notice:
            self._notice, self.engine.notice = self.engine.notice, ""
            self._notice_until = time.monotonic() + NOTICE_S
        notice = self._notice if time.monotonic() < self._notice_until else ""
        self.overlay.draw(snap, self.paused_message(snap), notice)
        self._polls += 1
        if self.preview_label is not None and snap.preview is not None and self._polls % PREVIEW_EVERY == 0:
            self._photo = to_photo(snap.preview)
            self.preview_label.configure(image=self._photo)
        self.root.after(POLL_MS, self._poll)

    def run(self, pipeline_fn):
        """Start the pipeline thread and block in the Tk main loop until quit."""
        self.thread = PipelineThread(pipeline_fn)
        self.thread.start()
        # Tk would swallow KeyboardInterrupt inside a callback; quit cleanly on Ctrl+C instead.
        signal.signal(signal.SIGINT, lambda *_: self.quit())
        self.root.after(POLL_MS, self._poll)
        try:
            self.root.mainloop()
        finally:
            self.thread.stop_event.set()
            self.thread.join(timeout=2.0)
        if self.thread.error is not None:
            raise self.thread.error

    def quit(self):
        if self.thread is not None:
            self.thread.stop_event.set()
        self.root.quit()
