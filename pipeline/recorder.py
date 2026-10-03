"""Landmark session record/replay (JSONL), the harness for headless tests.

A recording is one JSON object per line. The first line is a header; every
camera frame after it is one line, including frames with no hand, so pauses,
exits, and timing survive replay:

    {"type": "header", "format": 1, "name": ..., "frame_size": [w, h], "mirror": true, ...}
    {"t": 12.345, "hand": null}
    {"t": 12.378, "hand": {"handedness": "Right", "confidence": 0.98, "landmarks": [[x, y, z], ...]}}

Replay yields (timestamp, LandmarkFrame | None) pairs, the same stream the
live tracker produces, so any downstream stage can run from a file.
"""

import json
import time
from datetime import datetime
from pathlib import Path

from pipeline.landmarks import LandmarkFrame

FORMAT_VERSION = 1
DIGITS = 5  # ~1/100 px at 1080p; keeps a 60 s session around 3 MB


class LandmarkRecorder:
    def __init__(self, path, **header):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w")
        self.frames = 0
        meta = {"type": "header", "format": FORMAT_VERSION, "created": datetime.now().isoformat(timespec="seconds")}
        meta.update(header)
        self._write(meta)

    def write(self, timestamp, frame):
        record = {"t": round(timestamp, 6), "hand": None}
        if frame is not None:
            record["hand"] = {
                "handedness": frame.handedness,
                "confidence": round(frame.confidence, 4),
                "landmarks": [[round(v, DIGITS) for v in p] for p in frame.landmarks],
            }
        self._write(record)
        self.frames += 1

    def _write(self, obj):
        self._file.write(json.dumps(obj, separators=(",", ":")) + "\n")

    def close(self):
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _parse_frame(record):
    hand = record.get("hand")
    if hand is None:
        return None
    return LandmarkFrame(
        landmarks=tuple(tuple(p) for p in hand["landmarks"]),
        handedness=hand["handedness"],
        confidence=hand["confidence"],
        timestamp=record["t"],
    )


def read_recording(path):
    """Load a whole recording. Returns (header, [(timestamp, LandmarkFrame | None), ...])."""
    lines = Path(path).read_text().splitlines()
    header = json.loads(lines[0])
    if header.get("type") != "header":
        raise ValueError(f"{path}: first line is not a recording header")
    if header.get("format") != FORMAT_VERSION:
        raise ValueError(f"{path}: recording format {header.get('format')}, expected {FORMAT_VERSION}")
    frames = []
    for line in lines[1:]:
        if line.strip():
            record = json.loads(line)
            frames.append((record["t"], _parse_frame(record)))
    return header, frames


def replay(path, realtime=False, sleep=time.sleep):
    """Yield (timestamp, LandmarkFrame | None) from a recording, optionally at the original pace."""
    _, frames = read_recording(path)
    previous = None
    for t, frame in frames:
        if realtime and previous is not None:
            sleep(max(0.0, t - previous))
        previous = t
        yield t, frame
