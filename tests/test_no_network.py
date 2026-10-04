"""Tripwire for the no-network rule: mediapipe 0.10.35 ships a Google telemetry
uploader (Clearcut, play.googleapis.com/log) that phones home on every run.
0.10.33 does not. This fails if an upgrade brings it back."""

from pathlib import Path

import mediapipe

TELEMETRY_MARKERS = (b"play.googleapis.com/log", b"PortableClearcutUploader")


def test_installed_mediapipe_has_no_telemetry_uploader():
    binaries = [p for p in Path(mediapipe.__file__).parent.rglob("*") if p.suffix in (".so", ".dylib")]
    assert binaries, "no mediapipe native libraries found"
    for path in binaries:
        data = path.read_bytes()
        for marker in TELEMETRY_MARKERS:
            assert marker not in data, f"{path.name} contains telemetry marker {marker!r}"
