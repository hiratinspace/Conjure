"""Spell check: right after recording, prove the spell works before relying on it.

A recorded gesture that matches its own three samples can still fail when
cast for real (different speed, position, light). So after naming, the user
is asked to cast it `casts_wanted` times while the matcher runs without
clicking. The result is a plain count, "recognized 3 of 3", shown before the
spell is trusted, and a clear suggestion to record again when it is not.
"""

CASTS_WANTED = 3


class SpellCheck:
    def __init__(self, casts_wanted=CASTS_WANTED, timeout_s=20.0, min_gap_s=0.8):
        self.casts_wanted = casts_wanted
        self.timeout_s = timeout_s
        self.min_gap_s = min_gap_s
        self.active = False
        self.name = ""
        self.hits = 0
        self.prompt = ""
        self.verdict = ""  # set when done: the notice to show
        self._t_start = None
        self._t_hit = None

    def start(self, name):
        self.active = True
        self.name = name
        self.hits = 0
        self.verdict = ""
        self._t_start = None
        self._t_hit = None

    def cancel(self):
        self.active = False
        self.prompt = ""

    def update(self, matched, t):
        """matched: the matcher fired this frame. Returns True when the check just finished."""
        if not self.active:
            return False
        if self._t_start is None:
            self._t_start = t
        if matched and (self._t_hit is None or t - self._t_hit >= self.min_gap_s):
            self.hits += 1
            self._t_hit = t
        left = self.timeout_s - (t - self._t_start)
        self.prompt = (f"Check: cast '{self.name}' {self.casts_wanted} times... "
                       f"{self.hits}/{self.casts_wanted} recognized ({max(0, left):.0f} s)")
        if self.hits >= self.casts_wanted or left <= 0:
            self._finish()
            return True
        return False

    def _finish(self):
        self.active = False
        self.prompt = ""
        if self.hits >= self.casts_wanted:
            self.verdict = f"'{self.name}' recognized {self.hits} of {self.casts_wanted}: ready to use."
        elif self.hits > 0:
            self.verdict = (f"'{self.name}' recognized only {self.hits} of {self.casts_wanted}. Press Record spell "
                            "and do it again with a bigger motion, the same way each time.")
        else:
            self.verdict = (f"'{self.name}' was not recognized. Press Record spell and record a bigger, "
                            "more distinct motion.")
