import pytest

from main import make_engine
from pipeline.injector import RecordingInjector
from pipeline.modes import Mode, ModeState
from pipeline.recorder import read_recording
from pipeline.timing import StageTimer
from pipeline.tutorial import NaivePointer
from tests.synthetic import stream

SCREEN = (1440, 900)


def engine_in_tutorial():
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH))
    engine.set_tutorial(NaivePointer(SCREEN, 640 / 480))
    return engine, injector


@pytest.mark.parametrize("name", ["traversal_first", "traversal"])
def test_naive_tutorial_pointer_misfires_where_conjure_does_not(name):
    """The pitch's before/after, on real recordings with no click intended."""
    _, frames = read_recording(f"recordings/{name}.jsonl")
    engine, injector = engine_in_tutorial()
    results = [engine.step(t, h) for t, h in frames]
    assert engine.tutorial.clicks >= 10  # the naive detector fires on ordinary movement
    assert engine.shadow_clicks == 0  # Conjure's detector, on the same frames, does not
    assert sum(len(r.naive_clicks) for r in results) == engine.tutorial.clicks
    assert injector.actions() == []  # naive clicks are shown, never injected


def test_tutorial_cursor_follows_the_raw_fingertip():
    engine, injector = engine_in_tutorial()
    for t, h in stream([(0.5, dict(wrist=(0.5, 0.7)))]):
        r = engine.step(t, h)
    tip_x, tip_y = h.point(8)
    assert r.cursor == pytest.approx((tip_x * 1439, tip_y * 899))
    assert injector.calls[-1] == ("move", *r.cursor)


def test_naive_pinch_ignores_hand_size_so_leaning_in_clicks():
    naive = NaivePointer(SCREEN, 640 / 480)
    from tests.synthetic import make_hand
    open_far = make_hand(scale=0.03)  # small hand, far from the camera, fingers wide open
    assert naive.update(open_far)  # "pinches" without pinching
    assert not naive.update(open_far)  # fires on the crossing only


def test_turning_tutorial_off_restores_conjure():
    engine, _ = engine_in_tutorial()
    engine.set_tutorial(None)
    r = engine.step(0.0, stream([(0.1, dict())])[0][1])
    assert "tutorial" not in " ".join(r.lines)


def test_metrics_report_fps_jitter_clicks_and_blocked():
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH))
    _, frames = read_recording("recordings/traversal.jsonl")
    for t, h in frames:
        engine.step(t, h)
    m = engine.metrics(29.6)
    assert m["fps"] == "30" and m["clicks"] == "0" and int(m["misfires blocked"]) > 0
    assert m["jitter"] == "moving" or m["jitter"].endswith("px")


def test_jitter_metric_measures_a_still_hand():
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH))
    _, frames = read_recording("recordings/idle.jsonl")
    for t, h in frames[-60:]:
        engine.step(t, h)
    j = engine.jitter_px()
    assert j is not None and j < 5.0
