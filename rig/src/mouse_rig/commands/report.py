"""`mouse-rig report` — print what this machine can do (M0)."""
from __future__ import annotations

import json

from ..capabilities import format_report, probe


def add_parser(subparsers):
    p = subparsers.add_parser("report", help="show platform capabilities")
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p.set_defaults(func=run)
    return p


def run(args):
    caps = probe()
    if args.json:
        print(json.dumps(caps.as_dict(), indent=2))
    else:
        print(format_report(caps))
    return 0
