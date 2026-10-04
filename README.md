# Conjure

**A webcam mouse that learns your hand, instead of making your hand learn it.**

Conjure turns a standard laptop webcam into a full mouse replacement for people with limited hand mobility: tremor, arthritis, partial paralysis, repetitive strain injury. Your hand moves the cursor. You click with a pinch, by holding still, or with a gesture you record yourself. No extra hardware, no account, and no video ever leaves the laptop.

Every other webcam pointer ships a fixed set of gestures and expects your hand to adapt. Conjure inverts that: any motion your hand can repeat reliably becomes a click.

## Measured, not claimed

Results from real recorded sessions in [`recordings/`](recordings/), reproducible with `python -m pytest`:

| | Typical webcam-mouse tutorial | Conjure |
| --- | --- | --- |
| False clicks during ~2.5 min of ordinary pointing (no click intended) | **41** | **0** |
| Cursor shake with the hand at rest | 4.8 px | 1.3 px |
| Custom gesture recognized (10 varied casts) | not possible | 8 or more of 10, within 500 ms |
| Hand leaves view: input frozen | never | within 0.5 s, every time |

The tutorial approach misfires because it follows the fingertip (which moves when you pinch), measures the pinch in camera pixels (so leaning toward the camera "pinches"), and clicks the instant the fingers cross a line. Conjure fixes each of those, and the app's **tutorial mode** shows the difference live, side by side.

## What it does

| Your hand | Result |
| --- | --- |
| Move it (small movements, forearm rested) | The cursor follows the knuckle at the base of your index finger, smoothed against tremor, with automatic slow-motion for small targets. |
| Pinch thumb to index, other fingers open, then release | Left click, landing where the cursor was *before* you pinched. Two quick pinches make a double-click. |
| Pinch thumb to middle finger | Right click. |
| Pinch, hold, and move | Drag. |
| Hold still for 0.8 s (dwell mode) | Left click, with a countdown ring so it never feels accidental. For hands that can't pinch. |
| Your own recorded gesture (spell mode) | Left click. Record it 3 times, name it, and it works anywhere in the frame, at any distance from the camera. |
| Two fingers up (V), then lift or lower your hand | Scroll. |
| Drop your hand out of view | Everything pauses within half a second, so nothing can click while you rest. |

**Range-of-motion calibration** maps the small area you can move in comfortably (about 3 inches, forearm on the table) onto the whole screen.

**Feedback at all times:** a status indicator (tracking, near edge, paused, no hand), a pinch progress dot, a dwell countdown ring, a click sound, and the spell's name flashing on screen and spoken aloud (ElevenLabs, with an offline fallback).

## How it compares

| | Apple Head Pointer | Google Project Gameface | AirTouch | Tutorials | **Conjure** |
| --- | --- | --- | --- | --- | --- |
| Tracks | Head | Head + face | Hand | Hand | **Hand** |
| Record your own gesture as a click | No | No | No (consumer tiers) | No | **Yes** |
| Per-user range-of-motion calibration | No | No | Not documented | No | **Yes** |
| Click without pinching | Yes (dwell) | Yes (face expressions) | Not documented | No | **Yes** |
| Free and on-device | Yes | Yes | On-device, paid | Yes | **Yes** |
| On macOS | Yes | No | Not yet | Yes | **Yes** |

Sources and details: [`PITCH.md`](PITCH.md).

## Quick start

Requirements: a Mac with Apple Silicon, Python 3.11 or newer, a webcam.

```bash
git clone https://github.com/hiratinspace/Conjure.git
cd Conjure
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/check_permissions.py   # grants and checks Camera + Accessibility
python main.py --spellbook            # run Conjure and open the demo page
```

macOS asks for **Camera** and **Accessibility** permission for your terminal app. Grant both, then quit and reopen the terminal. Without Accessibility the cursor can move but clicks are silently dropped, so the check script verifies a real click.

First run:

1. In the Conjure panel, press **Calibrate**, rest your forearm, and trace the edges of a small comfortable area.
2. Pick a click mode: **Pinch**, **Dwell**, or **Spell** (press **Record spell** first).
3. Work through the spellbook page that opened in your browser.

Useful flags: `--preview` (camera view with landmarks), `--no-ui` (minimal fallback), `--replay recordings/idle.jsonl` (run from a recording, no camera). Optional spoken feedback: set `ELEVENLABS_API_KEY` in your shell; without it Conjure speaks with the built-in macOS voice.

## Privacy

All video is processed on this laptop by MediaPipe and never stored or sent anywhere. The only network call in the codebase is the optional ElevenLabs text-to-speech request, isolated in one module (a test fails if any other module touches the network). We pinned MediaPipe 0.10.33 because a newer release added usage telemetry, and a test guards against it returning.

## How it is built

A single Python process. A worker thread runs the per-frame pipeline: camera, MediaPipe hand landmarks, then calibration mapping, One Euro smoothing with precision mode, then pinch, dwell, scroll, and gesture detectors that emit one shared click event type. The main thread runs a Tk interface: a transparent, click-through overlay and a settings panel with large targets, usable with Conjure itself. The whole pipeline after tracking also runs from recorded sessions, so the acceptance tests (zero false clicks, jitter, calibration reach, pause timing) run headless against real hand data.

```
camera -> hand tracker -> calibration -> smoothing -> pinch / dwell / spell / scroll -> clicks
```

Developer notes are in [`CLAUDE.md`](CLAUDE.md), build decisions and the measurements behind them in [`PROGRESS.md`](PROGRESS.md), and the demo-day procedure in [`RUNBOOK.md`](RUNBOOK.md).

```bash
python -m pytest -q   # 239 tests, about 8 seconds, no camera needed
```

## Limitations and roadmap

Built in 18 hours, so deliberately narrow: macOS only, one screen, one hand, one recorded spell. Next on the roadmap: an on-screen keyboard for text entry, several spells mapped to different actions, and Windows and Linux support (the stack is cross-platform; only macOS is built and tested).

## Credits

Built solo in an 18-hour hackathon. Hand tracking by [MediaPipe](https://ai.google.dev/edge/mediapipe), smoothing by the [One Euro filter](https://gery.casiez.net/1euro/) (Casiez et al., 2012), voice by [ElevenLabs](https://elevenlabs.io).
