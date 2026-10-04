"""CONJ-14: the settings panel. Big targets, usable with Conjure itself in dwell mode.

Every control is at least MIN_TARGET_PX tall. Aqua tk.Buttons ignore their
height option on macOS (they render ~22 px), so buttons here are Labels
styled and bound as buttons. No sliders: they are hard to drag by dwell, so
every value has - and + buttons instead. Changes go through settings_model
on the pipeline thread, apply live, and are saved to the profile.
"""

import tkinter as tk

from pipeline import settings_model as sm
from pipeline.modes import Mode

MIN_TARGET_PX = 60
BG = "#1e1433"
FG = "#f2ecff"
ACCENT = "#f5c542"
BUTTON_BG = "#3b2a5c"
BUTTON_ACTIVE = "#5a4290"
SELECTED_BG = "#f5c542"
SELECTED_FG = "#1e1433"
FONT = ("Helvetica", 18, "bold")
SMALL = ("Helvetica", 14)


class BigButton(tk.Label):
    """A Label that behaves like a button and honors its size on macOS (>= MIN_TARGET_PX tall)."""

    def __init__(self, parent, text, command, width=8, **kw):
        super().__init__(parent, text=text, font=FONT, bg=BUTTON_BG, fg=FG, width=width, padx=12, pady=18,
                         relief="raised", bd=2, cursor="hand2", **kw)
        self.command = command
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self._selected = False

    def _click(self, _event):
        self.command()

    def _set_hover(self, hover):
        if not self._selected:
            self.configure(bg=BUTTON_ACTIVE if hover else BUTTON_BG)

    def set_selected(self, selected):
        self._selected = selected
        self.configure(bg=SELECTED_BG if selected else BUTTON_BG, fg=SELECTED_FG if selected else FG)


class SettingsPanel:
    def __init__(self, root, engine, actions, feedback_settings, toggle_feedback):
        """actions: dict of UI-level callbacks: calibrate, record_spell, toggle_preview, hide, quit.
        feedback_settings / toggle_feedback: the trail, sound, and voice switches (CONJ-17/18)."""
        self.engine = engine
        self.feedback_settings = feedback_settings
        self.win = tk.Toplevel(root, bg=BG)
        self.win.title("Conjure")
        self.win.attributes("-topmost", True)
        self.win.protocol("WM_DELETE_WINDOW", actions["hide"])
        self.values = {}

        tk.Label(self.win, text="Conjure", font=("Helvetica", 30, "bold"), bg=BG, fg=ACCENT).grid(
            row=0, column=0, columnspan=4, pady=(14, 4))
        self.status = tk.Label(self.win, text="", font=SMALL, bg=BG, fg=FG)
        self.status.grid(row=1, column=0, columnspan=4, pady=(0, 10))

        modes = tk.Frame(self.win, bg=BG)
        modes.grid(row=2, column=0, columnspan=4, pady=6)
        self.mode_buttons = {}
        for i, (mode, label) in enumerate(((Mode.PINCH, "Pinch"), (Mode.DWELL, "Dwell"), (Mode.CUSTOM, "Spell"))):
            b = BigButton(modes, label, lambda m=mode: self._submit(sm.set_click_mode, m.value))
            b.grid(row=0, column=i, padx=6)
            self.mode_buttons[mode] = b
        self.pause_button = BigButton(modes, "Pause", lambda: self._submit(sm.toggle_user_pause))
        self.pause_button.grid(row=0, column=3, padx=6)

        rows = [
            ("sensitivity", "Sensitivity", sm.step_sensitivity),
            ("smoothing", "Smoothing", sm.step_smoothing),
            ("dwell_ms", "Dwell time", sm.step_dwell_ms),
            ("dwell_radius", "Dwell area", sm.step_dwell_radius),
            ("spell_threshold", "Spell forgiveness", sm.step_spell_threshold),
        ]
        for r, (key, label, step) in enumerate(rows, start=3):
            tk.Label(self.win, text=label, font=FONT, bg=BG, fg=FG, anchor="w", width=16).grid(
                row=r, column=0, padx=(16, 6), pady=5, sticky="w")
            BigButton(self.win, "-", lambda s=step: self._submit(s, -1), width=3).grid(row=r, column=1, pady=5)
            value = tk.Label(self.win, text="", font=FONT, bg=BG, fg=ACCENT, width=9)
            value.grid(row=r, column=2)
            self.values[key] = value
            BigButton(self.win, "+", lambda s=step: self._submit(s, +1), width=3).grid(
                row=r, column=3, padx=(0, 16), pady=5)

        effects = tk.Frame(self.win, bg=BG)
        effects.grid(row=8, column=0, columnspan=4, pady=8)
        self.precision_button = BigButton(effects, "Precision", lambda: self._submit(sm.toggle_precision), width=12)
        self.precision_button.grid(row=0, column=0, padx=5)
        self.feedback_buttons = {}
        for i, (key, label) in enumerate((("trail", "Trail"), ("sound", "Sound"), ("voice", "Voice")), start=1):
            b = BigButton(effects, label, lambda k=key: toggle_feedback(k), width=8)
            b.grid(row=0, column=i, padx=5)
            self.feedback_buttons[key] = (b, label)

        stage = tk.Frame(self.win, bg=BG)
        stage.grid(row=9, column=0, columnspan=4, pady=4)
        self.tutorial_button = BigButton(stage, "Tutorial mode", actions["tutorial"], width=13)
        self.tutorial_button.grid(row=0, column=0, padx=5)
        self.metrics_button = BigButton(stage, "Metrics", actions["metrics"], width=10)
        self.metrics_button.grid(row=0, column=1, padx=5)

        actions_row = tk.Frame(self.win, bg=BG)
        actions_row.grid(row=10, column=0, columnspan=4, pady=(8, 16))
        for i, (label, fn) in enumerate((("Calibrate", actions["calibrate"]), ("Record spell", actions["record_spell"]),
                                         ("Preview", actions["toggle_preview"]), ("Hide", actions["hide"]),
                                         ("Quit", actions["quit"]))):
            BigButton(actions_row, label, fn, width=10 if i < 2 else 7).grid(row=0, column=i, padx=5)

    def _submit(self, fn, *args):
        self.engine.submit(lambda e: fn(e, *args))

    def refresh(self):
        v = sm.current(self.engine)
        for mode, button in self.mode_buttons.items():
            button.set_selected(v["click_mode"] == mode)
        self.pause_button.configure(text="Resume" if v["user_paused"] else "Pause")
        self.pause_button.set_selected(v["user_paused"])
        self.precision_button.configure(text=f"Precision: {'on' if v['precision'] else 'off'}")
        self.precision_button.set_selected(v["precision"])
        for key, (button, label) in self.feedback_buttons.items():
            on = getattr(self.feedback_settings, key)
            button.configure(text=f"{label}: {'on' if on else 'off'}")
            button.set_selected(on)
        self.values["sensitivity"].configure(text=f"{v['sensitivity']:.1f}x")
        self.values["smoothing"].configure(text=f"{v['smoothing']} of 5")
        self.values["dwell_ms"].configure(text=f"{v['dwell_ms'] / 1000:.1f} s")
        self.values["dwell_radius"].configure(text=f"{v['dwell_radius']} px")
        self.values["spell_threshold"].configure(
            text=f"{v['spell_threshold']:.2f}" if v["spell_threshold"] is not None else "no spell")
        self.tutorial_button.set_selected(self.engine.tutorial is not None)
        self.metrics_button.configure(text=f"Metrics: {'on' if self.engine.show_metrics else 'off'}")
        self.metrics_button.set_selected(self.engine.show_metrics)
        spell = f"spell: {v['spell']}" if v["spell"] else "no spell recorded"
        cal = "calibrated" if v["calibrated"] else "not calibrated (using the default area)"
        self.status.configure(text=f"Mode: {v['mode'].value}  |  {spell}  |  {cal}")

    def show(self):
        self.win.deiconify()
        self.win.lift()

    def hide(self):
        self.win.withdraw()

    @property
    def visible(self):
        return self.win.state() != "withdrawn"
