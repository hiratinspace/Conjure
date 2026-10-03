import dataclasses

import pytest

from pipeline.landmarks import INDEX_MCP, NUM_LANDMARKS, WRIST, LandmarkFrame
from tests.synthetic import make_hand


def test_contract_fields_are_frozen():
    # Changing these breaks every consumer and every recording; this test is the tripwire.
    assert [f.name for f in dataclasses.fields(LandmarkFrame)] == ["landmarks", "handedness", "confidence", "timestamp"]


def test_frame_is_immutable():
    hand = make_hand()
    with pytest.raises(dataclasses.FrozenInstanceError):
        hand.confidence = 0.1


def test_rejects_wrong_landmark_count():
    with pytest.raises(ValueError, match="21 landmarks"):
        LandmarkFrame(landmarks=((0.0, 0.0, 0.0),) * 20, handedness="Left", confidence=1.0, timestamp=0.0)


def test_rejects_unknown_handedness():
    with pytest.raises(ValueError, match="handedness"):
        LandmarkFrame(landmarks=((0.0, 0.0, 0.0),) * NUM_LANDMARKS, handedness="left", confidence=1.0, timestamp=0.0)


def test_as_array_is_a_copy_with_expected_shape():
    hand = make_hand()
    arr = hand.as_array()
    assert arr.shape == (NUM_LANDMARKS, 3)
    arr[0, 0] = 99.0
    assert hand.landmarks[0][0] != 99.0


def test_point_returns_xy():
    hand = make_hand(wrist=(0.4, 0.6))
    assert hand.point(WRIST) == (0.4, 0.6)
    assert hand.point(INDEX_MCP) != hand.point(WRIST)
