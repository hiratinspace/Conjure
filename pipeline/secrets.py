"""Load secrets.env (gitignored) into the environment, for people who do not want to export keys per shell.

The file holds one KEY=value per line, no quotes needed, and is read once at startup. Values already
set in the environment win. The file is never written by Conjure, and tests/test_voice_elevenlabs.py
scans the repository for anything that looks like a key, so a stray copy cannot be committed.
"""

import logging
import os

log = logging.getLogger("conjure.secrets")


def load_secrets(path):
    """Returns the names loaded (never the values)."""
    loaded = []
    try:
        if not path.exists():
            return loaded
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip("'\"")
            if key and value and not os.environ.get(key):
                os.environ[key] = value
                loaded.append(key)
    except OSError as e:
        log.warning("could not read %s: %s", path, e)
    if loaded:
        log.info("loaded %s from %s", ", ".join(loaded), path.name)
    return loaded
