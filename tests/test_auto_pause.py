from main import make_engine
from pipeline.injector import RecordingInjector
from pipeline.modes import HAND_LOST, USER, Mode, ModeState
from pipeline.recorder import read_recording
from pipeline.timing import StageTimer
from tests.synthetic import stream

SCREEN = (1440, 900)


def run(frames, mode=Mode.DWELL):
    injector = RecordingInjector()
    modes = ModeState(mode)
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, modes)
    states = []
    for t, h in frames:
        before = len(injector.calls)
        usable = engine.auto_pause.usable(h)
        engine.step(t, h)
        states.append((t, usable, modes.mode, len(injector.calls) - before, injector.enabled))
    return states, injector, engine


def transitions(states):
    out = []
    for prev, cur in zip(states, states[1:]):
        if (prev[2] == Mode.PAUSED) != (cur[2] == Mode.PAUSED):
            out.append((cur[0], cur[2] == Mode.PAUSED))
    return out


def test_hand_leaving_pauses_within_500ms_and_returning_resumes_within_1s():
    frames = stream([(1.0, dict(wrist=(0.5, 0.7))), (1.0, None), (1.0, dict(wrist=(0.5, 0.7)))])
    states, _, _ = run(frames)
    (t_pause, paused), (t_resume, resumed) = transitions(states)
    assert paused and not resumed
    assert t_pause - 1.0 <= 0.5
    assert t_resume - 2.0 <= 1.0


def test_nothing_is_injected_while_paused_and_the_injector_is_off():
    frames = stream([(1.0, dict(wrist=(0.5, 0.7))), (1.0, None), (0.1, dict(wrist=(0.5, 0.7)))])
    states, _, _ = run(frames)
    paused = [s for s in states if s[2] == Mode.PAUSED]
    assert paused and all(s[3] == 0 for s in paused)
    assert all(not s[4] for s in paused)


def test_knuckle_at_the_frame_edge_counts_as_leaving_but_a_low_wrist_does_not():
    # Hand sliding off the right edge: knuckle reaches x >= 0.99.
    off_edge = stream([(0.5, dict(wrist=(0.5, 0.7))), (1.0, dict(wrist=(1.1, 0.7)))])
    assert any(s[2] == Mode.PAUSED for s in run(off_edge)[0])
    # Wrist below the frame (y > 1) with the knuckle still well inside: normal rested pose.
    low_wrist = stream([(2.0, dict(wrist=(0.5, 1.05), scale=0.2))])
    assert not any(s[2] == Mode.PAUSED for s in run(low_wrist)[0])


def test_a_brief_tracking_dropout_does_not_pause():
    frames = stream([(1.0, dict(wrist=(0.5, 0.7))), (0.1, None), (1.0, dict(wrist=(0.5, 0.7)))])
    states, _, _ = run(frames)
    assert transitions(states) == []


def test_auto_resume_never_overrides_a_user_pause():
    injector = RecordingInjector()
    modes = ModeState(Mode.PINCH)
    engine = make_engine(injector, StageTimer(33.0, 1e9), SCREEN, modes)
    modes.pause(USER)
    for t, h in stream([(0.5, None), (1.0, dict(wrist=(0.5, 0.7)))]):
        engine.step(t, h)
    assert modes.paused and USER in modes.pause_reasons and HAND_LOST not in modes.pause_reasons


def test_exits_recording_ten_cycles_freeze_fast_resume_fast_no_clicks():
    """Build-plan validation row: hand exit/re-entry x10 -> freeze <= 500 ms, resume <= 1 s, no clicks."""
    _, frames = read_recording("recordings/exits.jsonl")
    states, injector, _ = run(frames, mode=Mode.PINCH)
    first_hand = next(s[0] for s in states if s[1])
    trans = [(t, p) for t, p in transitions(states) if t > first_hand]  # the session starts handless
    pauses = [t for t, p in trans if p]
    resumes = [t for t, p in trans if not p]
    assert len(pauses) >= 10 and len(resumes) >= 10
    times = [s[0] for s in states]
    for t_pause in pauses:  # each pause follows the hand's disappearance by <= 0.5 s
        i = times.index(t_pause)
        j = i
        while j > 0 and not states[j - 1][1]:
            j -= 1
        assert t_pause - times[j] <= 0.5
    for t_resume in resumes:  # each resume follows the hand's return by <= 1 s
        i = times.index(t_resume)
        j = i
        while j > 0 and states[j - 1][1]:
            j -= 1
        assert t_resume - times[j] <= 1.0
    assert injector.actions() == []
