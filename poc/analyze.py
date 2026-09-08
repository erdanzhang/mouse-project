#!/usr/bin/env python3
"""CLI entrypoint for the mouse nose-scratch analyzer.

Examples:
    python analyze.py data/1139_1782741938.mp4
    python analyze.py data/clip.mp4 --detector blob --no-llm
    python analyze.py data/clip.mp4 -o outputs/out.mp4 --stride 2
"""
from __future__ import annotations

import argparse
from pathlib import Path

from mouse_analyzer.config import get_api_key, load_credentials
from mouse_analyzer.pipeline import Args, run


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("video", help="input video path")
    p.add_argument("-o", "--output", help="annotated output video (mp4)")
    p.add_argument("-r", "--report", help="JSON report path")
    p.add_argument("--detector", default="blob",
                   choices=["blob", "yoloworld"],
                   help="blob = classical CV (default, robust on this footage); "
                        "yoloworld = open-vocab (needs a clearer view)")
    p.add_argument("--max-mice", type=int, default=4,
                   help="max mice to keep per frame (blob top-k)")
    p.add_argument("--prompts", nargs="+",
                   help="open-vocab class prompts (yoloworld)")
    p.add_argument("--conf", type=float, default=0.02,
                   help="detector confidence threshold")
    p.add_argument("--stride", type=int, default=1,
                   help="process every Nth frame (speed)")
    p.add_argument("--no-llm", action="store_true",
                   help="skip Claude confirmation; report motion candidates")
    p.add_argument("--llm-model", default="claude-haiku-4-5-20251001")
    p.add_argument("--max-llm-calls", type=int, default=40)
    p.add_argument("--motion-percentile", type=float, default=90.0)
    p.add_argument("--min-energy", type=float, default=4.0)
    p.add_argument("--cred", default=".cred", help="credentials file")
    args = p.parse_args()

    load_credentials(args.cred)

    stem = Path(args.video).stem
    out = args.output or f"outputs/{stem}_annotated.mp4"
    report = args.report or f"outputs/{stem}_report.json"

    run(Args(
        video=args.video,
        output=out,
        report=report,
        detector=args.detector,
        prompts=args.prompts,
        conf=args.conf,
        max_mice=args.max_mice,
        stride=args.stride,
        use_llm=not args.no_llm,
        llm_model=args.llm_model,
        max_llm_calls=args.max_llm_calls,
        motion_percentile=args.motion_percentile,
        min_energy=args.min_energy,
        api_key=get_api_key(),
    ))


if __name__ == "__main__":
    main()
