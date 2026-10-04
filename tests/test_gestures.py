import numpy as np
import pytest

import config
from main import make_engine, make_gesture_recorder
from pipeline.gesture_recorder import COUNTDOWN, DONE, IDLE, RECORD, min_window_distance
from pipeline.gestures import auto_threshold, normalize, resample, sequence_distance
from pipeline.injector import RecordingInjector
from pipeline.modes import Mode, ModeState
from pipeline.recorder import read_recording
from pipeline.timing import StageTimer
from tests.synthetic import hand_points, make_hand, stream

ASPECT = config.CAMERA_WIDTH / config.CAMERA_HEIGHT


def blend(a, b, f):
    return [(pa[0] + (pb[0] - pa[0]) * f, pa[1] + (pb[1] - pa[1]) * f) for pa, pb in zip(a, b)]


OPEN = hand_points()
CURLED = hand_points(curled=True)


def curl_points(f):
    """Open -> curled -> open over f in 0..1: the synthetic custom gesture."""
    return blend(OPEN, CURLED, 1 - abs(2 * f - 1))


# ---- normalization (CONJ-10 AC: translation- and scale-invariant) ----


@pytest.mark.parametrize("wrist,scale", [((0.2, 0.9), 0.08), ((0.8, 0.4), 0.25), ((0.5, 0.7), 0.15)])
def test_normalized_shape_is_the_same_anywhere_and_at_any_distance(wrist, scale):
    reference = normalize(make_hand(wrist=(0.5, 0.7), scale=0.15, curled=True), ASPECT)
    moved = normalize(make_hand(wrist=wrist, scale=scale, curled=True), ASPECT)
    assert np.allclose(moved, reference, atol=1e-9)


def test_normalized_wrist_is_origin_and_hand_size_is_one():
    n = normalize(make_hand(wrist=(0.3, 0.6), scale=0.2), ASPECT)
    assert np.allclose(n[0], 0)
    assert np.hypot(n[9, 0], n[9, 1]) == pytest.approx(1.0)


def test_different_shapes_stay_different_after_normalizing():
    assert np.linalg.norm(normalize(make_hand(), ASPECT) - normalize(make_hand(curled=True), ASPECT), axis=1).mean() > 0.2


def test_resample_keeps_endpoints_and_repeats_single_frames():
    seq = np.arange(5 * 21 * 3, dtype=float).reshape(5, 21, 3)
    r = resample(seq, 9)
    assert r.shape == (9, 21, 3)
    assert np.allclose(r[0], seq[0]) and np.allclose(r[-1], seq[-1])
    assert resample(seq[:1], 4).shape == (4, 21, 3)


def test_same_gesture_at_a_different_speed_is_close():
    slow = [normalize(make_hand(points=curl_points(i / 29)), ASPECT) for i in range(30)]
    fast = [normalize(make_hand(points=curl_points(i / 14)), ASPECT) for i in range(15)]
    still = [normalize(make_hand(), ASPECT)] * 20
    assert sequence_distance(slow, fast) < 0.02
    assert sequence_distance(slow, still) > 0.1


def test_auto_threshold_is_generous_but_bounded():
    a = [np.zeros((10, 21, 3))] * 3
    assert auto_threshold(a, 1.5, 0.15, 0.6) == 0.15  # identical samples -> floor
    b = [np.zeros((10, 21, 3)), np.full((10, 21, 3), 1.0), np.zeros((10, 21, 3))]
    assert auto_threshold(b, 1.5, 0.15, 0.6) == 0.6  # wildly different -> ceiling


# ---- recorder flow ----


def recorder_frames(gestures, rest_s=config.GESTURE_COUNTDOWN_S, sample_s=config.GESTURE_SAMPLE_S, t0=0.0):
    """Synthetic session: for each entry, a still open hand for the countdown, then the gesture
    (a points function over 0..1, or None for 'just keep the hand still') inside the sample window."""
    segments = []
    for g in gestures:
        segments.append((rest_s + 0.05, dict(points=OPEN)))
        if g is None:
            segments.append((sample_s, dict(points=OPEN)))
        else:
            segments += [(0.4, dict(points=OPEN)), (0.8, dict(points=g)), (sample_s - 1.2 + 0.05, dict(points=OPEN))]
    return stream(segments, start=t0)


def run_recorder(frames, recorder=None):
    rec = recorder or make_gesture_recorder()
    rec.start()
    for t, hand in frames:
        rec.update(hand, t)
    return rec


def test_three_samples_make_a_template_with_trimmed_samples():
    rec = run_recorder(recorder_frames([curl_points] * 3))
    assert rec.state == DONE
    samples, threshold, warnings = rec.result()
    assert len(samples) == 3
    assert all(10 <= len(s) <= 40 for s in samples)  # trimmed to the ~0.8 s motion, not the 2 s window
    assert config.GESTURE_THRESHOLD_FLOOR <= threshold <= config.GESTURE_THRESHOLD_CEILING
    assert warnings == []


def test_a_sample_with_no_distinct_motion_is_rejected_and_redone():
    rec = run_recorder(recorder_frames([curl_points, None]))
    assert len(rec.samples) == 1
    assert rec.state in (COUNTDOWN, RECORD)
    assert "resting hand" in rec.message


def test_losing_the_hand_mid_sample_repeats_it():
    frames = recorder_frames([curl_points])
    frames = frames[:-10] + [(frames[-10][0] + i / 30, None) for i in range(5)]
    rec = run_recorder(frames)
    assert rec.samples == [] and rec.state == COUNTDOWN
    assert "Lost your hand" in rec.message


def test_prompts_guide_the_user():
    rec = make_gesture_recorder()
    rec.start()
    rec.update(make_hand(), 0.0)
    assert "sample 1 of 3" in rec.prompt and "naturally" in rec.prompt
    rec.update(make_hand(), config.GESTURE_COUNTDOWN_S + 0.1)
    assert rec.state == RECORD and "cast" in rec.prompt


def test_cancel_returns_to_idle():
    rec = make_gesture_recorder()
    rec.start()
    rec.cancel()
    assert rec.state == IDLE and not rec.active


def test_warns_when_ordinary_movement_already_looks_like_the_gesture():
    rec = run_recorder(recorder_frames([curl_points] * 3))
    gesture_like = [normalize(make_hand(points=curl_points(i / 23)), ASPECT) for i in range(24)]
    unlike = [normalize(make_hand(), ASPECT)] * 60
    assert rec.result(ordinary=unlike)[2] == []
    assert any("normal hand movement" in w for w in rec.result(ordinary=unlike + gesture_like)[2])


def test_min_window_distance_finds_the_matching_stretch():
    target = np.random.default_rng(0).normal(size=(8, 21, 3))
    frames = np.concatenate([np.zeros((20, 21, 3)), target, np.zeros((20, 21, 3))])
    assert min_window_distance([target], frames, step=1) == pytest.approx(0.0)


def test_engine_records_without_moving_or_clicking_and_keeps_ordinary_history():
    injector = RecordingInjector()
    engine = make_engine(injector, StageTimer(33.0, 1e9), (1440, 900), ModeState(Mode.DWELL))
    _, ordinary = read_recording("recordings/idle.jsonl")
    for t, hand in ordinary[:200]:
        engine.step(t, hand)
    assert len(engine.ordinary) > 0
    engine.submit(lambda e: e.recorder.start())
    engine.step(199.9, ordinary[200][1])  # runs the submitted start command
    results, injected_while_recording = [], 0
    for t, h in recorder_frames([curl_points] * 3):
        was_recording, before = engine.recorder.active, len(injector.calls)
        engine.step(200 + t, h)
        results.append(engine.recorder.prompt)
        if was_recording:
            injected_while_recording += len(injector.calls) - before
    assert engine.recorder.state == DONE
    assert injected_while_recording == 0
    assert any("cast your gesture" in p for p in results)


def test_finishing_a_recording_names_and_stores_one_spell():
    engine = make_engine(RecordingInjector(), StageTimer(33.0, 1e9), (1440, 900), ModeState(Mode.CUSTOM))
    engine.recorder.start()
    for t, h in recorder_frames([curl_points] * 3):
        engine.recorder.update(h, t)
    template, warnings = engine.finish_recording("Illuminate")
    assert [g.name for g in engine.gestures] == ["Illuminate"]
    assert len(template.samples) == 3 and template.threshold > 0
    assert engine.recorder.state == IDLE
    assert "Illuminate" in engine.notice
