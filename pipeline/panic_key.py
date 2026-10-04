"""Global hotkeys: F8 pauses or resumes Conjure from anywhere; F9 brings the panel back.

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


def start_panic_key(key_name, engine, toggle, extra=None):
    """Start the global listener: `key_name` toggles the pause via engine.submit(toggle); `extra` maps
    other key names to plain callbacks (called on the listener thread, so they must only set flags).
    Returns the listener, or None if it could not start."""
    try:
        from pynput import keyboard
    except Exception:
        log.warning("pynput keyboard unavailable: no panic key")
        return None

    def resolve(name):
        try:
            return getattr(keyboard.Key, name.lower())
        except AttributeError:
            return keyboard.KeyCode.from_char(name)

    key = resolve(key_name)
    extra_keys = {resolve(name): fn for name, fn in (extra or {}).items()}
    armed = {k: True for k in [key] + list(extra_keys)}  # autorepeat: act once per press, re-arm on release

    def on_press(pressed):
        if pressed in armed and armed[pressed]:
            armed[pressed] = False
            if pressed == key:
                engine.submit(toggle)
                log.warning("panic key (%s): pause toggled", key_name)
            else:
                extra_keys[pressed]()

    def on_release(released):
        if released in armed:
            armed[released] = True

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
