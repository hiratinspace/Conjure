# Progress

Status key: `todo` · `doing` · `code done` (headless ACs pass, physical AC pending) · `done` (all ACs verified) · `blocked`

## Tickets

| Ticket | Title | Phase | Status | Notes |
| --- | --- | --- | --- | --- |
| CONJ-1 | Project scaffold & dependency install | A | done (1 laptop) | Verified on the M1 laptop. Second-laptop AC waived: only one laptop available. |
| CONJ-2 | macOS Camera + Accessibility permissions | A | done | All checks pass from Terminal.app on the M1. Second-laptop AC waived (one laptop). |
| CONJ-3 | Webcam capture loop + debug preview | A | code done | 640x480 @ 30 requested, mirrored once at the source, FPS overlay, `p` hides preview without stopping capture. Physical AC (>=20 fps on the M1) checked at the Phase A gate. |
| CONJ-4 | MediaPipe hand landmark extraction | A | code done | Tasks API HandLandmarker, num_hands=2 then sticky single-hand selection by wrist proximity (survives label flips); confidence gate in config. JSONL record/replay harness + `scripts/record_session.py` presets. Physical AC (overlay on either hand) checked at the Phase A gate. |
| CONJ-5 | Hand-to-cursor mapping | B | todo | |
| CONJ-6 | One Euro filter + precision mode | B | todo | |
| CONJ-7 | Pinch click with hysteresis | C (Dev A) | todo | |
| CONJ-8 | Dwell click mode | C (Dev A) | todo | |
| CONJ-9 | Drag and scroll gestures | C (Dev A) | todo | |
| CONJ-10 | Custom gesture recorder | C (Dev B) | todo | |
| CONJ-11 | Custom gesture recognition engine | C (Dev B) | todo | |
| CONJ-12 | Range-of-motion calibration | C (Dev B) | todo | |
| CONJ-13 | Profile store (local JSON) | D | todo | |
| CONJ-14 | Settings panel | D | todo | |
| CONJ-15 | Auto-pause on hand exit | D | todo | |
| CONJ-16 | Spellbook demo screen | D | todo | |
| CONJ-17 | Spell theming | E | todo | |
| CONJ-18 | ElevenLabs voices + offline fallback | E | todo | |
| CONJ-19 | Feature-freeze QA + venue rehearsal | F | todo | |
| CONJ-20 | Backup video + runbook | F | todo | |

## Shared contracts (frozen before Phase C)

| Contract | Module | Status |
| --- | --- | --- |
| LandmarkFrame | `pipeline/landmarks.py` | frozen (field-list tripwire test in `tests/test_landmarks.py`) |
| Mode state machine | `pipeline/modes.py` | todo |
| ClickEvent | `pipeline/events.py` | todo |
| profile.json schema | `pipeline/profile_schema.py` | todo |

## Decisions

- **mediapipe pinned to 0.10.35, not 1.0.x.** 1.0.1 aborts on macOS when HandLandmarker opens (`DrishtiMetalHelper ... Service is unavailable`), with both GPU and CPU delegates, inside and outside the sandbox. 0.10.35 runs at ~13.6 ms/frame on a blank 640x480 frame (M1, CPU).
- **mediapipe 0.10.35 has no `mp.solutions.hands`.** HandTracker uses the Tasks API (`HandLandmarker`, VIDEO mode), which needs a model file. `models/hand_landmarker.task` is committed so runtime never touches the network and both laptops run the identical model (source: Google's `mediapipe-models` bucket, float16/latest, sha256 `fbc2a300...cde1`).
- **`opencv-contrib-python` instead of `opencv-python`.** mediapipe hard-requires the contrib build, which provides the same `cv2` module. Having both installed makes them overwrite each other.
- **One demo machine, no backup laptop.** The team has a single M1 MacBook Air, so the both-laptops ACs (CONJ-1, CONJ-2) and the build plan's laptop-parity gate are waived. The plan's backup-laptop mitigation is gone, which makes the CONJ-20 backup video (stored on a phone too) the only fallback for a machine failure.

## Granted runners (CONJ-2 AC)

| Laptop | Runner app | Accessibility | Camera | Cursor | Click |
| --- | --- | --- | --- | --- | --- |
| M1 MacBook Air (Hirats-MacBook-Air-4) | **Terminal.app** (demo runner) | pass | pass (1920x1080 default, ~22 fps) | pass | pass (double-click in TextEdit) |
| M1 MacBook Air | Visual Studio Code.app (dev only) | pass | untested | untested | untested |

Permissions belong to the runner app. Demo from the same runner listed here, or re-run the script after switching.

## Open questions

- None.

