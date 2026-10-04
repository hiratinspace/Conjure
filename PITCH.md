# Conjure pitch material

## The one-line claim

Every other webcam pointer makes your hand learn its gestures. Conjure learns yours: record any motion your hand can repeat, and it becomes a click.

## Measured, not claimed

Numbers from this laptop's camera and the recordings in `recordings/` (reproducible: `python -m pytest tests/test_tutorial.py tests/test_pinch.py tests/test_filter.py`).

| Measurement | Typical tutorial approach | Conjure |
| --- | --- | --- |
| False clicks during 2.4 min of ordinary pointing, no click intended (3 sessions) | 17 (14 + 3 + 0) | 0 |
| Accidental contacts Conjure detected and blocked in those sessions | (none: it clicks) | 17 |
| Real pinches recognized (111 deliberate pinches, three sessions) | n/a | 100 (90%); 42 of 43 in the latest |
| Cursor shake with the hand at rest | 4.8 px (raw) | 1.3 px |
| Lag on a fast sweep | n/a | ~14 px (about one frame) |
| Spell recognized on 10 varied casts (speed, position, noise) | n/a | at least 8 of 10 within 500 ms |
| Hand leaves view: input frozen within | never (cursor freezes, clicks still possible) | under 0.5 s, every time (13 of 13) |

Why the tutorial approach misfires: it follows the fingertip (which moves when you pinch), measures the pinch in camera pixels (so leaning toward the camera "pinches"), and clicks the instant the fingers cross a line (no hold time, no hysteresis). A relaxed, curled hand drifts the thumb onto the index finger; Conjure counts only a pinch that snaps shut from open (under 200 ms; real pinches measured 33 to 167 ms), whatever shape the rest of the hand is in.

## Comparison slide

Verified against current sources in October 2026 (details and links below). Keep the footnotes on the slide or in the speaker notes.

| | Apple Head Pointer | Google Project Gameface | AirTouch (Neural Lab) | Tutorials | **Conjure** |
| --- | --- | --- | --- | --- | --- |
| Tracks | Head | Head + face expressions | Hand | Hand | **Hand** |
| Record your *own* gesture as a click | No (preset expressions) | No (preset expressions, adjustable thresholds) | No on consumer tiers (15-gesture library; custom training sold to OEMs) | No | **Yes** |
| Per-user range-of-motion calibration | No (speed and edge settings only) | No (per-direction speed only) | Not documented | No (fixed inset box) | **Yes** |
| Click without pinching | Yes (dwell) | Yes (face expressions; no dwell) | Not documented (pinch clicks) | No | **Yes (dwell, or your own gesture)** |
| Designed for a rested arm, small movements | Not applicable (head) | Not applicable (face) | No evidence (kiosk-oriented) | No | **Yes** |
| Free | Yes (built in) | Yes (open source; archived Sept 2025) | No ($299 per year) | Yes | **Yes** |
| Runs on-device | Yes | Yes | Yes | Yes | **Yes** |
| On macOS | Yes | No (Windows, Android) | Not yet ("on the way") | Yes | **Yes** |

Say it honestly on stage: Apple's head pointer and dwell are excellent and free; Conjure's difference is that the click is a motion *you* choose and the range is calibrated to *your* comfortable movement.

### Sources

- Apple Pointer Control (head pointer, speed, distance to edge): https://support.apple.com/guide/mac-help/change-pointer-control-settings-accessibility-unac899/mac
- Apple head pointer expressions (preset list): https://eshop.macsales.com/blog/64948-control-mac-with-head-gestures/ and https://mcmw.abilitynet.org.uk/how-to-control-your-computer-with-head-movement-in-macos-14-sonoma
- Apple Dwell: https://support.apple.com/guide/mac-help/mchl437b47b0/mac
- Project Gameface (archived Sept 5, 2025; Windows and Android configs, no dwell): https://github.com/google/project-gameface, https://github.com/google/project-gameface/blob/main/Windows/README.md, https://github.com/google/project-gameface/blob/main/Android/README.md
- Neural Lab AirTouch (on-device inference, pricing, platforms, gesture library): https://www.neural-lab.com, https://www.neural-lab.com/pricing, https://www.engadget.com/computing/accessories/neural-labs-airtouch-brings-gesture-control-to-windows-and-android-devices-with-just-a-webcam-180031750.html
- Representative tutorial (fixed inset box, fingertip-distance click): https://github.com/s0409/AI-VIRTUAL-MOUSE

Recheck the AirTouch row the morning of the demo: commercial products change.

## Lines worth saying out loud

- "Two inches of rested movement covers the whole screen." (during calibration)
- "Your spell works anywhere in the frame, at any distance from the camera: we normalize every sample to the hand itself."
- "If your three recordings don't look alike, Conjure says so instead of saving a spell that will fail you later."
- "When you rest, it pauses. A frozen cursor that can still click is how other tools hurt people."
- "Everything runs on this laptop. No video leaves it."
