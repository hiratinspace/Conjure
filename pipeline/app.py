"""The Tk application: owns the main thread while the pipeline runs on a worker thread.

macOS requires every window (Tk and OpenCV alike) on the main thread, so the
camera, tracker, and engine run in `PipelineThread`, and this app polls
UiState to draw the overlay and the preview window.

The settings panel (shown at startup) is the main control surface. Preview
window keys: p hides it, m cycles the click mode, g records a spell,
c calibrates, s shows the settings panel, q quits.
"""

import logging
import signal
import threading
import time
import tkinter as tk
from collections import deque

import config
from pipeline.events import Action, ClickEvent
from pipeline.gesture_recorder import DONE
from pipeline.modes import CLICK_MODES, USER, Mode
from pipeline.action_bar import ActionBar
from pipeline.overlay import Overlay
from pipeline.settings_panel import ACCENT, BG, BigButton, SettingsPanel
from pipeline.tutorial import NaivePointer
from pipeline.ui_state import NaiveClick, SpellCast

log = logging.getLogger("conjure.app")

POLL_MS = 33
PREVIEW_EVERY = 2  # refresh the preview image every Nth poll (~15 Hz)
PANEL_REFRESH_EVERY = 5  # refresh the settings panel every Nth poll (~6 Hz)
NOTICE_S = 6.0
BIG_FONT = ("Helvetica", 22, "bold")


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
    def __init__(self, ui_state, modes, engine, feedback, screen_size, show_preview):
        self.ui = ui_state
        self.feedback = feedback
        self._trail = deque(maxlen=config.TRAIL_LENGTH)
        self._ripples = []  # (x, y, t_start)
        self._flash = None  # (text, x, y, t_until)
        self._naive = []  # (x, y, t_start) tutorial-mode clicks
        self.screen_size = screen_size
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
        self.action_bar = ActionBar(self.root, engine, screen_size)
        self._bar_manual = False  # the user toggled the bar: stop auto showing/hiding it
        self.action_bar.hide()
        self.panel = SettingsPanel(self.root, engine, {
            "calibrate": self.calibrate, "record_spell": self.record_spell,
            "toggle_preview": self.toggle_preview, "hide": self.toggle_panel, "quit": self.quit,
            "tutorial": self.toggle_tutorial, "metrics": self.toggle_metrics, "actions": self.toggle_action_bar,
            "tune": self.tune},
            feedback.settings, feedback.toggle, screen_size)
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
            self.preview_win.title("Conjure preview (p hide, m mode, g spell, c calibrate, s settings, "
                                   "t tutorial, k metrics, q quit)")
            self.preview_win.protocol("WM_DELETE_WINDOW", self.toggle_preview)
            self.preview_label = tk.Label(self.preview_win, bg="black")
            self.preview_label.pack()
            for key, fn in (("p", self.toggle_preview), ("m", self.cycle_mode), ("g", self.record_spell),
                            ("c", self.calibrate), ("s", self.toggle_panel), ("t", self.toggle_tutorial),
                            ("k", self.toggle_metrics), ("q", self.quit)):
                self.preview_win.bind(f"<KeyPress-{key}>", lambda _e, fn=fn: fn())
            self.ui.preview_visible = True
        else:
            self.ui.preview_visible = False
            self.preview_win.destroy()
            self.preview_win = self.preview_label = self._photo = None

    def toggle_tutorial(self):
        """The before/after pitch: naive fingertip pointer vs Conjure. Naive clicks are shown, not injected."""
        def flip(engine):
            on = engine.tutorial is None
            engine.set_tutorial(NaivePointer(self.screen_size, config.CAMERA_WIDTH / config.CAMERA_HEIGHT)
                                if on else None)
            log.info("tutorial mode %s", "on" if on else "off")
        self.engine.submit(flip)

    def toggle_metrics(self):
        self.engine.submit(lambda e: setattr(e, "show_metrics", not e.show_metrics))

    def toggle_action_bar(self):
        self._bar_manual = True
        if self.action_bar.visible:
            self.action_bar.hide()
        else:
            self.action_bar.show()

    def toggle_panel(self):
        if self.panel.visible:
            self.panel.hide()
        else:
            self.panel.show()

    def cycle_mode(self):
        current = self.modes.click_mode
        nxt = CLICK_MODES[(CLICK_MODES.index(current) + 1) % len(CLICK_MODES)]
        self.set_click_mode(nxt)

    def set_click_mode(self, mode):
        def apply(engine):
            engine.modes.set_click_mode(mode)
            engine.persist()
        self.engine.submit(apply)
        log.info("click mode: %s", mode.value)

    def calibrate(self):
        self.engine.submit(lambda e: e.start_flow("calibrate"))
        log.info("calibrating: follow the prompts on screen")

    def tune(self):
        self.engine.submit(lambda e: e.start_flow("tune"))
        log.info("tuning: rest your hand and follow the prompts on screen")

    def record_spell(self):
        self.engine.submit(lambda e: e.start_flow("record"))
        log.info("recording a spell: follow the prompts on screen")

    def _open_naming(self):
        """'Name your spell': big stock-name buttons (no typing needed) plus an optional typed name."""
        win = self.naming_win = tk.Toplevel(self.root, bg=BG)
        win.title("Name your spell")
        win.attributes("-topmost", True)
        tk.Label(win, text="Name your spell", font=("Helvetica", 30, "bold"), bg=BG, fg=ACCENT, pady=16).pack()
        grid = tk.Frame(win, bg=BG)
        grid.pack(padx=20, pady=10)
        for i, name in enumerate(config.STOCK_SPELL_NAMES):
            BigButton(grid, name, lambda n=name: self._name_chosen(n), width=11).grid(
                row=i // 3, column=i % 3, padx=8, pady=8)
        row = tk.Frame(win, bg=BG)
        row.pack(pady=10)
        entry = tk.Entry(row, font=BIG_FONT, width=16)
        entry.pack(side="left", padx=8)
        BigButton(row, "Use typed name", lambda: self._name_chosen(entry.get().strip()), width=14).pack(side="left")
        BigButton(win, "Discard", self._discard_recording).pack(pady=(0, 16))
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

    def _collect_effects(self, snap, now):
        """Trail points, click ripples, and spell flashes from the latest snapshot and events."""
        if snap.cursor is not None and snap.hand_visible and self.modes.mode != Mode.PAUSED:
            if not self._trail or self._trail[-1] != snap.cursor:
                self._trail.append(snap.cursor)
        else:
            self._trail.clear()
        for event in self.ui.drain_events():
            if isinstance(event, SpellCast):
                x, y = event.position
                self._flash = (event.name, x, y, now + config.SPELL_FLASH_S)
            elif isinstance(event, NaiveClick):
                self._naive.append((*event.position, now))
            elif isinstance(event, ClickEvent) and event.action in (Action.LEFT, Action.RIGHT, Action.DOUBLE,
                                                                     Action.DRAG_START):
                self._ripples.append((*event.position, now))
        self._ripples = [r for r in self._ripples if now - r[2] < config.CLICK_RIPPLE_S]
        self._naive = [r for r in self._naive if now - r[2] < 2 * config.CLICK_RIPPLE_S]

    def paused_message(self, snap):
        if self.modes.mode != Mode.PAUSED:
            return None
        if USER in self.modes.pause_reasons:
            return "Paused: press Resume in the Conjure panel"
        return "Paused: raise your hand to continue"

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
        now = time.monotonic()
        notice = self._notice if now < self._notice_until else ""
        self._collect_effects(snap, now)
        trail = list(self._trail) if self.feedback.settings.trail else []
        ripples = [(x, y, (now - t0) / config.CLICK_RIPPLE_S) for x, y, t0 in self._ripples]
        flash = self._flash[:3] if self._flash and now < self._flash[3] else None
        naive = [(x, y, (now - t0) / (2 * config.CLICK_RIPPLE_S)) for x, y, t0 in self._naive]
        self.overlay.draw(snap, self.paused_message(snap), notice, trail, ripples, flash, naive)
        if self._polls % PANEL_REFRESH_EVERY == 0:
            self.panel.refresh()
            if not self._bar_manual:  # useful when a click cannot choose its own button: every mode but pinch
                want = self.modes.click_mode != Mode.PINCH or self.engine.actions.dragging
                if want != self.action_bar.visible:
                    (self.action_bar.show if want else self.action_bar.hide)()
            if self.action_bar.visible:
                self.action_bar.refresh()
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
