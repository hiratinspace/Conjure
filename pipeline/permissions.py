"""macOS permission and display queries via ctypes (no extra dependencies)."""

import ctypes
import logging
import time

log = logging.getLogger("conjure.permissions")

_APP_SERVICES = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
_CORE_GRAPHICS = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"


def accessibility_trusted():
    """True if the runner app may post synthetic input. Without it, clicks silently vanish."""
    lib = ctypes.cdll.LoadLibrary(_APP_SERVICES)
    lib.AXIsProcessTrusted.restype = ctypes.c_bool
    return bool(lib.AXIsProcessTrusted())


class _CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


class _CGSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]


class _CGRect(ctypes.Structure):
    _fields_ = [("origin", _CGPoint), ("size", _CGSize)]


def main_screen_size():
    """(width, height) of the main display in points, the coordinate space pynput uses."""
    cg = ctypes.cdll.LoadLibrary(_CORE_GRAPHICS)
    cg.CGMainDisplayID.restype = ctypes.c_uint32
    cg.CGDisplayBounds.restype = _CGRect
    cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
    rect = cg.CGDisplayBounds(cg.CGMainDisplayID())
    return int(rect.size.width), int(rect.size.height)


class PermissionWatch:
    """Re-checks Accessibility periodically so a revoked permission is loud, not silent dead clicks."""

    def __init__(self, interval_s, check=accessibility_trusted, clock=time.monotonic):
        self.interval_s = interval_s
        self._check = check
        self._clock = clock
        self._next = 0.0
        self.trusted = True

    def poll(self):
        now = self._clock()
        if now >= self._next:
            self._next = now + self.interval_s
            trusted = self._check()
            if not trusted and self.trusted:
                log.error("!!! ACCESSIBILITY PERMISSION MISSING: clicks and cursor moves will be dropped. "
                          "System Settings > Privacy & Security > Accessibility > enable this terminal app, "
                          "then restart it. !!!")
            elif trusted and not self.trusted:
                log.warning("Accessibility permission restored")
            self.trusted = trusted
        return self.trusted
