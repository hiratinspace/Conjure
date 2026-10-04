# Progress

Status key: `todo` · `doing` · `code done` (headless ACs pass, physical AC pending) · `done` (all ACs verified) · `blocked`

## Tickets

| Ticket | Title | Phase | Status | Notes |
| --- | --- | --- | --- | --- |
| CONJ-1 | Project scaffold & dependency install | A | done (1 laptop) | Verified on the M1 laptop. Second-laptop AC waived: only one laptop available. |
| CONJ-2 | macOS Camera + Accessibility permissions | A | done | All checks pass from Terminal.app on the M1. Second-laptop AC waived (one laptop). |
| CONJ-3 | Webcam capture loop + debug preview | A | done | Phase A gate: 30 fps with preview on (work ~28 ms: track ~15, preview ~13), 30 fps with preview hidden via `p` while capture continues. |
| CONJ-4 | MediaPipe hand landmark extraction | A | code done | Tasks API HandLandmarker, num_hands=1 (MediaPipe's ROI tracking keeps the locked hand sticky and skips palm detection), plus a sticky `select_hand` gate; confidence gate in config. JSONL record/replay harness + `scripts/record_session.py` presets. Phase A gate: overlay renders on either hand (pass); labels were swapped, fixed with SWAP_HANDEDNESS. Two-hand stickiness check and recordings pending. |
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

- **mediapipe pinned to 0.10.33.** 1.0.1 aborts on macOS when HandLandmarker opens (`DrishtiMetalHelper ... Service is unavailable`), with both GPU and CPU delegates, inside and outside the sandbox. 0.10.35 runs, but ships a Google telemetry uploader (Clearcut, `play.googleapis.com/log`) that tried to send data during the first recordings, breaking the no-network rule; there is no opt-out switch. 0.10.32 and 0.10.33 contain no uploader. 0.10.33 runs at ~13.7 ms/frame on a blank frame (M1, CPU). `tests/test_no_network.py` fails if an upgrade brings the uploader back.
- **mediapipe 0.10.3x has no `mp.solutions.hands`.** HandTracker uses the Tasks API (`HandLandmarker`, VIDEO mode), which needs a model file. `models/hand_landmarker.task` is committed so runtime never touches the network and both laptops run the identical model (source: Google's `mediapipe-models` bucket, float16/latest, sha256 `fbc2a300...cde1`).
- **`opencv-contrib-python` instead of `opencv-python`.** mediapipe hard-requires the contrib build, which provides the same `cv2` module. Having both installed makes them overwrite each other.
- **One demo machine, no backup laptop.** The team has a single M1 MacBook Air, so the both-laptops ACs (CONJ-1, CONJ-2) and the build plan's laptop-parity gate are waived. The plan's backup-laptop mitigation is gone, which makes the CONJ-20 backup video (stored on a phone too) the only fallback for a machine failure.

- **Tracker runs with num_hands=1.** First live run (Phase A gate) with num_hands=2: tracking 25-29 ms/frame with a hand visible, over the ~20 ms budget, because MediaPipe reruns palm detection every frame while looking for a second hand. num_hands=1 tracks the locked hand by ROI instead. The preview window itself costs 13-18 ms/frame on macOS (imshow + waitKey); with it hidden the loop held 30 fps.

- **MediaPipe handedness labels are swapped on our mirrored input.** The Phase A gate showed the left hand labeled "Right" and vice versa, contrary to MediaPipe's docs. `SWAP_HANDEDNESS = True` corrects it at the tracker, so LandmarkFrame and recordings carry the user's real hand.

- **Recordings: hand labels flicker; rested wrist sits at the frame bottom.** In `traversal` the label flipped to "Left" in 12 of 1695 hand frames, so nothing downstream may depend on per-frame handedness. In `idle` (forearm rested) the wrist reaches y=1.02, slightly past the bottom edge; calibration and the control point must not depend on the wrist being in frame.

## Granted runners (CONJ-2 AC)

| Laptop | Runner app | Accessibility | Camera | Cursor | Click |
| --- | --- | --- | --- | --- | --- |
| M1 MacBook Air (Hirats-MacBook-Air-4) | **Terminal.app** (demo runner) | pass | pass (1920x1080 default, ~22 fps) | pass | pass (double-click in TextEdit) |
| M1 MacBook Air | Visual Studio Code.app (dev only) | pass | untested | untested | untested |

Permissions belong to the runner app. Demo from the same runner listed here, or re-run the script after switching.

## Open questions

- None.

