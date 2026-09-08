"""`mouse-rig gate` — key-pixel filter a video (M1)."""
from __future__ import annotations

import os


def add_parser(subparsers):
    p = subparsers.add_parser("gate", help="drop idle frames + crop ROI + re-encode")
    p.add_argument("input", help="input video (file path or file:PATH)")
    p.add_argument("-o", "--output", help="output video (default: <stem>_gated.mp4)")
    p.add_argument("--stats", help="write stats JSON here (default: alongside output)")
    p.add_argument("--percentile", type=float, default=92.0,
                   help="motion percentile kept as active (lower = keep more)")
    p.add_argument("--roi", choices=["auto", "none"], default="auto",
                   help="crop to the global motion region, or keep full frame")
    p.add_argument("--encoder", default=None,
                   help="force an encoder (e.g. hevc_videotoolbox, hevc_nvenc, "
                        "libx265, opencv-mp4v); default = auto-detect")
    p.set_defaults(func=run)
    return p


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def run(args):
    from ..processing.motion_gate import gate

    src = args.input[5:] if args.input.startswith("file:") else args.input
    stem = os.path.splitext(os.path.basename(src))[0]
    out = args.output or f"{stem}_gated.mp4"
    stats_path = args.stats or (os.path.splitext(out)[0] + ".json")

    st = gate(
        src, out,
        percentile=args.percentile,
        roi=args.roi,
        prefer_encoder=args.encoder,
        stats_path=stats_path,
    )

    roi = st["roi"]
    roi_str = f"{roi[2]}x{roi[3]} @({roi[0]},{roi[1]})" if roi else "full frame"
    print("key-pixel gate")
    print("─" * 46)
    print(f"  input           {st['input']}  ({_fmt_bytes(st['input_bytes'])})")
    print(f"  output          {st['output']}  ({_fmt_bytes(st['output_bytes'])})")
    print(f"  encoder         {st['encoder']}")
    print(f"  frames kept     {st['kept_frames']} / {st['total_frames']}  ({st['kept_pct']}%)")
    print(f"  active segments {len(st['segments'])}")
    print(f"  ROI crop        {roi_str}")
    print(f"  motion thresh   {st['threshold']}")
    print("─" * 46)
    print(f"  → file size cut {st['size_reduction_pct']}%   (stats: {stats_path})")
    return 0
