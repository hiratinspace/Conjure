"""CONJ-2 smoke test: camera, cursor movement, and a synthetic click.

macOS grants Camera and Accessibility to the app that launched Python (Terminal,
iTerm, VS Code, ...), not to Python itself. Without Accessibility the cursor may
still move while clicks silently never land, so this script checks all three.

Usage, from the repo root, in the terminal you will demo from:
    .venv/bin/python scripts/check_permissions.py
"""

import argparse
import ctypes
import os
import platform
import socket
import subprocess
import sys
import time

APP_SERVICES = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"


def runner_chain():
    """Process names from this script up to launchd; the .app among them holds the permissions."""
    chain, pid = [], os.getppid()
    while pid > 1:
        out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        if not out:
            break
        ppid, comm = out.split(None, 1)
        chain.append(comm)
        pid = int(ppid)
    return chain


def runner_app(chain):
    for comm in chain:
        if ".app/" in comm:
            return comm.split(".app/")[0].rsplit("/", 1)[-1] + ".app"
    return os.environ.get("TERM_PROGRAM", "unknown")


def accessibility_trusted():
    lib = ctypes.cdll.LoadLibrary(APP_SERVICES)
    lib.AXIsProcessTrusted.restype = ctypes.c_bool
    return bool(lib.AXIsProcessTrusted())


def check_input_monitoring():
    """The F8 and F9 hotkeys need Input Monitoring (separate from Accessibility): without it macOS
    refuses to create a keyboard event tap."""
    try:
        import Quartz
        tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                      Quartz.kCGEventTapOptionListenOnly,
                                      Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
                                      lambda proxy, t, event, refcon: event, None)
        if tap is not None:
            return True, "granted (F8 pause and F9 panel hotkeys will work)"
        return False, ("NOT granted: System Settings > Privacy & Security > Input Monitoring > enable this "
                       "terminal app, then restart it. Only the F8 and F9 hotkeys need it.")
    except Exception as e:
        return False, f"could not test ({e})"


def check_camera(index, seconds=2.0):
    import cv2

    cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    if not cap.isOpened():
        return False, "camera did not open (denied, or in use by another app)"
    frames, shape, start = 0, None, time.perf_counter()
    while time.perf_counter() - start < seconds:
        ok, frame = cap.read()
        if ok and frame is not None:
            frames += 1
            shape = frame.shape
    cap.release()
    if frames == 0:
        return False, "camera opened but delivered no frames (permission prompt pending or denied)"
    fps = frames / seconds
    return True, f"{shape[1]}x{shape[0]} at ~{fps:.0f} fps"


def check_cursor_moves(size=150, tolerance=2):
    from pynput.mouse import Controller

    mouse = Controller()
    x0, y0 = mouse.position
    corners = [(x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size), (x0, y0)]
    misses = []
    for cx, cy in corners:
        mouse.position = (cx, cy)
        time.sleep(0.25)
        ax, ay = mouse.position
        if abs(ax - cx) > tolerance or abs(ay - cy) > tolerance:
            misses.append(((cx, cy), (round(ax), round(ay))))
    if misses:
        return False, f"cursor did not land where sent: {misses}"
    return True, f"traced a {size}px square from ({round(x0)}, {round(y0)})"


def check_click(countdown):
    from pynput.mouse import Button, Controller

    print("\n  Click test:")
    print("   1. Open TextEdit, create a new document, and type a few words.")
    print("   2. Rest the mouse pointer on top of one word and let go of the mouse.")
    for n in range(countdown, 0, -1):
        print(f"   Double-clicking in {n}...", end="\r", flush=True)
        time.sleep(1)
    Controller().click(Button.left, 2)
    print("   Double-click sent.            ")
    answer = input("   Did the word under the pointer get highlighted? [y/n] ").strip().lower()
    if answer.startswith("y"):
        return True, "double-click registered in TextEdit"
    return False, "double-click did not register (Accessibility not granted to this runner?)"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    parser.add_argument("--countdown", type=int, default=5, help="seconds before the test click")
    parser.add_argument("--skip-camera", action="store_true")
    parser.add_argument("--skip-input", action="store_true", help="skip cursor and click tests")
    args = parser.parse_args()

    chain = runner_chain()
    app = runner_app(chain)
    trusted = accessibility_trusted()

    results = [("Accessibility trusted", trusted, "granted" if trusted else
                f"NOT granted: System Settings > Privacy & Security > Accessibility > enable {app}, then restart it")]
    results.append(("Input Monitoring (panic key)", *check_input_monitoring()))
    if not args.skip_camera:
        ok, msg = check_camera(args.camera)
        if not ok:
            msg += f"; check System Settings > Privacy & Security > Camera > {app}"
        results.append(("Camera", ok, msg))
    if not args.skip_input:
        results.append(("Cursor move", *check_cursor_moves()))
        results.append(("Click", *check_click(args.countdown)))

    all_ok = all(ok for _, ok, _ in results)
    print("\n===== Conjure permission check (paste this block back) =====")
    print(f"Machine:  {socket.gethostname()} ({platform.machine()}, macOS {platform.mac_ver()[0]})")
    print(f"Python:   {sys.version.split()[0]} at {sys.executable}")
    print(f"Runner:   {app}")
    print(f"Chain:    {' <- '.join(os.path.basename(c) for c in chain)}")
    for name, ok, msg in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {msg}")
    print(f"RESULT:   {'ALL PASS' if all_ok else 'FAIL'}")
    print("============================================================")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
