"""Panic key: one global key pauses or resumes Conjure from anywhere.

If the cursor runs wild on stage, the operator presses the key (F8 by
default) and all input stops at once, through the same user pause the
panel's Pause button uses; pressing it again resumes. It works whichever app
has focus, because pynput's keyboard listener is global. On macOS that needs
Input Monitoring permission for the terminal app (separate from
Accessibility); without it the listener thread dies quietly, which is checked
here and reported. The listener runs on its own thread and hands the toggle
to the pipeline thread through engine.submit.
"""

import logging
import time

log = logging.getLogger("conjure.panic")


def start_panic_key(key_name, engine, toggle):
    """Start the global listener. Returns the listener, or None if it could not start."""
    try:
        from pynput import keyboard
    except Exception:
        log.warning("pynput keyboard unavailable: no panic key")
        return None
    try:
        key = getattr(keyboard.Key, key_name.lower())
    except AttributeError:
        key = keyboard.KeyCode.from_char(key_name)

    armed = [True]  # holding the key down autorepeats on macOS: toggle once per press, re-arm on release

    def on_press(pressed):
        if pressed == key and armed[0]:
            armed[0] = False
            engine.submit(toggle)
            log.warning("panic key (%s): pause toggled", key_name)

    def on_release(released):
        if released == key:
            armed[0] = True

    try:
        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.daemon = True
        listener.start()
        listener.wait()
        time.sleep(0.3)  # the tap is created on the listener thread; without Input Monitoring it dies right away
        if not listener.running:
            log.warning("panic key %s is NOT active: macOS needs Input Monitoring for this terminal app "
                        "(System Settings > Privacy & Security > Input Monitoring), then restart it", key_name.upper())
            return None
        log.info("panic key armed: %s pauses or resumes Conjure from any app", key_name.upper())
        return listener
    except Exception:
        log.warning("could not start the panic key listener", exc_info=True)
        return None
