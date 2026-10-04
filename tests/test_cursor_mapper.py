import pytest

from pipeline.cursor_mapper import Box, BoxCalibration, CursorMapper
from pipeline.injector import RecordingInjector
from pipeline.landmarks import INDEX_MCP, INDEX_TIP, THUMB_TIP
from pipeline.recorder import read_recording
from pipeline.timing import StageTimer
from tests.synthetic import make_hand

SCREEN = (1440, 900)
BOX = Box(0.2, 0.8, 0.2, 0.8)


def test_box_corners_map_to_screen_corners():
    cal = BoxCalibration(BOX, SCREEN)
    assert cal.to_screen(0.2, 0.2) == pytest.approx((0, 0), abs=1e-6)
    assert cal.to_screen(0.8, 0.8) == pytest.approx((1439, 899))
    assert cal.to_screen(0.5, 0.5) == pytest.approx((719.5, 449.5))


def test_positions_outside_the_box_clamp_to_the_edge():
    cal = BoxCalibration(BOX, SCREEN)
    assert cal.to_screen(-0.5, 1.5) == (0, 899)
    assert cal.to_screen(0.95, 0.05) == (1439, 0)


def test_higher_sensitivity_needs_less_hand_travel():
    slow = BoxCalibration(BOX, SCREEN, sensitivity=1.0)
    fast = BoxCalibration(BOX, SCREEN, sensitivity=2.0)
    # 0.15 to the right of center reaches the edge only at double sensitivity.
    assert slow.to_screen(0.65, 0.5)[0] < 1400
    assert fast.to_screen(0.65, 0.5)[0] == pytest.approx(1439)


def test_box_rejects_inverted_ranges():
    with pytest.raises(ValueError):
        Box(0.8, 0.2, 0.2, 0.8)


def test_mapper_follows_index_mcp_not_fingertips():
    mapper = CursorMapper(BoxCalibration(BOX, SCREEN))
    hand = make_hand(wrist=(0.5, 0.75))
    # Pinch: move thumb tip and index tip together; the knuckle does not move.
    pts = list(hand.landmarks)
    mid = tuple((a + b) / 2 for a, b in zip(pts[THUMB_TIP], pts[INDEX_TIP]))
    pts[THUMB_TIP] = pts[INDEX_TIP] = mid
    pinched = type(hand)(tuple(pts), hand.handedness, hand.confidence, hand.timestamp)
    assert mapper.target(pinched) == mapper.target(hand)
    assert mapper.target(hand) == BoxCalibration(BOX, SCREEN).to_screen(*hand.point(INDEX_MCP))


def run_engine(frames):
    from main import make_engine

    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN)
    results = [engine.step(t, hand) for t, hand in frames]
    return injector, results


def test_engine_moves_cursor_only_when_a_hand_is_tracked():
    injector, results = run_engine([(0.0, make_hand()), (0.033, None), (0.066, make_hand(wrist=(0.6, 0.7)))])
    assert [c[0] for c in injector.calls] == ["move", "move"]
    assert results[1].cursor is None


def test_traversal_recording_reaches_every_screen_edge():
    # traversal_first covers the whole frame; the second session never moves the knuckle
    # left of x=0.35, so it cannot reach the left screen edge under any mapping.
    _, frames = read_recording("recordings/traversal_first.jsonl")
    injector, _ = run_engine(frames)
    moves = [c for c in injector.calls if c[0] == "move"]
    xs = [c[1] for c in moves]
    ys = [c[2] for c in moves]
    assert min(xs) == 0 and max(xs) == SCREEN[0] - 1
    assert min(ys) == 0 and max(ys) == SCREEN[1] - 1
