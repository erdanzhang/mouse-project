"""Motion-based candidate detection for scratching.

Scratching shows up as bursts of fast, localized motion (the rhythmic hind-paw
flick near the head) inside an otherwise slowly-moving body. We measure, per
track and per frame, the frame-to-frame intensity change within the mouse's
bounding box, normalized by box size. Frames whose motion energy exceeds an
adaptive (percentile) threshold become candidate scratch frames; contiguous
candidates are merged into windows that the LLM then confirms.

This is a cheap gate, not the final classifier — it favors recall so the LLM
sees every plausible bout while keeping API calls low.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class TrackMotion:
    frames: list[int] = field(default_factory=list)
    energy: list[float] = field(default_factory=list)
    _prev: np.ndarray | None = None


CROP = 96  # normalized crop size for motion comparison


def _crop_gray(frame: np.ndarray, xyxy: np.ndarray) -> np.ndarray | None:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(round(v)) for v in xyxy]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    g = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    return cv2.resize(g, (CROP, CROP), interpolation=cv2.INTER_AREA)


class MotionScorer:
    """Accumulate per-track motion energy across the detection pass."""

    def __init__(self) -> None:
        self.tracks: dict[int, TrackMotion] = {}

    def update(self, frame_idx: int, frame, tid: int, xyxy: np.ndarray) -> None:
        tm = self.tracks.setdefault(tid, TrackMotion())
        crop = _crop_gray(frame, xyxy)
        if crop is None:
            return
        if tm._prev is not None:
            diff = cv2.absdiff(crop, tm._prev).astype(np.float32)
            tm.frames.append(frame_idx)
            tm.energy.append(float(diff.mean()))
        tm._prev = crop

    def candidate_windows(
        self,
        percentile: float = 90.0,
        min_energy: float = 4.0,
        min_len: int = 3,
        merge_gap: int = 5,
    ) -> dict[int, list[tuple[int, int]]]:
        """Return {track_id: [(start_frame, end_frame), ...]} of candidates."""
        out: dict[int, list[tuple[int, int]]] = {}
        for tid, tm in self.tracks.items():
            if len(tm.energy) < min_len:
                continue
            energy = np.array(tm.energy)
            thr = max(min_energy, np.percentile(energy, percentile))
            hot = energy >= thr
            windows: list[tuple[int, int]] = []
            run_start = None
            for i, is_hot in enumerate(hot):
                if is_hot and run_start is None:
                    run_start = i
                elif not is_hot and run_start is not None:
                    windows.append((run_start, i - 1))
                    run_start = None
            if run_start is not None:
                windows.append((run_start, len(hot) - 1))
            # merge windows separated by small gaps, drop tiny ones
            merged: list[tuple[int, int]] = []
            for s, e in windows:
                if merged and tm.frames[s] - merged[-1][1] <= merge_gap:
                    merged[-1] = (merged[-1][0], tm.frames[e])
                else:
                    merged.append((tm.frames[s], tm.frames[e]))
            merged = [(s, e) for s, e in merged if (e - s + 1) >= min_len]
            if merged:
                out[tid] = merged
        return out
