from main import make_engine
from pipeline.events import Action, ClickEvent
from pipeline.injector import RecordingInjector
from pipeline.modes import Mode, ModeState
from pipeline.timing import StageTimer
from tests.synthetic import stream
from tests.test_pinch import pinch_stream

SCREEN = (1440, 900)


def dwell_engine():
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.DWELL))
    return engine, injector


def settle(wrist, seconds=1.6):
    """Arrive at `wrist` then hold still long enough for a dwell click."""
    return [(0.4, dict(wrist=lambda f, w=wrist: (w[0] - 0.15 + 0.15 * f, w[1]))), (seconds, dict(wrist=wrist))]


def run(engine, segments, start=0.0):
    frames = stream(segments, start=start)
    return [e for t, h in frames for e in engine.step(t, h).events], frames[-1][0]


def test_next_right_click_makes_one_right_click_then_falls_back_to_left():
    engine, injector = dwell_engine()
    engine.next_action.set("right")
    events, t = run(engine, settle((0.5, 0.7)))
    events2, _ = run(engine, settle((0.6, 0.6)), start=t + 0.1)
    assert [e.action for e in events] == [Action.RIGHT]
    assert [e.action for e in events2] == [Action.LEFT]
    assert injector.actions() == [("click", "right", 1), ("click", "left", 1)]


def test_next_double_click():
    engine, injector = dwell_engine()
    engine.next_action.set("double")
    events, _ = run(engine, settle((0.5, 0.7)))
    assert [e.action for e in events] == [Action.DOUBLE]
    assert injector.actions() == [("click", "left", 2)]


def test_drag_lock_by_dwell_starts_moves_and_drops_on_the_next_dwell():
    engine, injector = dwell_engine()
    engine.next_action.set("drag")
    events, t = run(engine, settle((0.4, 0.7)))
    assert [e.action for e in events] == [Action.DRAG_START]
    assert engine.actions.dragging and "drop" in engine.next_action.label()
    events2, _ = run(engine, settle((0.6, 0.5)), start=t + 0.1)  # carry it elsewhere, dwell again
    assert [e.action for e in events2] == [Action.DRAG_END]
    assert injector.actions() == [("press", "left"), ("release", "left")]
    assert events2[0].position[0] > events[0].position[0] + 100


def test_keep_makes_the_choice_sticky():
    engine, _ = dwell_engine()
    engine.next_action.sticky = True
    engine.next_action.set("right")
    events, t = run(engine, settle((0.5, 0.7)))
    events2, _ = run(engine, settle((0.6, 0.6)), start=t + 0.1)
    assert [e.action for e in events + events2] == [Action.RIGHT, Action.RIGHT]


def test_drag_lock_works_with_a_pinch_too():
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH))
    engine.next_action.set("drag")
    first = pinch_stream(hold_s=0.2, close_s=0.07)
    gap = stream([(0.5, dict(pinch=0.0))], start=first[-1][0] + 0.033)
    second = [(gap[-1][0] + 0.033 + t, h) for t, h in pinch_stream(hold_s=0.2, close_s=0.07, open_s=0.3)]
    events = [e for t, h in first + gap + second for e in engine.step(t, h).events]
    assert [e.action for e in events] == [Action.DRAG_START, Action.DRAG_END]


def test_natural_pinch_drag_is_untouched_by_the_remap():
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, ModeState(Mode.PINCH))
    frames = stream([(0.5, dict(pinch=0.0, wrist=(0.4, 0.7))), (0.06, dict(pinch=0.95, wrist=(0.4, 0.7))),
                     (0.3, dict(pinch=0.95, wrist=(0.4, 0.7))),
                     (0.6, dict(pinch=0.95, wrist=lambda f: (0.4 + 0.15 * f, 0.7))),
                     (0.2, dict(pinch=0.0, wrist=(0.55, 0.7)))])
    events = [e for t, h in frames for e in engine.step(t, h).events]
    assert [e.action for e in events] == [Action.DRAG_START, Action.DRAG_END]
    assert injector.actions() == [("press", "left"), ("release", "left")]


def test_pill_shows_the_pending_action():
    engine, _ = dwell_engine()
    engine.next_action.set("right")
    result = engine.step(0.0, stream([(0.1, dict())])[0][1])
    assert result.next_action == "next: right click"
