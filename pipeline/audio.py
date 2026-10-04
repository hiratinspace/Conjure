"""Local audio for feedback (CONJ-17) and the voice fallback (CONJ-18).

Everything plays on one background thread through macOS's own command-line
players (`afplay` for files, `say` as the last-resort voice), so no extra
dependency is needed and nothing here can stall the frame loop: callers only
enqueue. Nothing in this module touches the network.
"""

import logging
import queue
import subprocess
import threading

log = logging.getLogger("conjure.audio")


class SoundBank:
    """Short sounds preloaded with AppKit's NSSound: playback starts in a few ms, unlike spawning
    afplay (~50-100 ms). Falls back to `fallback.play_file` when AppKit is unavailable."""

    def __init__(self, fallback):
        self.fallback = fallback
        self._sounds = {}
        try:
            import AppKit
            self._appkit = AppKit
        except ImportError:
            self._appkit = None

    def _sound(self, path):
        path = str(path)
        if path not in self._sounds:
            self._sounds[path] = self._appkit.NSSound.alloc().initWithContentsOfFile_byReference_(path, True)
        return self._sounds[path]

    def preload(self, *paths):
        if self._appkit is not None:
            for p in paths:
                self._sound(p)

    def play(self, path):
        sound = self._sound(path) if self._appkit is not None else None
        if sound is None:
            self.fallback.play_file(path)
            return
        sound.stop()
        sound.play()


class AudioPlayer:
    """Plays queued jobs one at a time on a daemon thread. A job is a list of argv to run in order."""

    def __init__(self, runner=None, max_queue=8):
        self._run = runner or (lambda argv: subprocess.run(argv, check=False, stdout=subprocess.DEVNULL,
                                                            stderr=subprocess.DEVNULL, timeout=10))
        self._queue = queue.Queue(maxsize=max_queue)
        self._thread = threading.Thread(target=self._loop, name="conjure-audio", daemon=True)
        self._thread.start()

    def _loop(self):
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                if callable(job):
                    job()
                else:
                    self._run(job)
            except Exception:
                log.debug("audio job failed", exc_info=True)
            finally:
                self._queue.task_done()

    def submit(self, job):
        """Enqueue a job without blocking; when the queue is full the sound is dropped, not delayed."""
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            log.debug("audio queue full: dropped a sound")

    def play_file(self, path):
        self.submit(["afplay", str(path)])

    def say(self, text):
        self.submit(["say", text])

    def wait(self):
        """Block until every queued job has run (tests)."""
        self._queue.join()

    def close(self):
        self._queue.put(None)
