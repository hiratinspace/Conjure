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

# Hand tracking (CONJ-4)
HAND_MODEL_PATH = ROOT / "models" / "hand_landmarker.task"
# 1, not 2: with num_hands=2 and one hand visible, MediaPipe reruns palm detection every
# frame looking for the second hand (~26 ms/frame on the M1 vs a ~20 ms budget). With 1,
# it tracks the locked hand from its previous ROI, which is also what keeps it sticky.
MAX_HANDS = 1
MIN_DETECTION_CONFIDENCE = 0.5  # MediaPipe palm detection
MIN_PRESENCE_CONFIDENCE = 0.5  # MediaPipe hand presence while tracking
MIN_TRACKING_CONFIDENCE = 0.5  # MediaPipe frame-to-frame tracking
MIN_HAND_CONFIDENCE = 0.5  # our gate: hands below this are treated as absent
MAX_WRIST_JUMP = 0.15
# Measured on the M1 (mediapipe 0.10.35, mirrored input): MediaPipe labels the user's left
# hand "Right" and vice versa, despite its docs. Swap so LandmarkFrame.handedness is the
# user's real hand. Re-check if MIRROR or the mediapipe version changes.
SWAP_HANDEDNESS = True  # normalized wrist travel per frame still counted as the same hand

# Profile store (CONJ-13): calibration, the recorded spell, and settings. Gitignored.
PROFILE_PATH = ROOT / "profile.json"

# Recordings (record/replay harness)
RECORDINGS_DIR = ROOT / "recordings"

# Cursor mapping (CONJ-5). Naive box until the user calibrates (CONJ-12): inset 15% so the
# cursor reaches every screen edge while the hand stays fully in frame (tracking drops at
# the frame edge). Normalized frame coordinates, same fields as profile.json calibration.
DEFAULT_CALIBRATION = {"x_min": 0.15, "x_max": 0.85, "y_min": 0.15, "y_max": 0.85}
SENSITIVITY = 1.0  # >1 shrinks the box: less hand travel per screen width

# Injection
PERMISSION_CHECK_INTERVAL_S = 2.0

# Smoothing + precision (CONJ-6). Tuned on recordings/idle.jsonl and traversal.jsonl:
# settled-idle jitter 4.8 px raw -> 1.3 px mean, fast-sweep lag ~14 px (about one frame).
FILTER_MIN_CUTOFF = 0.5  # Hz; lower = smoother at rest, more lag
FILTER_BETA = 0.01  # cutoff growth per px/s of speed; higher = less lag when fast
FILTER_D_CUTOFF = 1.0  # Hz, for the speed estimate
PRECISION_GAIN = 0.3  # cursor gain when the hand is nearly still (1.0 disables precision mode)
PRECISION_SPEED_PX_S = 60  # at or below this hand speed, full precision gain
FAST_SPEED_PX_S = 400  # at or above this, gain 1 and the cursor re-anchors to the hand
REANCHOR_RATE = 0.15  # fraction of the precision offset removed per fast frame
POSITION_HISTORY_FRAMES = 30  # ~1 s of cursor history for position_at (pre-pinch latch)

# Click modes (contract: pipeline/modes.py)
DEFAULT_CLICK_MODE = "pinch"  # "pinch" | "dwell" | "custom"

# Dwell (CONJ-8)
DWELL_MS = 1000  # hold still this long to click
DWELL_RADIUS_PX = 30  # "still" means the cursor stays inside this radius

# Pinch (CONJ-7). Ratios are thumb-to-fingertip distance / hand size (wrist to middle MCP).
# Tuned on recordings: with the other-fingers-open rule there are 0 sustained false pinches in
# traversal_first/traversal/idle/exits. Real-pinch values still need the deferred pinches recording.
PINCH_ENGAGE_RATIO = 0.20  # closing below this starts a pinch
PINCH_RELEASE_RATIO = 0.32  # opening above this ends it (hysteresis gap)
PINCH_HOLD_MS = 150  # a pinch must stay closed this long to count (kills Midas-touch blips)
PINCH_OPEN_EXTENSION = 1.4  # other fingers' mean extension must exceed this (curled hand != pinch).
# 1.2 let through 0.16-0.37 s fingertip contacts with half-open fingers (1.21-1.32) in the second
# traversal recording; open-finger pinches measure ~1.8-2.1.
FINGERTIP_EDGE_MARGIN = 0.03  # fingertips this close to the frame edge are untrusted
PINCH_LATCH_LOOKBACK_S = 0.5  # how far back the pre-pinch click position may be taken from
DRAG_START_PX = 25  # a confirmed pinch that moves this far becomes a drag (CONJ-9)
DOUBLE_CLICK_INTERVAL_S = 0.5  # macOS default double-click speed
DOUBLE_CLICK_RADIUS_PX = 8

# Scroll (CONJ-9): two-finger V pose as a joystick. Extensions are fingertip-to-wrist / hand size.
SCROLL_EXTENDED = 1.6  # index and middle above this ...
SCROLL_FOLDED = 1.0  # ... and ring and pinky below this = V pose (never seen by accident in recordings)
SCROLL_EXIT_EXTENDED = 1.4  # looser thresholds to stay in the pose (hysteresis)
SCROLL_EXIT_FOLDED = 1.2
SCROLL_ENTER_MS = 200  # hold the pose this long to start scrolling
SCROLL_EXIT_MS = 150  # leave the pose this long to stop
SCROLL_DEAD_ZONE = 0.15  # hand sizes of up/down travel that do nothing
SCROLL_GAIN = 40.0  # scroll steps per second per hand size beyond the dead zone (1 step = 10 px)
SCROLL_MAX_RATE = 60.0  # steps per second

# Custom gesture recorder (CONJ-10). Shape distances are mean per-landmark distance in hand sizes.
# Recorded hands vary 0.02 (at rest) to 0.21 (median, ordinary movement) within a second.
GESTURE_COUNTDOWN_S = 2.0  # "hold your hand naturally" before each sample; its second half is the rest shape
GESTURE_SAMPLE_S = 2.0  # recording window per sample
GESTURE_ACTIVE_THRESHOLD = 0.25  # frames differing from rest by more than this are the gesture
GESTURE_MARGIN_FRAMES = 3  # kept on each side of the trimmed gesture
GESTURE_THRESHOLD_SCALE = 1.5  # match threshold = this x the largest difference between the 3 samples
GESTURE_THRESHOLD_FLOOR = 0.15
GESTURE_THRESHOLD_CEILING = 0.35  # real movement came within 0.40 of a curl gesture (exits recording)
GESTURE_DISTINCT_FACTOR = 1.5  # warn if the gesture peaks less than this x threshold away from rest
# Stock spell names offered when naming a recorded gesture (CONJ-17); pre-generated audio
# exists for these (CONJ-18). Original names, no franchise terms.
STOCK_SPELL_NAMES = ["Illuminate", "Summon", "Unlock", "Levitate", "Banish", "Ignite"]

# Custom gesture matching (CONJ-11)
GESTURE_SCALES = (0.75, 1.0, 1.33)  # window lengths tried, relative to each recorded sample
GESTURE_MATCH_SCALE = 1.0  # runtime multiplier on the recorded threshold (>1 = more forgiving)
GESTURE_REARM_FACTOR = 1.5  # after a match, distance must exceed threshold x this before the next
GESTURE_REFRACTORY_S = 1.0  # minimum time between matches
GESTURE_BUFFER_FRAMES = 90  # ~3 s of live shapes kept for matching

# Range-of-motion calibration (CONJ-12)
CALIBRATION_COUNTDOWN_S = 3.0
CALIBRATION_TRACE_S = 8.0  # seconds of hand-visible tracing
CALIBRATION_LOW_PCT = 5  # box edges are these percentiles of the traced knuckle positions,
CALIBRATION_HIGH_PCT = 95  # so a twitch does not stretch the box and edges need no strain
CALIBRATION_MIN_SIZE = 0.03  # normalized frame units; smaller traces are redone

# Auto-pause (CONJ-15). AC: freeze within 500 ms of losing the hand, resume within 1 s of it returning.
PAUSE_AFTER_FRAMES = 10  # ~0.33 s at 30 fps without a usable hand
RESUME_AFTER_FRAMES = 5  # ~0.17 s with one
CONTROL_POINT_EDGE_MARGIN = 0.01  # knuckle this close to the frame edge = hand leaving
