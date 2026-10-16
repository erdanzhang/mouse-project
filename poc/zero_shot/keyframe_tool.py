"""Frame sampling helper for zero-shot nose-rubbing pre-screening.

A multimodal agent drives this tool: it scans coarse contact sheets, zooms into
candidates with a dense cropped burst, then cuts a scored 10-15 s clip per event.

  overview VIDEO [--start S] [--end E] [--step 2] [--cols 3] [--rows 2] [--crop x,y,w,h]
  burst    VIDEO --t T [--dur 3] [--fps 8] [--crop x,y,w,h] [--cols 6]
  clip     VIDEO --t T --score {4,5} --bbox x,y,w,h [--end T2] [--before 4] [--dur 12] [--note TEXT]

Crop coordinates are in original-video pixels. Only needs ffmpeg + Pillow.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_ROOT = Path("data/zero-shot")
WORK_DIR = OUT_ROOT / "_work"
SHEET_WIDTH = 1560  # close to the longest edge a vision model keeps without downscaling


def _font(size: int):
    for path in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def _extract(video: Path, start: float, dur: float, fps: float, crop: str | None, dest: Path) -> list[Path]:
    filters = [f"fps={fps}"]
    if crop:
        x, y, w, h = (int(v) for v in crop.split(","))
        filters.append(f"crop={w}:{h}:{x}:{y}")
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(video),
           "-vf", ",".join(filters), "-q:v", "3", str(dest / "f%05d.jpg")]
    subprocess.run(cmd, check=True)
    return sorted(dest.glob("f*.jpg"))


def _sheet(frames: list[Path], stamps: list[float], cols: int, out: Path) -> None:
    rows = -(-len(frames) // cols)
    first = Image.open(frames[0])
    tile_w = SHEET_WIDTH // cols
    tile_h = round(first.height * tile_w / first.width)
    sheet = Image.new("RGB", (tile_w * cols, tile_h * rows), "black")
    draw = ImageDraw.Draw(sheet)
    font = _font(max(16, tile_w // 22))
    for i, (frame, ts) in enumerate(zip(frames, stamps)):
        x, y = (i % cols) * tile_w, (i // cols) * tile_h
        sheet.paste(Image.open(frame).resize((tile_w, tile_h), Image.LANCZOS), (x, y))
        label = f"t={ts:.2f}s"
        box = draw.textbbox((x + 6, y + 4), label, font=font)
        draw.rectangle((box[0] - 4, box[1] - 2, box[2] + 4, box[3] + 2), fill="black")
        draw.text((x + 6, y + 4), label, fill="yellow", font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=88)


def cmd_overview(args) -> None:
    video = Path(args.video)
    total = _duration(video)
    start = args.start
    end = min(args.end if args.end is not None else total, total)
    per_sheet = args.cols * args.rows
    with tempfile.TemporaryDirectory() as tmp:
        frames = _extract(video, start, end - start, 1 / args.step, args.crop, Path(tmp))
        stamps = [start + i * args.step for i in range(len(frames))]
        print(f"video={video.name} duration={total:.2f}s frames={len(frames)} step={args.step}s")
        for n in range(0, len(frames), per_sheet):
            out = WORK_DIR / video.stem / f"overview_{stamps[n]:07.2f}.jpg"
            _sheet(frames[n:n + per_sheet], stamps[n:n + per_sheet], args.cols, out)
            print(out.resolve())


def cmd_burst(args) -> None:
    video = Path(args.video)
    start = max(0.0, args.t - args.dur / 2)
    with tempfile.TemporaryDirectory() as tmp:
        frames = _extract(video, start, args.dur, args.fps, args.crop, Path(tmp))
        stamps = [start + i / args.fps for i in range(len(frames))]
        out = WORK_DIR / video.stem / f"burst_{args.t:07.2f}.jpg"
        _sheet(frames, stamps, args.cols, out)
        print(out.resolve())


def cmd_clip(args) -> None:
    video = Path(args.video)
    total = _duration(video)
    dur = min(max(args.dur, 10.0), 15.0)
    start = max(0.0, min(args.t - args.before, total - dur))
    dur = min(dur, total - start)
    event_end = args.end if args.end is not None else min(args.t + 3.0, start + dur)
    out_dir = OUT_ROOT / video.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.t:07.2f}-{args.score}.mp4"
    x, y, w, h = (int(v) for v in args.bbox.split(","))
    # box + label shown from event onset to event end (times relative to clip start), red, 4 px
    enable = f"enable='between(t,{args.t - start:.3f},{event_end - start:.3f})'"
    filters = [f"drawbox=x={x}:y={y}:w={w}:h={h}:color=red@0.9:t=4:{enable}"]
    font = next((f for f in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Menlo.ttc")
                 if Path(f).exists()), None)
    if font:
        label = f"nose rubbing (score {args.score})"
        ty = y - 34 if y >= 34 else y + h + 6
        filters.append(f"drawtext=fontfile={font}:text='{label}':x={x}:y={ty}:fontsize=26:fontcolor=white:"
                       f"box=1:boxcolor=red@0.8:boxborderw=4:{enable}")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(video),
                    "-vf", ",".join(filters),
                    "-an", "-c:v", "libx264", "-crf", "25", "-preset", "fast", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(out)], check=True)
    log = out_dir / "findings.csv"
    new = not log.exists()
    with log.open("a", newline="") as fh:
        writer = csv.writer(fh)
        if new:
            writer.writerow(["event_t_s", "event_end_s", "score", "clip_file", "clip_start_s", "clip_end_s",
                             "bbox_x", "bbox_y", "bbox_w", "bbox_h", "source_video", "note"])
        writer.writerow([f"{args.t:.2f}", f"{event_end:.2f}", args.score, out.name, f"{start:.2f}",
                         f"{start + dur:.2f}", x, y, w, h, str(video), args.note])
    print(out.resolve())


def main() -> None:
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg not found")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("overview")
    p.add_argument("video")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float)
    p.add_argument("--step", type=float, default=2.0)
    p.add_argument("--cols", type=int, default=3)
    p.add_argument("--rows", type=int, default=2)
    p.add_argument("--crop")
    p.set_defaults(func=cmd_overview)

    p = sub.add_parser("burst")
    p.add_argument("video")
    p.add_argument("--t", type=float, required=True)
    p.add_argument("--dur", type=float, default=3.0)
    p.add_argument("--fps", type=float, default=8.0)
    p.add_argument("--crop")
    p.add_argument("--cols", type=int, default=6)
    p.set_defaults(func=cmd_burst)

    p = sub.add_parser("clip")
    p.add_argument("video")
    p.add_argument("--t", type=float, required=True, help="event onset in the original video (s)")
    p.add_argument("--score", type=int, choices=[4, 5], required=True)
    p.add_argument("--bbox", required=True, help="x,y,w,h in original pixels around the rubbing mouse")
    p.add_argument("--end", type=float, help="event end in the original video (s); default t+3")
    p.add_argument("--before", type=float, default=4.0, help="seconds of lead-in before the event")
    p.add_argument("--dur", type=float, default=12.0, help="clip length, clamped to 10-15 s")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_clip)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
