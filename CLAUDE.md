# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Conjure is an 18-hour hackathon project. It turns a webcam into a mouse replacement for people with limited hand mobility: the hand moves the cursor, and a click comes from a pinch, a dwell (holding still), or a gesture the user records. The planning docs live in `docs/` (gitignored, local only):

- `docs/scope.md`: vision, personas, stack, out-of-scope list (section 4 is a hard no), risks
- `docs/backlog.md`: tickets CONJ-1 to CONJ-20, each with dependencies and acceptance criteria
- `docs/build-plan.md`: shared contracts, build order (Phases A to F), stage gates, validation table

When they conflict, build-plan.md governs order, backlog.md governs "done" (acceptance criteria are the definition of done), and scope.md governs intent. Work ticket by ticket in build-plan order and never cross a stage gate that hasn't passed. `PROGRESS.md` tracks ticket status, decisions, and open questions; keep it current.

## Stack and constraints

- Python 3.11+, macOS only (Apple Silicon). Single process, on-device, no backend, no database, no accounts.
- MediaPipe for tracking via the Tasks API `HandLandmarker` (VIDEO mode) with the committed model `models/hand_landmarker.task`. mediapipe is pinned to 0.10.35 because 1.0.x aborts on macOS; see PROGRESS.md decisions before changing it. The legacy `mp.solutions.hands` API does not exist in this version.
- Dependencies are limited to mediapipe, opencv (the `opencv-contrib-python` build mediapipe requires), pynput, and pytest. Ask before adding anything else.
- OpenCV for capture and the debug preview, pynput for input injection (Quartz CGEvent as fallback), Tkinter or PyQt for the settings overlay, and a static local HTML "spellbook" demo page.
- Persistence is one local JSON file (`profile.json`).
- The only network call is ElevenLabs TTS (CONJ-18). Read the API key from an env var. Wrap the call in a 1 s timeout and play the audio asynchronously. On any exception, fall back to pre-generated local audio files. The core pointer must never touch the network.
- macOS Camera and Accessibility permissions are tied to the terminal or runner app. Switching runners silently revokes them: the cursor still moves but clicks never land. `scripts/check_permissions.py` (CONJ-2) is the smoke test.

## Commands

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python main.py                         # run the app
.venv/bin/python -m pytest                       # all tests (headless)
.venv/bin/python -m pytest tests/test_timing.py::test_window_resets_after_each_summary   # one test
```

Per-stage timings are logged every few seconds by `pipeline/timing.py`; wrap every new loop stage in `timer.stage(name)` so the 33 ms budget stays visible.

## Architecture

The app is one per-frame pipeline in `main.py`, with one module per stage under `pipeline/`. Defaults live in `config.py`.

```
FrameSource → HandTracker → Filter → GestureEngine → ActionMapper → Injector
```

The GestureEngine runs pinch detection, the dwell timer, and custom-gesture template matching side by side.

Four shared contracts must stay single-owner because both developer tracks consume them:

1. **`LandmarkFrame`** (CONJ-4): 21 normalized landmarks, handedness, confidence, and timestamp. It is frozen after Stage 1, and every downstream stage imports it.
2. **Mode state machine**: one enum, `PINCH | DWELL | CUSTOM | PAUSED`, in one module. CONJ-8, CONJ-11, CONJ-14 and CONJ-15 all write to it. Do not create a second copy of the mode state.
3. **`ClickEvent`**: `{action: left|right|double|drag_start|drag_end|scroll, position}`. All three click paths emit this type into one ActionMapper, so downstream code never cares which mode fired.
4. **`profile.json`**: versioned schema with the fields `version`, `calibration {x_min,x_max,y_min,y_max}`, `gestures[] {name, samples[3][21][3], threshold}`, and `settings {click_mode, dwell_ms, dwell_radius_px, filter{min_cutoff,beta,precision_gain}, sensitivity}`. Write atomically (temp file, then rename). A corrupt, missing, or old-version file loads defaults with a warning and never crashes.

## Design decisions that are easy to get wrong

- **The control point is the index MCP knuckle, not a fingertip.** A fingertip moves during a pinch.
- **The One Euro filter owns a position-history ring buffer** (about 10 frames), exposed as `filter.position_at(t)`. A pinch click fires at the *pre-pinch* position latched from this buffer.
- **Pinch** distance is thumb tip to index tip, normalized by hand size (wrist to middle MCP). It uses separate engage and release thresholds plus a ~150 ms confirmation hold, which suppresses false clicks during fast movement.
- **Dwell** requires the cursor to leave and return between clicks, so holding still never fires repeated clicks.
- **Custom gestures** are normalized for position and scale (subtract the wrist position, divide by hand size). Matching uses a sliding window, mean landmark distance or DTW, a generous configurable threshold, and a refractory period. Support one gesture only, not a library.
- **Two hands in frame:** the highest-confidence hand wins, and the choice is sticky. Switching back and forth between hands makes the cursor jump.
- **Low confidence or a lost hand must go to `PAUSED`,** with the injector inert. It must never reach a frozen-but-armed state where a noise frame can click. Treat partial or edge frames as low confidence, not as movement.
- **Calibration** maps a small comfortable box (about 3 inches, forearm rested) to the full screen, clamped at the edges. It sits behind a `Calibration` interface so it can replace the naive linear map.
- **Frame budget** is about 33 ms per frame for the whole loop: about 20 ms for tracking and about 10 ms for everything else.
- **Large targets:** settings controls must be ≥60 px, and spellbook targets ≥80 px. Both must be usable with Conjure itself in dwell mode.
- **Tunables live in config or the profile,** never hardcoded. This covers filter params, thresholds, dwell time and radius, and sensitivity.

## Validation

Everything that can run without a hand gets a pytest (filter jitter, pinch hysteresis, dwell repeat-fire, gesture normalization, profile fallback, calibration mapping), driven by synthetic landmark streams or by real sessions recorded to JSONL in `recordings/` and replayed headless. The physical gates below are run by a human at each stage gate:

- 60 s full-screen traversal: 0 false clicks or matches
- 20 pinches: at least 19 fire exactly once, at the pre-pinch position
- 30 s idle jitter: within ±3 px
- 10 casts of the custom gesture: at least 8 fire within 500 ms
- kill and relaunch: the profile restores with no re-setup

The full table is in `docs/build-plan.md` section 4.

## Scope guardrails

These are out of scope; treat them as roadmap items and do not build them:

- Windows or Linux support
- an on-screen keyboard
- multiple custom gestures or macros
- voice or eye tracking
- per-app profiles
- an installer or code signing
- macOS Accessibility API integration
- any cloud features
- multi-monitor or two-hand control

After the hour-16 freeze (CONJ-19), only config changes are allowed. Venue thresholds go in `venue.json`.

## Git workflow

The remote is `github.com:hiratinspace/Conjure` (private), on the `main` branch. After each meaningful change, commit and push it. One commit per ticket, titled `CONJ-n: <summary>`, with a body that says what changed and why. Never commit anything in `docs/`.
