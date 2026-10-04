"""CONJ-14: the settings panel. Big targets, usable with Conjure itself in dwell mode.

Every control is at least MIN_TARGET_PX tall. Aqua tk.Buttons ignore their
height option on macOS (they render ~22 px), so buttons here are Labels
styled and bound as buttons. No sliders: they are hard to drag by dwell, so
every value has - and + buttons instead. Changes go through settings_model
on the pipeline thread, apply live, and are saved to the profile.

Layout: the value rows sit in two columns so the whole panel fits a 900 px
tall laptop screen with room to spare, and it opens at the left edge so it
does not cover the demo page in the middle.
"""

import tkinter as tk

from pipeline import palette as P
from pipeline import settings_model as sm
from pipeline.modes import Mode

MIN_TARGET_PX = 60
BG = P.NAVY
FG = P.WHITE
ACCENT = P.SKY_LIGHT
BUTTON_BG = P.NAVY_3
BUTTON_BORDER = P.BORDER
BUTTON_ACTIVE = "#1b2d55"
SELECTED_BG = P.SKY
SELECTED_FG = P.NAVY
FONT = ("Helvetica", 17, "bold")
SMALL = ("Helvetica", 13)
TITLE_FONT = ("Helvetica", 26, "bold")
PAD = 5


class BigButton(tk.Label):
    """A Label that behaves like a button and honors its size on macOS (>= MIN_TARGET_PX tall)."""

    def __init__(self, parent, text, command, width=8, **kw):
        super().__init__(parent, text=text, font=FONT, bg=BUTTON_BG, fg=FG, width=width, padx=16, pady=18,
                         relief="flat", bd=0, cursor="hand2", highlightthickness=2,
                         highlightbackground=BUTTON_BORDER, highlightcolor=BUTTON_BORDER, **kw)
        self.command = command
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self._selected = False

    def _click(self, _event):
        self.command()

    def _set_hover(self, hover):
        if not self._selected:
            self.configure(bg=BUTTON_ACTIVE if hover else BUTTON_BG,
                           highlightbackground=P.SKY if hover else BUTTON_BORDER)

    def set_selected(self, selected):
        self._selected = selected
        self.configure(bg=SELECTED_BG if selected else BUTTON_BG, fg=SELECTED_FG if selected else FG,
                       highlightbackground=P.SKY_LIGHT if selected else BUTTON_BORDER)


class SettingsPanel:
    def __init__(self, root, engine, actions, feedback_settings, toggle_feedback, screen_size=None):
        """actions: dict of UI-level callbacks: calibrate, record_spell, toggle_preview, hide, quit, tutorial,
        metrics, actions, tune. feedback_settings / toggle_feedback: the trail, sound, and voice switches."""
        self.engine = engine
        self.feedback_settings = feedback_settings
        self.win = tk.Toplevel(root, bg=BG)
        self.win.title("Conjure")
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", actions["hide"])
        self.values = {}
        body = tk.Frame(self.win, bg=BG, padx=14, pady=10)
        body.pack()

        tk.Label(body, text="Conjure", font=TITLE_FONT, bg=BG, fg=ACCENT).grid(row=0, column=0, columnspan=2,
                                                                               pady=(2, 6))

        modes = tk.Frame(body, bg=BG)
        modes.grid(row=1, column=0, columnspan=2, pady=PAD)
        self.mode_buttons = {}
        for i, (mode, label) in enumerate(((Mode.PINCH, "Pinch"), (Mode.TOUCH, "Touch"), (Mode.DWELL, "Dwell"),
                                           (Mode.CUSTOM, "Spell"))):
            b = BigButton(modes, label, lambda m=mode: self._submit(sm.set_click_mode, m.value), width=6)
            b.grid(row=0, column=i, padx=4)
            self.mode_buttons[mode] = b
        self.pause_button = BigButton(modes, "Pause", lambda: self._submit(sm.toggle_user_pause), width=6)
        self.pause_button.grid(row=0, column=4, padx=(16, 4))

        feel = tk.Frame(body, bg=BG)
        feel.grid(row=2, column=0, columnspan=2, pady=PAD, sticky="w")
        tk.Label(feel, text="Feel", font=FONT, bg=BG, fg=FG, width=5, anchor="w").grid(row=0, column=0, padx=(4, 6))
        self.feel_buttons = {}
        for i, name in enumerate(("precise", "balanced", "fast")):
            b = BigButton(feel, name.capitalize(), lambda n=name: self._submit(sm.set_feel, n), width=8)
            b.grid(row=0, column=i + 1, padx=4)
            self.feel_buttons[name] = b
        self.pointer_button = BigButton(feel, "Pointer: Mouse", lambda: self._submit(sm.toggle_pointer_style),
                                        width=14)
        self.pointer_button.grid(row=0, column=4, padx=(16, 4))

        left = [("sensitivity", "Sensitivity", sm.step_sensitivity), ("smoothing", "Smoothing", sm.step_smoothing),
                ("responsiveness", "Response", sm.step_responsiveness)]
        right = [("dwell_ms", "Dwell time", sm.step_dwell_ms), ("dwell_radius", "Dwell area", sm.step_dwell_radius),
                 ("spell_threshold", "Tolerance", sm.step_spell_threshold)]
        for col, rows in enumerate((left, right)):
            frame = tk.Frame(body, bg=BG)
            frame.grid(row=3, column=col, padx=(0, 18) if col == 0 else 0, sticky="n")
            for r, (key, label, step) in enumerate(rows):
                tk.Label(frame, text=label, font=FONT, bg=BG, fg=FG, anchor="w", width=10).grid(
                    row=r, column=0, padx=(4, 6), pady=PAD, sticky="w")
                BigButton(frame, "-", lambda s=step: self._submit(s, -1), width=3).grid(row=r, column=1, pady=PAD)
                value = tk.Label(frame, text="", font=FONT, bg=BG, fg=ACCENT, width=7)
                value.grid(row=r, column=2)
                self.values[key] = value
                BigButton(frame, "+", lambda s=step: self._submit(s, +1), width=3).grid(row=r, column=3, pady=PAD)

        toggles = tk.Frame(body, bg=BG)
        toggles.grid(row=4, column=0, columnspan=2, pady=(10, PAD))
        self.precision_button = BigButton(toggles, "Acceleration", lambda: self._submit(sm.toggle_precision), width=14)
        self.precision_button.grid(row=0, column=0, padx=4)
        self.feedback_buttons = {}
        for i, (key, label) in enumerate((("trail", "Trail"), ("sound", "Sound"), ("voice", "Voice")), start=1):
            b = BigButton(toggles, label, lambda k=key: toggle_feedback(k), width=9)
            b.grid(row=0, column=i, padx=4)
            self.feedback_buttons[key] = (b, label)

        setup = tk.Frame(body, bg=BG)
        setup.grid(row=5, column=0, columnspan=2, pady=PAD)
        for i, (label, fn, w) in enumerate((("Tune", actions["tune"], 7), ("Record spell", actions["record_spell"], 11),
                                            ("Calibrate", actions["calibrate"], 9), ("Actions", actions["actions"], 8),
                                            ("Defaults", lambda: self._submit(sm.reset_settings), 8))):
            BigButton(setup, label, fn, width=w).grid(row=0, column=i, padx=4)

        system = tk.Frame(body, bg=BG)
        system.grid(row=6, column=0, columnspan=2, pady=(PAD, 6))
        self.tutorial_button = BigButton(system, "Tutorial", actions["tutorial"], width=8)
        self.tutorial_button.grid(row=0, column=0, padx=4)
        self.metrics_button = BigButton(system, "Metrics", actions["metrics"], width=8)
        self.metrics_button.grid(row=0, column=1, padx=4)
        for i, (label, fn) in enumerate((("Preview", actions["toggle_preview"]), ("Hide", actions["hide"]),
                                         ("Quit", actions["quit"])), start=2):
            BigButton(system, label, fn, width=7).grid(row=0, column=i, padx=4)

        self.status = tk.Label(body, text="", font=SMALL, bg=BG, fg=P.MUTED)
        self.status.grid(row=7, column=0, columnspan=2, pady=(2, 4))

        self.win.update_idletasks()
        if screen_size is not None:  # left edge, vertically centered, clear of the demo page in the middle
            h = self.win.winfo_reqheight()
            self.win.geometry(f"+12+{max(40, (screen_size[1] - h) // 2)}")

    def _submit(self, fn, *args):
        self.engine.submit(lambda e: fn(e, *args))

    def refresh(self):
        v = sm.current(self.engine)
        for mode, button in self.mode_buttons.items():
            button.set_selected(v["click_mode"] == mode)
        for name, button in self.feel_buttons.items():
            button.set_selected(v["feel"] == name and v["pointer_style"] == "mouse")
        self.pause_button.configure(text="Resume" if v["user_paused"] else "Pause")
        self.pause_button.set_selected(v["user_paused"])
        self.pointer_button.configure(text=f"Pointer: {'Mouse' if v['pointer_style'] == 'mouse' else 'Direct'}")
        label = "Acceleration" if v["pointer_style"] == "mouse" else "Precision"
        self.precision_button.configure(text=f"{label}: {'on' if v['precision'] else 'off'}")
        self.precision_button.set_selected(v["precision"])
        for key, (button, label) in self.feedback_buttons.items():
            on = getattr(self.feedback_settings, key)
            button.configure(text=f"{label}: {'on' if on else 'off'}")
            button.set_selected(on)
        self.tutorial_button.set_selected(self.engine.tutorial is not None)
        self.metrics_button.configure(text=f"Metrics: {'on' if self.engine.show_metrics else 'off'}")
        self.metrics_button.set_selected(self.engine.show_metrics)
        self.values["sensitivity"].configure(text=f"{v['sensitivity']:.1f}x")
        self.values["smoothing"].configure(text=f"{v['smoothing']} of 5")
        self.values["responsiveness"].configure(text=f"{v['responsiveness']} of 5")
        self.values["dwell_ms"].configure(text=f"{v['dwell_ms'] / 1000:.1f} s")
        self.values["dwell_radius"].configure(text=f"{v['dwell_radius']} px")
        self.values["spell_threshold"].configure(
            text=f"{v['spell_threshold']:.2f}" if v["spell_threshold"] is not None else "no spell")
        spell = f"spell: {v['spell']}" if v["spell"] else "no spell recorded"
        if v["pointer_style"] == "mouse":
            cal = "tuned to your hand" if self.engine.tuned else "not tuned yet (press Tune)"
        else:
            cal = "calibrated" if v["calibrated"] else "not calibrated (press Calibrate)"
        self.status.configure(text=f"Mode: {v['mode'].value}   |   {spell}   |   {cal}")

    def show(self):
        self.win.deiconify()
        self.win.lift()

    def hide(self):
        self.win.withdraw()

    @property
    def visible(self):
        return self.win.state() != "withdrawn"
