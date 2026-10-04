"""Global hotkeys: F8 pauses or resumes Conjure from anywhere; F9 brings the panel back.

Implemented as a Quartz event tap on its own thread, reading only the key
code of each key-down event. A pynput keyboard listener was used first, but
it maps every key through the Text Services Manager on its own thread, which
macOS asserts must happen on the main thread: any key press in any app
crashed Conjure with "Trace/BPT trap". A tap that never translates keys has
no such call.

Needs Input Monitoring for the terminal app (separate from Accessibility);
without it CGEventTapCreate returns None, which is reported. Callbacks run on
the tap thread, so they must be thread-safe: engine.submit, or set a flag.
Autorepeat events are ignored, so holding a key acts once.
"""

import logging
import threading

log = logging.getLogger("conjure.panic")

KEYCODES = {"f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101,
            "f10": 109, "f11": 103, "f12": 111, "escape": 53}


class QuartzHotkeyTap(threading.Thread):
    """Listen-only tap: bindings maps key codes to callbacks. `ok` says whether the tap could be created."""

    def __init__(self, bindings):
        super().__init__(name="conjure-hotkeys", daemon=True)
        self.bindings = bindings
        self.ok = False
        self.ready = threading.Event()

    def run(self):
        import Quartz

        tap_ref = []

        def on_event(_proxy, event_type, event, _refcon):
            if event_type == Quartz.kCGEventKeyDown:
                code = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
                repeat = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat)
                fn = self.bindings.get(code)
                if fn is not None and not repeat:
                    try:
                        fn()
                    except Exception:
                        log.exception("hotkey handler failed")
            elif event_type in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
                if tap_ref:
                    Quartz.CGEventTapEnable(tap_ref[0], True)
            return event

        tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                      Quartz.kCGEventTapOptionListenOnly,
                                      Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown), on_event, None)
        if tap is None:
            self.ready.set()
            return
        tap_ref.append(tap)
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        self.ok = True
        self.ready.set()
        Quartz.CFRunLoopRun()


def start_panic_key(key_name, engine, toggle, extra=None, tap_factory=QuartzHotkeyTap):
    """Start the hotkeys: `key_name` toggles the pause via engine.submit(toggle); `extra` maps other key
    names to callbacks. Returns the tap, or None if it could not start (no Input Monitoring)."""
    try:
        bindings = {KEYCODES[key_name.lower()]: lambda: (engine.submit(toggle),
                                                        log.warning("panic key (%s): pause toggled", key_name))}
        for name, fn in (extra or {}).items():
            bindings[KEYCODES[name.lower()]] = fn
    except KeyError as e:
        log.warning("unknown hotkey %s: hotkeys disabled", e)
        return None
    try:
        tap = tap_factory(bindings)
        tap.start()
        tap.ready.wait(2.0)
    except Exception:
        log.warning("could not start the hotkey tap", exc_info=True)
        return None
    if not tap.ok:
        log.warning("hotkeys %s are NOT active: macOS needs Input Monitoring for this terminal app "
                    "(System Settings > Privacy & Security > Input Monitoring), then restart it",
                    ", ".join([key_name.upper()] + [n.upper() for n in (extra or {})]))
        return None
    log.info("hotkeys armed: %s pauses or resumes Conjure from any app%s", key_name.upper(),
             "; " + ", ".join(n.upper() for n in extra) + " brings the panel back" if extra else "")
    return tap
