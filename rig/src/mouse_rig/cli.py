"""`mouse-rig` command-line entrypoint.

    mouse-rig serve [--demo]              # recorder web UI: preview + one-click recording
    mouse-rig cameras [--demo]            # list the cameras this computer can see
    mouse-rig record --seconds N [--demo] # record without the web UI
    mouse-rig check [SESSION] [--decode]  # frames per camera per clip
    mouse-rig report [--json]             # what can this machine do?
    mouse-rig gate VIDEO [-o OUT]         # drop idle frames + crop + re-encode
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .commands import gate as gate_cmd
from .commands import recorder as recorder_cmd
from .commands import report as report_cmd


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mouse-rig",
        description="Multi-camera mouse nose-scratch rig — platform-neutral tools.",
    )
    p.add_argument("--version", action="version", version=f"mouse-rig {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    recorder_cmd.add_parsers(sub)
    recorder_cmd.add_check_parser(sub)
    report_cmd.add_parser(sub)
    gate_cmd.add_parser(sub)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
