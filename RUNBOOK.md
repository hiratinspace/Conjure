# Conjure demo runbook

One laptop (the M1), two people:

- **Presenter**: talks, and controls the computer with their hand in front of the camera. Never touches the trackpad.
- **Operator**: stands at the laptop side with the trackpad, watches the terminal and overlay, and calls every fallback. The Presenter never has to improvise a failure response.

Everything runs from **Terminal.app**, the runner that holds Camera and Accessibility permission.

## The night before

1. `cd ~/Downloads/Hackathon/Conjure && source .venv/bin/activate`
2. `python -m pytest -q`: all tests pass.
3. `python scripts/check_permissions.py`: `RESULT: ALL PASS`. If anything fails, the line says which setting to change.
4. Voice clips: `export ELEVENLABS_API_KEY=...` in that shell, then `python scripts/pregenerate_voices.py`. Commit `audio/voice/`.
5. Record the backup video (below). Copy it to the Desktop and to a phone.
6. Charge the laptop and phone. Pack a desk lamp and a plain backdrop (a sheet or poster board).

## 30 minutes before (at the venue)

1. Set up the lamp in front of the Presenter's hand and the backdrop behind it. No window behind the Presenter.
2. Launch: `python main.py --spellbook`. The Conjure panel, the overlay, and the spellbook (in the browser) open.
3. Presenter: rest the forearm, then **Calibrate** in the panel and trace the comfortable area.
4. Presenter: **Record spell** in the panel, cast the chosen gesture 3 times, then name it. Use a big, distinct motion; heed any warning that appears.
5. Run the 3-minute script below twice, back to back. Count false clicks.
6. If anything misbehaves, tune `venue.json` (each key says which way to turn it), quit with **Quit** in the panel, and relaunch. Calibration and the spell survive a relaunch.
7. Set `STAGE_CLICK_MODE` in `venue.json` to the mode that was most reliable in the two runs. Commit `venue.json`.
8. Spellbook: reload the page so it starts at page I.

## The 3-minute script

| Time | Spellbook page | Presenter says and does |
| --- | --- | --- |
| 0:00 | (before) | "Mice hurt or don't work for people with tremor, arthritis, or paralysis. Every webcam pointer asks your hand to learn its gestures. Conjure learns yours." |
| 0:20 | I. Point | Hand rested, small movements, light the three runes. "Two inches of comfortable movement covers the whole screen." |
| 0:45 | II. Pinch | Pinch with fingers open to light the candle. |
| 1:05 | III. Hold still | Operator presses **Dwell** in the panel. Hold over the crystal until the ring fills. "For hands that can't pinch." |
| 1:30 | IV. Your own spell | Operator presses **Spell**. Point at the door and cast the recorded gesture: the name flashes and is spoken. "Any motion your hand can repeat becomes a click." |
| 2:00 | V. Scroll | Two fingers up, lift the hand to read the scroll. |
| 2:20 | VI. Drag | Pinch the moonstone into the cauldron (in dwell mode: click the stone, then the cauldron). |
| 2:40 | VII. Finale | Drop the hand out of view: "It pauses when you rest, so nothing clicks by accident. Everything runs on this laptop; no video leaves it." |

## Fallback ladder

Each step down is called by the **Operator**, out loud ("switching to dwell"), so the Presenter can keep talking.

| Level | Trigger (Operator watches for) | Action (Operator) |
| --- | --- | --- |
| 1. Pinch (stage default) | Start here. | |
| 2. Dwell only | 2 false or missed pinch clicks in a row, or the cursor jumps while pinching. | Press **Dwell** in the panel (or `m` in the preview). Dwell needs no pinch and ignores jitter. The spellbook is fully completable by dwell. |
| 3. Spellbook only, skip pages | Tracking drops repeatedly (the "Paused" banner appears while the hand is in view, twice within 30 s), or a step fails twice. | Click **Next page** on the trackpad to skip the failing step; the Presenter narrates it. |
| 4. Backup video | Conjure crashes, the camera stops, or tracking is gone for more than 10 s. | Quit Conjure (`Ctrl+C` in Terminal), open `~/Desktop/conjure-demo.mov` in QuickTime, press `Cmd+F` for full screen, and play. If the laptop itself fails, play the phone copy. |

Restarting is level 3.5: `Ctrl+C`, then `python main.py --spellbook`. It takes about 5 seconds, and nothing needs redoing (calibration and the spell are saved).

## Backup video

1. Run the full script once with everything working (spell recorded, voice on).
2. `Cmd+Shift+5`, choose **Record Entire Screen**, Options > Microphone: built-in (to capture the narration), then **Record**.
3. Perform the whole script in under 3 minutes. Stop with the stop button in the menu bar.
4. Save as `~/Desktop/conjure-demo.mov`. AirDrop it to a phone. Play it once on both to check.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Cursor moves but clicks do nothing | Accessibility lost for this terminal (a red banner says so) | System Settings > Privacy & Security > Accessibility > Terminal on, `Cmd+Q` Terminal, relaunch. |
| `camera ... did not open` | Another app has the camera, or Camera permission is off | Quit Zoom, FaceTime, or Photo Booth; check Privacy & Security > Camera > Terminal. |
| "Paused" banner while the hand is visible | Dim light or busy background | Turn on the lamp, move the backdrop, or raise `PAUSE_AFTER_FRAMES` in `venue.json`. |
| Clicks fire while just moving | Fingers drifting closed while pointing | Switch to dwell (level 2). After the demo: lower `PINCH_ENGAGE_RATIO` or raise `PINCH_OPEN_EXTENSION`. |
| Spell does not fire | Cast differs from the recording, or venue light changed the hand's look | Raise `GESTURE_MATCH_SCALE` in `venue.json`, or press **Spell forgiveness +** in the panel, or re-record the spell. |
| Spell name is spoken by the robotic Mac voice | No network or no key; the offline fallback is working as designed | Nothing to fix. Pre-generated clips cover the stock spell names. |
| Cursor cannot reach a screen edge | Calibration area too large | **Calibrate** again with a smaller area, or press **Sensitivity +**. |
| Overlay intercepts clicks | Click-through failed (a warning is logged at startup) | Relaunch; if it persists, run `python main.py --no-ui` (no overlay) and use the spellbook only. |
