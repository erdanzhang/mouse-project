"""`mouse-rig` command-line entrypoint.

    mouse-rig report [--json]        # M0 — what can this machine do?
    mouse-rig gate VIDEO [-o OUT]    # M1 — drop idle frames + crop + re-encode
"""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .commands import gate as gate_cmd
from .commands import report as report_cmd


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mouse-rig",
        description="Multi-camera mouse nose-scratch rig — platform-neutral tools.",
    )
    p.add_argument("--version", action="version", version=f"mouse-rig {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    report_cmd.add_parser(sub)
    gate_cmd.add_parser(sub)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
