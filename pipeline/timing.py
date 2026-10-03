"""Per-stage timing against the frame budget.

Every stage of the loop runs inside `timer.stage(name)`. Stages that only wait
(camera read blocks until the next frame arrives) pass `budgeted=False`, so the
budget check measures our work, not the camera's frame interval.
"""

import logging
import time
from collections import defaultdict
from contextlib import contextmanager

log = logging.getLogger("conjure.timing")


class StageTimer:
    def __init__(self, budget_ms, log_interval_s, clock=time.perf_counter):
        self.budget_ms = budget_ms
        self.log_interval_s = log_interval_s
        self._clock = clock
        self._totals = defaultdict(float)
        self._budgeted = set()
        self._work_this_frame = 0.0
        self._work_total = 0.0
        self._work_max = 0.0
        self._frames = 0
        self._window_start = clock()
        self.last_summary = {}

    @contextmanager
    def stage(self, name, budgeted=True):
        start = self._clock()
        try:
            yield
        finally:
            ms = (self._clock() - start) * 1000.0
            self._totals[name] += ms
            if budgeted:
                self._budgeted.add(name)
                self._work_this_frame += ms

    def end_frame(self):
        """Close the current frame; log and return a summary once per interval."""
        self._frames += 1
        self._work_total += self._work_this_frame
        self._work_max = max(self._work_max, self._work_this_frame)
        self._work_this_frame = 0.0

        now = self._clock()
        elapsed = now - self._window_start
        if elapsed < self.log_interval_s:
            return None

        n = self._frames
        summary = {name: total / n for name, total in self._totals.items()}
        summary["work"] = self._work_total / n
        summary["work_max"] = self._work_max
        summary["fps"] = n / elapsed if elapsed > 0 else 0.0
        self.last_summary = summary

        stages = " ".join(f"{k}={v:.1f}ms" for k, v in summary.items() if k in self._totals)
        line = f"{stages} | work avg={summary['work']:.1f}ms max={summary['work_max']:.1f}ms | {summary['fps']:.1f} fps"
        if summary["work"] > self.budget_ms:
            log.warning("OVER BUDGET (%.0f ms): %s", self.budget_ms, line)
        else:
            log.info(line)

        self._totals.clear()
        self._work_total = 0.0
        self._work_max = 0.0
        self._frames = 0
        self._window_start = now
        return summary
