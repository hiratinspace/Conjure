"""Spoken feedback, offline layer (CONJ-17/18).

LocalVoice speaks a phrase from a pre-generated clip in `voice_dir` when one
exists (`<slug>.mp3`, rendered ahead of time by scripts/pregenerate_voices.py),
and otherwise falls back to macOS's built-in `say`, which is also offline.
The ElevenLabs voice (pipeline/voice_elevenlabs.py) sits in front of this and
falls through to it on any failure, so the demo never depends on the network.
"""

import re


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "phrase"


class LocalVoice:
    def __init__(self, player, voice_dir, say_fallback=True):
        self.player = player
        self.voice_dir = voice_dir
        self.say_fallback = say_fallback

    def clip(self, text):
        path = self.voice_dir / f"{slug(text)}.mp3"
        return path if path.exists() else None

    def speak(self, text):
        path = self.clip(text)
        if path is not None:
            self.player.play_file(path)
        elif self.say_fallback:
            self.player.say(text)


class SilentVoice:
    def speak(self, text):
        pass
