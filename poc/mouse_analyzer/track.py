"""ByteTrack wrapper producing stable per-mouse track IDs."""
from __future__ import annotations

import numpy as np
import supervision as sv


class MouseTracker:
    def __init__(self, fps: float = 30.0) -> None:
        # Lenient thresholds: mice are small/low-confidence and can occlude.
        self.tracker = sv.ByteTrack(
            track_activation_threshold=0.1,
            lost_track_buffer=int(2 * fps),  # ~2s memory through merge/occlusion
            minimum_matching_threshold=0.7,
            frame_rate=int(round(fps)),
        )

    def update(
        self, xyxy: np.ndarray, conf: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return (xyxy, confidence, tracker_id) for tracked detections."""
        if len(xyxy) == 0:
            dets = sv.Detections.empty()
        else:
            dets = sv.Detections(xyxy=xyxy, confidence=conf)
        tracked = self.tracker.update_with_detections(dets)
        if len(tracked) == 0:
            return (
                np.empty((0, 4), np.float32),
                np.empty((0,), np.float32),
                np.empty((0,), np.int64),
            )
        return tracked.xyxy, tracked.confidence, tracked.tracker_id
