"""Draw tracking + scratching annotations onto frames."""
from __future__ import annotations

import cv2
import numpy as np

# Distinct BGR colors cycled per track id for normal (non-scratching) boxes.
_PALETTE = [
    (0, 200, 0), (0, 180, 255), (255, 160, 0),
    (200, 0, 200), (0, 255, 255), (255, 80, 80),
]
SCRATCH_COLOR = (0, 0, 255)  # red


def track_color(tid: int) -> tuple[int, int, int]:
    return _PALETTE[tid % len(_PALETTE)]


def draw_box(
    frame: np.ndarray,
    xyxy: np.ndarray,
    tid: int,
    scratching: bool,
    conf: float | None = None,
) -> None:
    x1, y1, x2, y2 = [int(round(v)) for v in xyxy]
    color = SCRATCH_COLOR if scratching else track_color(tid)
    thickness = 3 if scratching else 2
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
    label = f"mouse {tid}"
    if scratching:
        label += " - SCRATCHING"
    elif conf is not None:
        label += f" {conf:.2f}"
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    cv2.rectangle(frame, (x1, y1 - th - 8), (x1 + tw + 6, y1), color, -1)
    cv2.putText(
        frame, label, (x1 + 3, y1 - 5),
        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA,
    )


def draw_hud(frame: np.ndarray, frame_idx: int, n_scratching: int) -> None:
    txt = f"frame {frame_idx}"
    if n_scratching:
        txt += f"  |  {n_scratching} scratching"
    cv2.putText(
        frame, txt, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
        (255, 255, 255), 2, cv2.LINE_AA,
    )
