"""Default tunables for every pipeline stage.

These are fallbacks. At runtime the profile store (CONJ-13) overrides the
user-facing ones, and venue.json (CONJ-19) overrides thresholds on demo day.
Nothing downstream should hardcode a number that belongs here.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Frame budget (build-plan section 2): ~20 ms tracking, ~10 ms everything else.
FRAME_BUDGET_MS = 33.0
TIMING_LOG_INTERVAL_S = 5.0
