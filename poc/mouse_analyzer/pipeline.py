"""End-to-end pipeline: detect -> track -> motion-gate -> LLM confirm -> render.

Passes over the video:
  A) Detect + track every frame; record boxes per frame and motion energy.
  B) From motion energy, derive candidate scratch windows per track.
  C) For each candidate window, sample frames, crop the mouse, ask the LLM.
  D) Render annotated video using boxes + confirmed scratch intervals.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .annotate import draw_box, draw_hud
from .detect import build_detector
from .scratch_motion import MotionScorer, _crop_gray  # noqa: F401 (crop reuse)
from .track import MouseTracker


@dataclass
class Args:
    video: str
    output: str
    report: str
    detector: str = "blob"
    prompts: list[str] | None = None
    conf: float = 0.02
    max_mice: int = 4
    stride: int = 1
    use_llm: bool = True
    llm_model: str = "claude-haiku-4-5-20251001"
    max_llm_calls: int = 40
    motion_percentile: float = 90.0
    min_energy: float = 4.0
    samples_per_window: int = 6
    crop_pad: float = 0.35
    api_key: str | None = None


# ---- frame-level detection record -------------------------------------------
@dataclass
class FrameDets:
    xyxy: list[list[float]] = field(default_factory=list)
    conf: list[float] = field(default_factory=list)
    tids: list[int] = field(default_factory=list)


def _pad_crop(frame: np.ndarray, xyxy, pad: float) -> np.ndarray | None:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = xyxy
    bw, bh = x2 - x1, y2 - y1
    x1 = int(max(0, x1 - pad * bw)); y1 = int(max(0, y1 - pad * bh))
    x2 = int(min(w, x2 + pad * bw)); y2 = int(min(h, y2 + pad * bh))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    return frame[y1:y2, x1:x2].copy()


def _box_at(per_frame: dict[int, FrameDets], frame_idx: int, tid: int):
    fd = per_frame.get(frame_idx)
    if not fd:
        return None
    for i, t in enumerate(fd.tids):
        if t == tid:
            return fd.xyxy[i]
    return None


def run(args: Args) -> dict:
    video = Path(args.video)
    if not video.exists():
        raise FileNotFoundError(video)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    detector = build_detector(
        args.detector, args.prompts, args.conf,
        video=str(video), top_k=args.max_mice,
    )
    tracker = MouseTracker(fps=fps)
    motion = MotionScorer()
    per_frame: dict[int, FrameDets] = {}

    # ---- Pass A: detect + track + motion -----------------------------------
    print(f"[A] detect+track {total} frames ({args.detector})...")
    idx = -1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        if args.stride > 1 and idx % args.stride != 0:
            continue
        xyxy, conf = detector(frame)
        txyxy, tconf, tids = tracker.update(xyxy, conf)
        fd = FrameDets()
        for b, c, t in zip(txyxy, tconf, tids):
            fd.xyxy.append([float(v) for v in b])
            fd.conf.append(float(c))
            fd.tids.append(int(t))
            motion.update(idx, frame, int(t), b)
        per_frame[idx] = fd
        if idx % 50 == 0:
            print(f"    frame {idx}/{total}  tracks={sorted(set(fd.tids))}")
    cap.release()

    track_ids = sorted({t for fd in per_frame.values() for t in fd.tids})
    print(f"[A] done. tracks found: {track_ids}")

    # ---- Pass B: candidate windows -----------------------------------------
    candidates = motion.candidate_windows(
        percentile=args.motion_percentile, min_energy=args.min_energy
    )
    n_cand = sum(len(v) for v in candidates.values())
    print(f"[B] candidate scratch windows: {n_cand} across {len(candidates)} tracks")

    # ---- Pass C: LLM confirm ------------------------------------------------
    confirmer = None
    if args.use_llm and args.api_key and n_cand:
        from .scratch_llm import LlmScratchConfirmer

        confirmer = LlmScratchConfirmer(args.api_key, model=args.llm_model)
        print(f"[C] confirming with {args.llm_model}...")
    elif args.use_llm and not args.api_key:
        print("[C] no API key -> skipping LLM; reporting motion candidates only")

    scratch_intervals: dict[int, list[dict]] = {tid: [] for tid in track_ids}
    calls = 0
    cap = cv2.VideoCapture(str(video))
    for tid, windows in candidates.items():
        for (s, e) in windows:
            verdict = {"scratching": True, "confidence": 0.0,
                       "reason": "motion candidate (LLM disabled)"}
            if confirmer and calls < args.max_llm_calls:
                sample_idx = np.linspace(
                    s, e, num=min(args.samples_per_window, e - s + 1)
                ).round().astype(int)
                crops, labels = [], []
                for fi in sample_idx:
                    box = _box_at(per_frame, int(fi), tid)
                    if box is None:
                        continue
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(fi))
                    ok, fr = cap.read()
                    if not ok:
                        continue
                    crop = _pad_crop(fr, box, args.crop_pad)
                    if crop is not None:
                        crops.append(crop)
                        labels.append(f"f{int(fi)}")
                if len(crops) >= 2:
                    verdict = confirmer.confirm(crops, labels)
                    calls += 1
                    print(f"    mouse {tid} [{s}-{e}] -> "
                          f"{verdict['scratching']} ({verdict['confidence']:.2f})")
            if verdict["scratching"]:
                scratch_intervals[tid].append(
                    {"start": int(s), "end": int(e), **verdict}
                )
    cap.release()
    print(f"[C] LLM calls: {calls}")

    # frame -> set of scratching track ids
    scratch_frames: dict[int, set[int]] = {}
    for tid, ivs in scratch_intervals.items():
        for iv in ivs:
            for f in range(iv["start"], iv["end"] + 1):
                scratch_frames.setdefault(f, set()).add(tid)

    # ---- Pass D: render -----------------------------------------------------
    print("[D] rendering annotated video...")
    cap = cv2.VideoCapture(str(video))
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(args.output, fourcc, fps, (width, height))
    idx = -1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx += 1
        fd = per_frame.get(idx)
        scr = scratch_frames.get(idx, set())
        if fd:
            for b, c, t in zip(fd.xyxy, fd.conf, fd.tids):
                draw_box(frame, np.array(b), t, scratching=(t in scr), conf=c)
        draw_hud(frame, idx, len(scr))
        writer.write(frame)
    cap.release()
    writer.release()

    report = {
        "video": str(video),
        "fps": fps,
        "frames": total,
        "detector": args.detector,
        "llm_model": args.llm_model if confirmer else None,
        "llm_calls": calls,
        "tracks": track_ids,
        "scratching": {
            str(tid): [
                {**iv,
                 "start_sec": round(iv["start"] / fps, 2),
                 "end_sec": round(iv["end"] / fps, 2)}
                for iv in ivs
            ]
            for tid, ivs in scratch_intervals.items() if ivs
        },
    }
    Path(args.report).write_text(json.dumps(report, indent=2))
    print(f"[done] video -> {args.output}\n[done] report -> {args.report}")
    return report
