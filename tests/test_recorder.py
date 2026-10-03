import json

import pytest

from pipeline.recorder import LandmarkRecorder, read_recording, replay
from tests.synthetic import make_hand


def write_session(path, entries, **header):
    with LandmarkRecorder(path, **header) as rec:
        for t, hand in entries:
            rec.write(t, hand)


def test_round_trip_keeps_hands_gaps_and_header(tmp_path):
    path = tmp_path / "s.jsonl"
    hand = make_hand(timestamp=1.0, handedness="Left", confidence=0.87)
    write_session(path, [(1.0, hand), (1.033, None), (1.066, make_hand(timestamp=1.066))], name="test", mirror=True)

    header, frames = read_recording(path)
    assert header["name"] == "test" and header["mirror"] is True
    assert [t for t, _ in frames] == [1.0, 1.033, 1.066]
    assert frames[1][1] is None
    restored = frames[0][1]
    assert restored.handedness == "Left"
    assert restored.confidence == pytest.approx(0.87)
    assert restored.timestamp == 1.0
    for got, want in zip(restored.landmarks, hand.landmarks):
        assert got == pytest.approx(want, abs=1e-5)


def test_rejects_file_without_header(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps({"t": 0, "hand": None}) + "\n")
    with pytest.raises(ValueError, match="header"):
        read_recording(path)


def test_rejects_unknown_format_version(tmp_path):
    path = tmp_path / "old.jsonl"
    path.write_text(json.dumps({"type": "header", "format": 999}) + "\n")
    with pytest.raises(ValueError, match="format"):
        read_recording(path)


def test_realtime_replay_sleeps_original_intervals(tmp_path):
    path = tmp_path / "s.jsonl"
    write_session(path, [(0.0, None), (0.5, None), (0.75, None)])
    sleeps = []
    list(replay(path, realtime=True, sleep=sleeps.append))
    assert sleeps == pytest.approx([0.5, 0.25])


def test_fast_replay_never_sleeps(tmp_path):
    path = tmp_path / "s.jsonl"
    write_session(path, [(0.0, None), (5.0, None)])
    sleeps = []
    assert len(list(replay(path, sleep=sleeps.append))) == 2
    assert sleeps == []
