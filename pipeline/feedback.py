"""CONJ-17 (+ CONJ-18 hooks): what the user hears and sees when something happens.

Feedback subscribes to applied ClickEvents (ActionMapper), spell casts
(Engine), and mode changes (ModeState). It plays the local click and spell
sounds and hands words to the voice (CONJ-18). The visual side, the cursor
trail and the spell-name flash, is drawn by the overlay; Feedback only holds
the switches, so the settings panel has one place to flip them.

Every effect can be turned off: visual noise and sound are accessibility
concerns in their own right.
"""

from dataclasses import dataclass

from pipeline.events import Action
from pipeline.modes import Mode

MODE_WORDS = {Mode.PINCH: "Pinch mode", Mode.DWELL: "Dwell mode", Mode.CUSTOM: "Spell mode",
              Mode.PAUSED: "Paused"}
CLICK_WORDS = ["Click", "Right click", "Double click"]
# Every fixed phrase Conjure can say; scripts/pregenerate_voices.py renders these plus the stock spell names.
FIXED_PHRASES = list(MODE_WORDS.values()) + ["Resumed"] + CLICK_WORDS


@dataclass
class FeedbackSettings:
    trail: bool = True
    sound: bool = True
    voice: bool = True
    voice_clicks: bool = False  # speak "click" on every click: off by default, it gets tiring


class Feedback:
    def __init__(self, player, voice, click_sound, spell_sound, settings=None, sounds=None):
        """sounds: optional low-latency SoundBank for the short click and spell sounds."""
        self.player = player
        self.sounds = sounds
        self.voice = voice
        self.click_sound = click_sound
        self.spell_sound = spell_sound
        self.settings = settings or FeedbackSettings()

    def on_click(self, event):
        if event.action in (Action.SCROLL, Action.DRAG_END):
            return
        if self.settings.sound:
            self._play(self.click_sound)
        if self.settings.voice and self.settings.voice_clicks and event.action != Action.DRAG_START:
            self.voice.speak({Action.RIGHT: "Right click", Action.DOUBLE: "Double click"}.get(event.action, "Click"))

    def on_spell(self, name):
        if self.settings.sound:
            self._play(self.spell_sound)
        if self.settings.voice:
            self.voice.speak(name)

    def on_mode(self, old, new):
        if new == Mode.PAUSED or old == Mode.PAUSED:
            word = "Paused" if new == Mode.PAUSED else "Resumed"
        else:
            word = MODE_WORDS[new]
        if self.settings.voice:
            self.voice.speak(word)

    def _play(self, path):
        if self.sounds is not None:
            self.sounds.play(path)
        else:
            self.player.play_file(path)

    def toggle(self, name):
        setattr(self.settings, name, not getattr(self.settings, name))
        return getattr(self.settings, name)
