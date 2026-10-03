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

# Camera (CONJ-3). 640x480 keeps tracking fast; the M1 camera defaults to 1080p.
CAMERA_INDEX = 0
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
MIRROR = True  # selfie view: moving the hand right moves the cursor right
CAMERA_WARMUP_FRAMES = 5
FPS_SMOOTHING = 0.1  # EMA weight of the newest frame interval
