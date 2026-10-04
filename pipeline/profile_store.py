"""CONJ-13: the profile store. One local JSON file, no database, no cloud.

load() never raises: a missing file gives defaults (first launch), and a
corrupt, invalid, or old-version file gives defaults plus a warning, with the
bad file moved aside to `<name>.bad-<timestamp>` so it is not lost or
silently overwritten. Validation is all-or-nothing (profile_schema), so a
profile is never half-applied.

save() is atomic: write a temp file in the same directory, flush and fsync
it, then os.replace() over the real file. A crash mid-save leaves the old
profile intact.
"""

import json
import logging
import os
import tempfile
import time
from pathlib import Path

from pipeline.profile_schema import ProfileError, default_profile, profile_from_dict, profile_to_dict

log = logging.getLogger("conjure.profile")


class ProfileStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        """Returns (profile, warning or None)."""
        if not self.path.exists():
            log.info("no profile at %s yet: using defaults", self.path)
            return default_profile(), None
        try:
            profile = profile_from_dict(json.loads(self.path.read_text()))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ProfileError) as e:
            backup = self.path.with_name(f"{self.path.name}.bad-{time.strftime('%Y%m%d-%H%M%S')}")
            try:
                os.replace(self.path, backup)
            except OSError:
                backup = None
            warning = (f"Your saved profile could not be loaded ({e}), so Conjure started with default settings."
                       + (f" The old file was kept as {backup.name}." if backup else ""))
            log.warning("%s", warning)
            return default_profile(), warning
        log.info("loaded profile from %s", self.path)
        return profile, None

    def save(self, profile):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(profile_to_dict(profile), indent=1)
        fd, tmp = tempfile.mkstemp(prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        log.debug("saved profile to %s", self.path)
