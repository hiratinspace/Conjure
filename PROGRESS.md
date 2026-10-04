# Progress

Status key: `todo` · `doing` · `code done` (headless ACs pass, physical AC pending) · `done` (all ACs verified) · `blocked`

## Tickets

| Ticket | Title | Phase | Status | Notes |
| --- | --- | --- | --- | --- |
| CONJ-1 | Project scaffold & dependency install | A | done (1 laptop) | Verified on the M1 laptop. Second-laptop AC waived: only one laptop available. |
| CONJ-2 | macOS Camera + Accessibility permissions | A | done | All checks pass from Terminal.app on the M1. Second-laptop AC waived (one laptop). |
| CONJ-3 | Webcam capture loop + debug preview | A | done | Phase A gate: 30 fps with preview on (work ~28 ms: track ~15, preview ~13), 30 fps with preview hidden via `p` while capture continues. |
| CONJ-4 | MediaPipe hand landmark extraction | A | done | Tasks API HandLandmarker, num_hands=1 (MediaPipe's ROI tracking keeps the locked hand sticky and skips palm detection), plus a sticky `select_hand` gate; confidence gate in config. JSONL record/replay harness + `scripts/record_session.py` presets. Phase A gate: overlay renders on either hand (pass); labels were swapped, fixed with SWAP_HANDEDNESS. Two-hand stickiness passes live. |
| CONJ-5 | Hand-to-cursor mapping | B | code done | Index MCP control point through a `Calibration` interface (`BoxCalibration`, default box inset 15%, clamped, sensitivity scales the box). Pipeline after tracking lives in `pipeline/engine.py` so replays and tests run the live code. Traversal replay reaches all four screen edges. Accessibility re-checked every 2 s with a loud banner. Physical AC (<100 ms perceived lag) pending. |
| CONJ-6 | One Euro filter + precision mode | B | code done | Tuned on real recordings: settled idle jitter 4.8 px raw to 1.3 px mean (p95 4.4 px, which includes real micro-movements), fast-sweep lag ~14 px. Precision gain 0.3 below 60 px/s, re-anchor above 400 px/s, edge snap. `position_at(t)` history for CONJ-7. All params in config. Physical gate (idle jitter, no visible trail) pending. |
| CONJ-7 | Pinch click with hysteresis | C (Dev A) | code done | Engage 0.20 / release 0.32 (ratio to hand size), 150 ms hold, click on release at the pre-pinch position (start of the closing motion). Only counts with the other fingers open; untrusted when the pinching fingertips touch the frame edge. Thumb+middle = right click. Two quick pinches = real macOS double-click (ClickCounter + Quartz click state). Headless: 0 false clicks on traversal/idle/exits. Physical AC (19/20 pinches) pending the deferred `pinches` recording. |
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

## Stage gates

| Gate | Status | Evidence / pending |
| --- | --- | --- |
| Phase B (CONJ-5..6) | **code done, physical gate deferred** | Headless: traversal replay reaches all edges, idle jitter 1.3 px mean. Pending: live cursor feel (<100 ms lag, smooth), the hour-3 go/no-go. |
| Phase A (CONJ-1..4) | **passed with deferrals** | Live: 30 fps with preview, track ~15 ms, either hand, sticky with two hands. Recorded: `traversal`, `idle`, `exits` (stopped at 51 s of 70, but holds 12 clean exit/re-entry cycles). **Deferred by the user** (build continues meanwhile): `pinches`, `small_range` recordings. |

## Shared contracts (frozen before Phase C)

| Contract | Module | Status |
| --- | --- | --- |
| LandmarkFrame | `pipeline/landmarks.py` | frozen (field-list tripwire test in `tests/test_landmarks.py`) |
| Mode state machine | `pipeline/modes.py` | frozen. Pause is tracked by reason (hand_lost, user); resume restores the click mode. Thread-safe. |
| ClickEvent | `pipeline/events.py` | frozen. Adds `amount` (scroll steps) to the plan's `{action, position}`: scroll needs a magnitude. Consumed only by `pipeline/action_mapper.py`. |
| profile.json schema | `pipeline/profile_schema.py` | frozen, version 1. All-or-nothing validation. **Deviation:** gesture samples are `[3][T][21][3]` sequences, not `[3][21][3]` poses (see open questions). |

## Decisions

- **mediapipe pinned to 0.10.33.** 1.0.1 aborts on macOS when HandLandmarker opens (`DrishtiMetalHelper ... Service is unavailable`), with both GPU and CPU delegates, inside and outside the sandbox. 0.10.35 runs, but ships a Google telemetry uploader (Clearcut, `play.googleapis.com/log`) that tried to send data during the first recordings, breaking the no-network rule; there is no opt-out switch. 0.10.32 and 0.10.33 contain no uploader. 0.10.33 runs at ~13.7 ms/frame on a blank frame (M1, CPU). `tests/test_no_network.py` fails if an upgrade brings the uploader back.
- **mediapipe 0.10.3x has no `mp.solutions.hands`.** HandTracker uses the Tasks API (`HandLandmarker`, VIDEO mode), which needs a model file. `models/hand_landmarker.task` is committed so runtime never touches the network and both laptops run the identical model (source: Google's `mediapipe-models` bucket, float16/latest, sha256 `fbc2a300...cde1`).
- **`opencv-contrib-python` instead of `opencv-python`.** mediapipe hard-requires the contrib build, which provides the same `cv2` module. Having both installed makes them overwrite each other.
- **One demo machine, no backup laptop.** The team has a single M1 MacBook Air, so the both-laptops ACs (CONJ-1, CONJ-2) and the build plan's laptop-parity gate are waived. The plan's backup-laptop mitigation is gone, which makes the CONJ-20 backup video (stored on a phone too) the only fallback for a machine failure.

- **Tracker runs with num_hands=1.** First live run (Phase A gate) with num_hands=2: tracking 25-29 ms/frame with a hand visible, over the ~20 ms budget, because MediaPipe reruns palm detection every frame while looking for a second hand. num_hands=1 tracks the locked hand by ROI instead. The preview window itself costs 13-18 ms/frame on macOS (imshow + waitKey); with it hidden the loop held 30 fps.

- **MediaPipe handedness labels are swapped on our mirrored input.** The Phase A gate showed the left hand labeled "Right" and vice versa, contrary to MediaPipe's docs. `SWAP_HANDEDNESS = True` corrects it at the tracker, so LandmarkFrame and recordings carry the user's real hand.

- **Recordings: hand labels flicker; rested wrist sits at the frame bottom.** In `traversal` the label flipped to "Left" in 12 of 1695 hand frames, so nothing downstream may depend on per-frame handedness. In `idle` (forearm rested) the wrist reaches y=1.02, slightly past the bottom edge; calibration and the control point must not depend on the wrist being in frame.

- **Pinch only counts with the other fingers open.** In `traversal` the user's natural pointing posture was curled fingers (median extension 0.63 vs ~2.0 open), and a curled hand puts the thumb tip on the index finger: 5% of frames looked like a pinch. Requiring middle/ring/pinky open (extension > 1.2) gives 0 sustained false pinches in all three recordings. Teach it as "pinch with your other fingers open".
- **Edge trust is per fingertip, not per hand.** With the hand near the camera the wrist is usually below the frame (80% of traversal frames touch an edge). Only the thumb and pinching finger joints must be 3% inside the frame.
- **Scroll will use the two-finger V pose, not a fist.** A fist is the user's resting travel pose, so it would scroll constantly. The V pose (index + middle out, ring + pinky folded) never occurs by accident in any recording (max 1 frame).

## Granted runners (CONJ-2 AC)

| Laptop | Runner app | Accessibility | Camera | Cursor | Click |
| --- | --- | --- | --- | --- | --- |
| M1 MacBook Air (Hirats-MacBook-Air-4) | **Terminal.app** (demo runner) | pass | pass (1920x1080 default, ~22 fps) | pass | pass (double-click in TextEdit) |
| M1 MacBook Air | Visual Studio Code.app (dev only) | pass | untested | untested | untested |

Permissions belong to the runner app. Demo from the same runner listed here, or re-run the script after switching.

## Open questions

- **Gesture template shape.** The build plan's table says `samples[3][21][3]` (three single poses), but CONJ-10 records a *motion* and CONJ-11 matches with a sliding window, which needs sequences. Implemented as `samples[3][T][21][3]`; a static pose is T = 1, so both readings work. Confirm, or say if the custom gesture should be a static pose only.

