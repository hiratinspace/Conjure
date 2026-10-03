"""Conjure: webcam hand tracking as a mouse replacement.

The single process loop. Each stage is a module in pipeline/; this file only
wires them together and owns startup and shutdown.
"""

import argparse
import logging
import sys

import config
from pipeline.frame_source import CameraError, FrameSource
from pipeline.preview import QUIT, Preview
from pipeline.timing import StageTimer

log = logging.getLogger("conjure")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Conjure: hand-tracking pointer for macOS")
    parser.add_argument("--preview", action="store_true", help="show the debug preview window (p hides it, q quits)")
    parser.add_argument("--camera", type=int, default=config.CAMERA_INDEX, help="camera index")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    return parser.parse_args(argv)


def run(args):
    timer = StageTimer(config.FRAME_BUDGET_MS, config.TIMING_LOG_INTERVAL_S)
    preview = Preview(enabled=args.preview)
    source = FrameSource(args.camera, config.CAMERA_WIDTH, config.CAMERA_HEIGHT, config.CAMERA_FPS,
                         config.MIRROR, config.CAMERA_WARMUP_FRAMES, config.FPS_SMOOTHING)
    with source:
        while True:
            with timer.stage("capture", budgeted=False):
                frame, t = source.read()

            with timer.stage("preview"):
                action = preview.show(frame, lines=[f"{source.fps:.1f} fps"])
            if action == QUIT:
                break
            timer.end_frame()
    preview.close()


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log.info("Conjure starting (frame budget %.0f ms). Ctrl+C to quit.", config.FRAME_BUDGET_MS)
    try:
        run(args)
    except CameraError as e:
        log.error("%s", e)
        return 1
    except KeyboardInterrupt:
        pass
    log.info("Conjure stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
