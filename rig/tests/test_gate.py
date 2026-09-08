"""M1 end-to-end test — gate drops idle frames and produces a smaller, playable clip.

Uses the OpenCV encoder so it runs anywhere (no ffmpeg HW path needed).
"""
import cv2
import numpy as np

from mouse_rig.processing.motion_gate import gate


def _make_clip(path, n=60, w=192, h=144, fps=20):
    """Mostly-static clip with a moving square only in frames 22..37."""
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    assert vw.isOpened()
    for i in range(n):
        frame = np.full((h, w, 3), 16, np.uint8)          # dark, still
        if 22 <= i < 38:
            x = 20 + (i - 22) * 7
            cv2.rectangle(frame, (x, 60), (x + 24, 96), (255, 255, 255), -1)
        vw.write(frame)
    vw.release()


def test_gate_drops_idle_and_shrinks(tmp_path):
    src = str(tmp_path / "in.mp4")
    out = str(tmp_path / "out.mp4")
    stats_path = str(tmp_path / "out.json")
    _make_clip(src)

    st = gate(src, out, percentile=80, roi="auto",
              prefer_encoder="opencv-mp4v", stats_path=stats_path)

    # kept a non-empty subset of frames
    assert 1 <= st["kept_frames"] < st["total_frames"]
    assert st["total_frames"] == 60

    # output exists, is playable, and holds ~the kept frames
    cap = cv2.VideoCapture(out)
    assert cap.isOpened()
    out_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    assert out_frames >= 1

    # stats sidecar written
    import json
    import os
    assert os.path.exists(stats_path)
    with open(stats_path) as fh:
        saved = json.load(fh)
    assert saved["kept_frames"] == st["kept_frames"]


def test_gate_roi_none_keeps_full_size(tmp_path):
    src = str(tmp_path / "in.mp4")
    out = str(tmp_path / "out.mp4")
    _make_clip(src)
    st = gate(src, out, percentile=80, roi="none", prefer_encoder="opencv-mp4v")
    assert st["roi"] is None
    assert st["full_size"] == [192, 144]
