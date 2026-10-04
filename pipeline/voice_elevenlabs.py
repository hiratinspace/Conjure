"""CONJ-18: ElevenLabs text-to-speech. THE ONLY MODULE ALLOWED TO USE THE NETWORK.

speak(text), in order:
  1. a clip already on disk (pre-generated in audio/voice, or cached in
     audio/cache from an earlier call) plays immediately, no network;
  2. otherwise a TTS request runs on its own thread with a hard total
     deadline of `deadline_s` (1 s). If audio arrives in time it is cached and
     played; on any error, or when the deadline passes, the offline fallback
     (LocalVoice) speaks instead, right away. A response that arrives late is
     still cached, so the next cast of that spell is instant.

Nothing here runs on the frame loop: speak() only starts a thread. The API key
comes from the ELEVENLABS_API_KEY environment variable, is sent only as a
request header, and is never logged or written anywhere.
"""

import json
import logging
import threading
import urllib.request

from pipeline.voice import slug

log = logging.getLogger("conjure.voice")

API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_22050_32"


class ElevenLabsVoice:
    def __init__(self, api_key, voice_id, model_id, clip_dirs, cache_dir, player, fallback, deadline_s,
                 opener=urllib.request.urlopen):
        if not api_key:
            raise ValueError("ElevenLabsVoice needs an API key (ELEVENLABS_API_KEY)")
        self._api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.clip_dirs = list(clip_dirs)
        self.cache_dir = cache_dir
        self.player = player
        self.fallback = fallback
        self.deadline_s = deadline_s
        self._open = opener

    def __repr__(self):  # never show the key
        return f"ElevenLabsVoice(voice_id={self.voice_id!r}, model_id={self.model_id!r})"

    def _clip(self, text):
        for d in self.clip_dirs + [self.cache_dir]:
            path = d / f"{slug(text)}.mp3"
            if path.exists():
                return path
        return None

    def synthesize(self, text, timeout_s=None):
        """Blocking TTS request; returns MP3 bytes. Raises on any failure."""
        body = json.dumps({"text": text, "model_id": self.model_id}).encode()
        request = urllib.request.Request(API_URL.format(voice_id=self.voice_id), data=body, method="POST",
                                         headers={"xi-api-key": self._api_key, "Content-Type": "application/json",
                                                  "Accept": "audio/mpeg"})
        with self._open(request, timeout=timeout_s or self.deadline_s) as response:
            audio = response.read()
        if not audio:
            raise ValueError("empty audio response")
        return audio

    def _cache(self, text, audio):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{slug(text)}.mp3"
        tmp = path.with_suffix(".part")
        tmp.write_bytes(audio)
        tmp.replace(path)
        return path

    def speak(self, text):
        clip = self._clip(text)
        if clip is not None:
            self.player.play_file(clip)
            return
        threading.Thread(target=self._fetch_and_speak, args=(text,), name="conjure-tts", daemon=True).start()

    def _fetch_and_speak(self, text):
        result = {}
        done = threading.Event()

        def fetch():
            try:
                result["path"] = self._cache(text, self.synthesize(text))
            except Exception as e:  # network down, bad key, quota, timeout: all fall through
                result["error"] = e
            finally:
                done.set()

        threading.Thread(target=fetch, name="conjure-tts-fetch", daemon=True).start()
        if done.wait(self.deadline_s) and "path" in result:
            self.player.play_file(result["path"])
            return
        reason = type(result["error"]).__name__ if "error" in result else f"no audio within {self.deadline_s:.1f} s"
        log.info("ElevenLabs unavailable (%s): using the offline voice for %r", reason, text)
        self.fallback.speak(text)
