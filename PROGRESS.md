# Progress

Status key: `todo` · `doing` · `code done` (headless ACs pass, physical AC pending) · `done` (all ACs verified) · `blocked`

## Tickets

| Ticket | Title | Phase | Status | Notes |
| --- | --- | --- | --- | --- |
| CONJ-1 | Project scaffold & dependency install | A | code done | Verified on laptop 1. Laptop 2 setup pending (human checkpoint). |
| CONJ-2 | macOS Camera + Accessibility permissions | A | code done | `scripts/check_permissions.py` written. Laptop 1 (VS Code runner): Accessibility already granted; camera, cursor, click untested. Human run on both laptops pending. |
| CONJ-3 | Webcam capture loop + debug preview | A | todo | |
| CONJ-4 | MediaPipe hand landmark extraction | A | todo | |
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
| LandmarkFrame | `pipeline/landmarks.py` | todo |
| Mode state machine | `pipeline/modes.py` | todo |
| ClickEvent | `pipeline/events.py` | todo |
| profile.json schema | `pipeline/profile_schema.py` | todo |

## Decisions

- **mediapipe pinned to 0.10.35, not 1.0.x.** 1.0.1 aborts on macOS when HandLandmarker opens (`DrishtiMetalHelper ... Service is unavailable`), with both GPU and CPU delegates, inside and outside the sandbox. 0.10.35 runs at ~13.6 ms/frame on a blank 640x480 frame (M-series, CPU).
- **mediapipe 0.10.35 has no `mp.solutions.hands`.** HandTracker uses the Tasks API (`HandLandmarker`, VIDEO mode), which needs a model file. `models/hand_landmarker.task` is committed so runtime never touches the network and both laptops run the identical model (source: Google's `mediapipe-models` bucket, float16/latest, sha256 `fbc2a300...cde1`).
- **`opencv-contrib-python` instead of `opencv-python`.** mediapipe hard-requires the contrib build, which provides the same `cv2` module. Having both installed makes them overwrite each other.

## Granted runners (CONJ-2 AC)

| Laptop | Runner app | Accessibility | Camera | Cursor | Click |
| --- | --- | --- | --- | --- | --- |
| Laptop 1 (Hirats-MacBook-Air-4) | Visual Studio Code.app | pass | pending | pending | pending |
| Laptop 2 | pending | pending | pending | pending | pending |

Permissions belong to the runner app. Demo from the same runner listed here, or re-run the script after switching.

## Open questions

- Which runner will the demo use: VS Code's integrated terminal or Terminal.app? Both must pass CONJ-2 if both are used.
