import numpy as np
import pytest

import config
from pipeline.hand_tracker import HandTracker, select_hand
from tests.synthetic import make_hand

MIN_CONF = 0.5
JUMP = 0.15


def test_no_candidates_means_no_hand():
    assert select_hand([], None, MIN_CONF, JUMP) is None


def test_low_confidence_hand_is_treated_as_absent():
    assert select_hand([make_hand(confidence=0.3)], None, MIN_CONF, JUMP) is None


def test_either_hand_works_alone():
    for side in ("Left", "Right"):
        hand = make_hand(handedness=side)
        assert select_hand([hand], None, MIN_CONF, JUMP) is hand


def test_highest_confidence_wins_when_nothing_is_tracked():
    weak = make_hand(wrist=(0.3, 0.7), confidence=0.7, handedness="Left")
    strong = make_hand(wrist=(0.7, 0.7), confidence=0.9, handedness="Right")
    assert select_hand([weak, strong], None, MIN_CONF, JUMP) is strong


def test_tracked_hand_stays_selected_when_a_more_confident_hand_appears():
    tracked = make_hand(wrist=(0.3, 0.7), confidence=0.8, handedness="Left")
    still_there = make_hand(wrist=(0.31, 0.7), confidence=0.8, handedness="Left")
    newcomer = make_hand(wrist=(0.7, 0.7), confidence=0.99, handedness="Right")
    assert select_hand([newcomer, still_there], tracked, MIN_CONF, JUMP) is still_there


def test_stickiness_survives_a_handedness_label_flip():
    tracked = make_hand(wrist=(0.3, 0.7), handedness="Left")
    flipped = make_hand(wrist=(0.31, 0.7), confidence=0.8, handedness="Right")
    other = make_hand(wrist=(0.7, 0.7), confidence=0.99, handedness="Left")
    assert select_hand([other, flipped], tracked, MIN_CONF, JUMP) is flipped


def test_switches_when_tracked_hand_leaves():
    tracked = make_hand(wrist=(0.3, 0.7))
    other = make_hand(wrist=(0.8, 0.7), confidence=0.9)
    assert select_hand([other], tracked, MIN_CONF, JUMP) is other


@pytest.fixture(scope="module")
def tracker():
    with HandTracker(config.HAND_MODEL_PATH, 1, 0.5, 0.5, 0.5, MIN_CONF, JUMP) as t:
        yield t


def test_model_loads_and_blank_frame_has_no_hand(tracker):
    blank = np.zeros((config.CAMERA_HEIGHT, config.CAMERA_WIDTH, 3), np.uint8)
    assert tracker.process(blank, 1.0) is None


def test_repeated_timestamps_do_not_crash_video_mode(tracker):
    blank = np.zeros((config.CAMERA_HEIGHT, config.CAMERA_WIDTH, 3), np.uint8)
    tracker.process(blank, 2.0)
    tracker.process(blank, 2.0)  # MediaPipe VIDEO mode rejects non-increasing timestamps
