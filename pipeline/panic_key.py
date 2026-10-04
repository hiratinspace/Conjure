"""Panic key: one global key pauses or resumes Conjure from anywhere.

If the cursor runs wild on stage, the operator presses the key (F8 by
default) and all input stops at once, through the same user pause the
panel's Pause button uses; pressing it again resumes. It works whichever app
has focus, because pynput's keyboard listener is global (it needs the same
Accessibility permission as clicking). The listener runs on its own thread
and hands the toggle to the pipeline thread through engine.submit.
"""

import logging

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

    def on_press(pressed):
        if pressed == key:
            engine.submit(toggle)
            log.warning("panic key (%s): pause toggled", key_name)

    try:
        listener = keyboard.Listener(on_press=on_press)
        listener.daemon = True
        listener.start()
        log.info("panic key armed: %s pauses or resumes Conjure from any app", key_name.upper())
        return listener
    except Exception:
        log.warning("could not start the panic key listener", exc_info=True)
        return None
