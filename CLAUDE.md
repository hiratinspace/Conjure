# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Conjure is an 18-hour hackathon project. It turns a webcam into a mouse replacement for people with limited hand mobility: the hand moves the cursor, and a click comes from a pinch, a dwell (holding still), or a gesture the user records. **No code exists yet.** The repo holds three planning docs in `docs/` (gitignored, local only), and they are the source of truth:

- `docs/Conjure — Project Discovery & Scope Document.md`: vision, personas, stack, out-of-scope list, risks
- `docs/Engineering backlog.md`: tickets CONJ-1 to CONJ-20, each with dependencies and acceptance criteria
- `docs/Build plan.md`: shared contracts, build order, implied blockers, validation gates

Refer to work by ticket ID (CONJ-n). When an acceptance criterion and an implementation idea conflict, the acceptance criterion wins.

## Stack and constraints

- Python 3.11+, macOS only (Apple Silicon). Single process, on-device, no backend, no database, no accounts.
- MediaPipe Hands for tracking, OpenCV for capture and the debug preview, pynput for input injection (Quartz CGEvent as fallback), Tkinter or PyQt for the settings overlay, and a static local HTML "spellbook" demo page.
- Persistence is one local JSON file (`profile.json`).
- The only network call is ElevenLabs TTS (CONJ-18). Read the API key from an env var. Wrap the call in a 1 s timeout and play the audio asynchronously. On any exception, fall back to pre-generated local audio files. The core pointer must never touch the network.
- macOS Camera and Accessibility permissions are tied to the terminal or runner app. Switching runners silently revokes them: the cursor still moves but clicks never land. `scripts/check_permissions.py` (CONJ-2) is the smoke test.

## Planned commands

These are planned for CONJ-1. Update this section once they exist.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt     # pinned: mediapipe, opencv-python, pynput
python main.py                      # run the app
python main.py --preview            # with the OpenCV debug preview (landmarks, FPS, pinch/dwell state)
python scripts/check_permissions.py # camera + cursor move + click into TextEdit
```

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

There is no unit-test suite in the plan. Each acceptance criterion is checked by a manual gate, and the cheap gates are rerun at the end of every stage:

- 60 s full-screen traversal: 0 false clicks or matches
- 20 pinches: at least 19 fire exactly once, at the pre-pinch position
- 30 s idle jitter: within ±3 px
- 10 casts of the custom gesture: at least 8 fire within 500 ms
- kill and relaunch: the profile restores with no re-setup

The full table is in `docs/Build plan.md` §4.

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
