import pytest

from pipeline.timing import StageTimer


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance_ms(self, ms):
        self.t += ms / 1000.0


def run_frame(timer, clock, capture_ms, track_ms):
    with timer.stage("capture", budgeted=False):
        clock.advance_ms(capture_ms)
    with timer.stage("track"):
        clock.advance_ms(track_ms)
    return timer.end_frame()


def test_summary_averages_per_stage_and_excludes_waits_from_work():
    clock = FakeClock()
    timer = StageTimer(budget_ms=33.0, log_interval_s=1.0, clock=clock)
    summary = None
    while summary is None:
        summary = run_frame(timer, clock, capture_ms=20.0, track_ms=13.0)
    assert summary["capture"] == pytest.approx(20.0)
    assert summary["track"] == pytest.approx(13.0)
    assert summary["work"] == pytest.approx(13.0)
    assert round(summary["fps"]) == 30


def test_over_budget_is_logged_as_warning(caplog):
    clock = FakeClock()
    timer = StageTimer(budget_ms=33.0, log_interval_s=0.1, clock=clock)
    while run_frame(timer, clock, capture_ms=0.0, track_ms=40.0) is None:
        pass
    assert any("OVER BUDGET" in r.message for r in caplog.records)


def test_window_resets_after_each_summary():
    clock = FakeClock()
    timer = StageTimer(budget_ms=33.0, log_interval_s=0.1, clock=clock)
    while run_frame(timer, clock, capture_ms=0.0, track_ms=40.0) is None:
        pass
    summary = None
    while summary is None:
        summary = run_frame(timer, clock, capture_ms=0.0, track_ms=10.0)
    assert summary["work"] == pytest.approx(10.0)
    assert summary["work_max"] == pytest.approx(10.0)
