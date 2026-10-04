# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

Conjure is an 18-hour hackathon project. It turns a webcam into a mouse replacement for people with limited hand mobility: the hand moves the cursor, and a click comes from a pinch, a dwell (holding still), or a gesture the user records. The planning docs live in `docs/` (gitignored, local only):

- `docs/scope.md`: vision, personas, stack, out-of-scope list (section 4 is a hard no), risks
- `docs/backlog.md`: tickets CONJ-1 to CONJ-20, each with dependencies and acceptance criteria
- `docs/build-plan.md`: shared contracts, build order (Phases A to F), stage gates, validation table

When they conflict, build-plan.md governs order, backlog.md governs "done" (acceptance criteria are the definition of done), and scope.md governs intent. `PROGRESS.md` tracks ticket status, stage gates, decisions (with the measurements behind them), and open questions; keep it current and read its decisions before changing any threshold. `RUNBOOK.md` is the demo-day procedure.

## Stack and constraints

- Python 3.11+ (developed on 3.12), macOS only, one M1 laptop. Single process, on-device, no backend, no accounts.
- Dependencies are exactly those in `requirements.txt` (mediapipe, opencv-contrib-python, numpy, pynput, pytest). Ask before adding anything. pyobjc (`Quartz`, `AppKit`) arrives with pynput and is used directly; Tk is stdlib; audio uses macOS `afplay` and `say`.
- **mediapipe is pinned to 0.10.33.** 1.0.x aborts on macOS, and 0.10.35 ships a Google telemetry uploader that makes network calls (`tests/test_no_network.py` scans for it). It only has the Tasks API (`HandLandmarker`, VIDEO mode) with the committed model `models/hand_landmarker.task`; `mp.solutions.hands` does not exist.
- **The only network code is `pipeline/voice_elevenlabs.py`** (a test fails if any other module imports networking code). The key comes only from `ELEVENLABS_API_KEY`; never ask for it in chat or write it to a file.
- macOS permissions belong to the runner app. Terminal.app is the verified demo runner. Without Accessibility the cursor may move while clicks silently vanish; `scripts/check_permissions.py` checks it.

## Commands

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python main.py --spellbook                 # the app: overlay + settings panel (+ demo page in the browser)
.venv/bin/python main.py --preview                   # plus the debug preview (keys: p m g c s q)
.venv/bin/python main.py --replay recordings/idle.jsonl --preview      # drive the app from a recording (dry run)
.venv/bin/python main.py --replay recordings/idle.jsonl --quit-after 6 # UI smoke test
.venv/bin/python main.py --no-ui --preview           # fallback: single thread, OpenCV preview, no overlay
.venv/bin/python -m pytest -q                        # all tests, headless (~7 s)
.venv/bin/python -m pytest tests/test_pinch.py -k traversal   # a subset
.venv/bin/python scripts/record_session.py --list    # record named landmark sessions for replay tests
.venv/bin/python scripts/check_permissions.py        # camera / Accessibility / click smoke test
.venv/bin/python scripts/diagnose_tracking.py        # what the camera and tracker see, saved to logs/
.venv/bin/python scripts/pregenerate_voices.py       # render voice clips (needs ELEVENLABS_API_KEY)
```

## Architecture

**Threads.** macOS needs every window on the main thread, so Tk owns it (`pipeline/app.py`: overlay, settings panel, preview, naming window), and camera + tracking + engine run on a worker thread. They share only `UiState` (`pipeline/ui_state.py`: a per-frame snapshot plus an event queue) and the thread-safe `ModeState`. The UI never mutates engine state directly: it calls `engine.submit(fn)`, which runs `fn(engine)` on the pipeline thread at the next frame. `--no-ui` runs everything on one thread with the OpenCV preview.

**Per frame.** `main.run_pipeline` yields `(t, image, LandmarkFrame | None)` from the camera (`frame_source` + `hand_tracker`) or a JSONL replay (`recorder`), and calls `Engine.step(t, hand)` (`pipeline/engine.py`). The engine runs submitted commands; hands frames to the calibrator or gesture recorder if one is active (no cursor or clicks then); applies auto-pause; checks scroll (which freezes the cursor); maps and filters the cursor (`cursor_mapper`, `filter`); then runs the active click mode's detector (`touch`, `pinch`, `dwell`, or `gesture_matcher`). Detectors return `ClickEvent`s, which go to the single `ActionMapper` and then the injector. `StepResult` carries overlay text, prompts, dwell progress, and the cast spell name. Every factory lives in `main.py` (`make_engine`, `make_pinch`, ...), and tests build engines through them, so tests run the live wiring.

**Frozen contracts** (implemented once; import them, never fork them; each has a field-list tripwire test):

1. `LandmarkFrame` (`pipeline/landmarks.py`): 21 normalized `(x, y, z)` in mirrored frame coords, handedness (corrected by `SWAP_HANDEDNESS`), confidence, monotonic timestamp. Changing it invalidates every recording.
2. `Mode` / `ModeState` (`pipeline/modes.py`): `TOUCH | PINCH | DWELL | CUSTOM | PAUSED` (TOUCH added after the build plan). Pauses are tracked by reason (`HAND_LOST`, `USER`), so auto-resume never cancels a user pause.
3. `ClickEvent` (`pipeline/events.py`): `{action, position, amount}`; `amount` (scroll steps) is an addition to the build plan.
4. `profile.json` schema (`pipeline/profile_schema.py`), version 1, all-or-nothing validation. Deviation: gesture samples are sequences `[3][T][21][3]`, not poses (open question in PROGRESS.md). `pipeline/profile_store.py` saves atomically and turns any bad file into defaults plus an on-screen warning.

**Config layering.** `config.py` holds every tunable. At startup `venue.json` overrides it by name (`pipeline/venue.py`; typos are logged and skipped; `STAGE_CLICK_MODE` forces the launch mode). Then `profile.json` sets the user-facing values (click mode, dwell, filter, sensitivity, calibration, spell). Settings panel changes go through `pipeline/settings_model.py` and are saved immediately.

## Decisions that are easy to undo by accident

Each was forced by real recordings; PROGRESS.md has the numbers.

- **The control point is the index MCP knuckle**, not a fingertip.
- **Pinch is the default; Touch mode is an option.** Touch detects a tap as a quick index-finger bend (straightness, no depth). It counts only after pointing, with the hand nearly still (< 250 px/s), and a drag needs the press held 200 ms first: without these, ordinary movement in the recordings made false clicks and drags. `Mode.TOUCH` was added to the frozen contract deliberately.
- **A pinch counts only with the other fingers open (mean extension > 1.4) and the hand under 400 px/s**; with both, the hold can be a short 80 ms so natural quick pinches click. Dropping the open-fingers rule gives 5-30 false clicks on the recordings. A blocked pinch turns the cursor dot red and says why. The user's natural pointing pose is a curled hand, which puts the thumb on the index finger. So a fist cannot be the scroll gesture: scroll is the two-finger V pose, used like a joystick.
- **Edge trust is per fingertip**: only the pinching fingertip joints must be inside the frame. The wrist is usually below the frame.
- **A pinch click lands where the fingers started closing**, found by walking back through the ratio history and read from `filter.position_at(t)`. Drag distance is measured from the confirmation point, and a drag starts only while the pinch is firmly closed.
- **Precision gain below 1 drifts the cursor away from the hand**: it is re-anchored when the hand moves fast, and snapped to a screen edge when the raw target is pinned there.
- **Custom gestures compare hand shape only** (wrist subtracted, size normalized), so cursor travel is never a gesture. The threshold ceiling (0.35) sits below the closest real ordinary movement measured (0.40).
- **Dwell, gestures, and auto-pause all need movement or a clean re-entry before acting again**, so stillness or a returning hand never clicks by itself.
- **Large targets**: panel controls at least 60 px (Aqua buttons ignore height, so `BigButton` is a styled Label); spellbook targets at least 96 px, and every step is completable with plain clicks.
- **Frame budget**: 33 ms total; tracking ~15 ms with one hand (`MAX_HANDS = 1`; two hands cost ~26 ms). Wrap new loop stages in `timer.stage(name)`.

## Validation

Physical acceptance criteria are checked by a human at stage gates (PROGRESS.md lists what is still deferred). Everything else is a pytest, mostly driven by real sessions in `recordings/` (`traversal_first`, `traversal`, `idle`, `exits`) and synthetic hands from `tests/synthetic.py` (`make_hand`, `stream`). The build plan's validation rows exist as headless tests: zero false clicks, scrolls, and spell matches on every recording; idle jitter; a calibrated small box reaching every edge; kill-and-relaunch; exit and re-entry timing. New thresholds must keep all of them passing. Add new recordings with `scripts/record_session.py` and keep old ones as fixtures rather than overwriting them.

## Scope guardrails

Out of scope, so do not build: Windows or Linux support, an on-screen keyboard, multiple custom gestures or macros, voice or eye tracking, per-app profiles, an installer or code signing, macOS Accessibility API integration, any cloud features, multi-monitor or two-hand control. After the hour-16 freeze (CONJ-19) only `venue.json` changes.

## Git workflow

The remote is `github.com:hiratinspace/Conjure`, **public on purpose** (it is the hackathon submission), on the `main` branch. Never commit secrets, keys, or `profile.json`. Commit and push after each meaningful change, titled `CONJ-n: <summary>` when it belongs to a ticket, with a body that says what changed and why. Never commit anything in `docs/`. Recordings in `recordings/` and voice clips in `audio/voice/` are committed; `profile.json`, `logs/`, and `audio/cache/` are not.
