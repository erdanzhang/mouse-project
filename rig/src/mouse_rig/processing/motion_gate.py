"""Key-pixel gate (M1) — keep only the frames (and pixels) that matter.

Two passes over a video file:
  1. Measure per-frame motion energy (mean frame-to-frame change on a downscaled
     grey image) and accumulate a motion mask.
  2. Keep frames whose energy clears an adaptive threshold, grouped into runs;
     optionally crop every kept frame to the global "where motion happens" ROI;
     encode with the best available backend.

A mostly-sleeping cage collapses to the handful of active frames — big storage
and downstream-analysis savings. Pure OpenCV/numpy, so it runs on any OS today.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from ..backends.encoder import best_available_encoder
from ..backends.frame_source import FileSource


@dataclass
class GateStats:
    input: str
    output: str
    total_frames: int
    kept_frames: int
    dropped_frames: int
    kept_pct: float
    fps: float
    threshold: float
    roi: list[int] | None                 # [x, y, w, h] in full-res, or None
    full_size: list[int] = field(default_factory=list)
    input_bytes: int = 0
    output_bytes: int = 0
    size_reduction_pct: float = 0.0
    encoder: str = ""
    segments: list[list[int]] = field(default_factory=list)   # [start, end] frame idx


def _downscaled_gray(frame, width):
    h, w = frame.shape[:2]
    scale = width / float(w)
    small = cv2.resize(frame, (width, max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(g, (5, 5), 0), scale


def _runs_from_mask(keep_flags, min_run, merge_gap):
    """Turn a per-frame boolean array into merged, de-noised [start, end] runs."""
    runs = []
    start = None
    for i, k in enumerate(keep_flags):
        if k and start is None:
            start = i
        elif not k and start is not None:
            runs.append([start, i - 1])
            start = None
    if start is not None:
        runs.append([start, len(keep_flags) - 1])
    # merge runs separated by small gaps
    merged = []
    for s, e in runs:
        if merged and s - merged[-1][1] - 1 <= merge_gap:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    # drop too-short runs
    return [[s, e] for s, e in merged if (e - s + 1) >= min_run]


def gate(
    input_path: str,
    output_path: str,
    *,
    percentile: float = 92.0,
    min_energy: float = 1.0,
    min_run: int = 3,
    merge_gap: int = 6,
    roi: str = "auto",           # "auto" | "none"
    pad: float = 0.08,
    proc_width: int = 320,
    prefer_encoder: str | None = None,
    stats_path: str | None = None,
) -> dict:
    """Run the key-pixel gate on a video file. Returns a stats dict."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(input_path)

    # ---- Pass 1: motion energy + activity mask -----------------------------
    src = FileSource(input_path)
    fps = src.fps
    full_w, full_h = src.size
    energies: list[float] = []
    prev = None
    activity = None
    scale = 1.0
    with src:
        for frame in src:
            small, scale = _downscaled_gray(frame, proc_width)
            if prev is None:
                energies.append(0.0)
            else:
                diff = cv2.absdiff(small, prev)
                energies.append(float(diff.mean()))
                mask = (diff > 18).astype(np.float32)
                activity = mask if activity is None else activity + mask
            prev = small
    total = len(energies)
    if total == 0:
        raise RuntimeError("no frames read from input")

    energies_arr = np.asarray(energies)
    threshold = max(min_energy, float(np.percentile(energies_arr, percentile)))
    keep_flags = energies_arr >= threshold
    segments = _runs_from_mask(keep_flags, min_run, merge_gap)
    keep_set = {i for s, e in segments for i in range(s, e + 1)}

    # ---- global ROI from the activity mask ---------------------------------
    roi_box = None
    if roi == "auto" and activity is not None and total > 1:
        hot = (activity >= max(1.0, 0.02 * total)).astype(np.uint8) * 255
        hot = cv2.dilate(hot, np.ones((5, 5), np.uint8), iterations=2)
        ys, xs = np.where(hot > 0)
        if xs.size and ys.size:
            inv = 1.0 / scale
            x0, x1 = xs.min() * inv, xs.max() * inv
            y0, y1 = ys.min() * inv, ys.max() * inv
            bw, bh = x1 - x0, y1 - y0
            x0 = max(0, int(x0 - pad * bw)); y0 = max(0, int(y0 - pad * bh))
            x1 = min(full_w, int(x1 + pad * bw)); y1 = min(full_h, int(y1 + pad * bh))
            if x1 - x0 >= 16 and y1 - y0 >= 16:
                roi_box = [x0, y0, x1 - x0, y1 - y0]

    out_w = roi_box[2] if roi_box else full_w
    out_h = roi_box[3] if roi_box else full_h

    # ---- Pass 2: write kept frames (cropped to ROI) ------------------------
    enc = best_available_encoder(output_path, (out_w, out_h), fps, prefer=prefer_encoder)
    encoder_name = type(enc).__name__ + (f"/{getattr(enc, 'codec', '')}" if hasattr(enc, "codec") else "")
    written = 0
    src2 = FileSource(input_path)
    with src2, enc:
        idx = -1
        for frame in src2:
            idx += 1
            if idx not in keep_set:
                continue
            if roi_box:
                x, y, w, h = roi_box
                frame = frame[y:y + h, x:x + w]
            enc.write(frame)
            written += 1

    in_bytes = os.path.getsize(input_path)
    out_bytes = os.path.getsize(output_path) if os.path.exists(output_path) else 0
    stats = GateStats(
        input=input_path,
        output=output_path,
        total_frames=total,
        kept_frames=written,
        dropped_frames=total - written,
        kept_pct=round(100.0 * written / total, 1),
        fps=round(fps, 3),
        threshold=round(threshold, 3),
        roi=roi_box,
        full_size=[full_w, full_h],
        input_bytes=in_bytes,
        output_bytes=out_bytes,
        size_reduction_pct=round(100.0 * (1 - out_bytes / in_bytes), 1) if in_bytes else 0.0,
        encoder=encoder_name,
        segments=segments,
    )
    result = asdict(stats)
    if stats_path:
        with open(stats_path, "w") as fh:
            json.dump(result, fh, indent=2)
    return result
