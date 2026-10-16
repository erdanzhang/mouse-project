"""Recorder end-to-end tests with synthetic cameras (no hardware needed).

They check the folder layout, clip splitting, per-frame CSV, session.json, and that
every clip is a readable video with the expected number of frames.
"""
import csv
import json
import re
import time

import cv2
import numpy as np
import pytest

from mouse_rig.cameras import pixel
from mouse_rig.recorder import CameraManager, RecordingSession, load_config
from mouse_rig.recorder.ffmpeg import find_ffmpeg, pick_encoder

FPS = 30
CLIP_S = 2


def _cfg(tmp_path, **rec):
    cfg = load_config(demo=True)
    cfg["recording"].update(output_dir=str(tmp_path), clip_seconds=CLIP_S, min_free_gb=0.1, **rec)
    cfg["cameras"]["synthetic"].update(count=2, width=640, height=480)
    cfg["cameras"]["default"]["fps"] = FPS
    return cfg


def _record(cfg, seconds):
    mgr = CameraManager(cfg)
    mgr.open_all()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not all(s["state"] == "ok" for s in mgr.status()):
            time.sleep(0.1)
        session = RecordingSession(cfg, mgr)
        path = session.start()
        time.sleep(seconds)
        session.stop()
        return path, session
    finally:
        mgr.close_all()


def _count_frames(path):
    cap = cv2.VideoCapture(str(path))
    n = 0
    while cap.read()[0]:
        n += 1
    cap.release()
    return n


def test_ffmpeg_and_encoder_available():
    assert find_ffmpeg()
    assert pick_encoder("h264", "auto").name


def test_folder_layout_and_clip_split(tmp_path):
    path, session = _record(_cfg(tmp_path), seconds=CLIP_S * 2 + 1.0)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}-\d{6}", path.name)
    clips = sorted(p for p in path.iterdir() if p.is_dir() and p.name.startswith("clip-"))
    assert len(clips) >= 3                         # 2 full clips + 1 partial
    for clip in clips:
        assert re.fullmatch(r"clip-\d{4}-\d{2}-\d{2}-\d{6}", clip.name)
        for cam in (1, 2):
            assert (clip / f"cam-{cam}.mp4").stat().st_size > 0
            assert (clip / f"cam-{cam}.frames.csv").exists()
    # full clips hold ~CLIP_S * FPS frames, and both cameras hold the same count
    for clip in clips[:2]:
        n1, n2 = (_count_frames(clip / f"cam-{c}.mp4") for c in (1, 2))
        assert abs(n1 - CLIP_S * FPS) <= 3, (clip.name, n1)
        assert abs(n1 - n2) <= 2
    # the first clip folder carries the session start time
    assert clips[0].name == "clip-" + path.name


def test_frames_csv_matches_video(tmp_path):
    path, _ = _record(_cfg(tmp_path), seconds=CLIP_S + 0.5)
    clip = sorted(p for p in path.iterdir() if p.name.startswith("clip-"))[0]
    with open(clip / "cam-1.frames.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0].keys() >= {"frame_in_clip", "host_time_unix", "camera_frame_id"}
    assert len(rows) == _count_frames(clip / "cam-1.mp4")
    times = [float(r["host_time_unix"]) for r in rows]
    assert all(b >= a for a, b in zip(times, times[1:]))


def test_session_json(tmp_path):
    path, session = _record(_cfg(tmp_path), seconds=1.5)
    meta = json.loads((path / "session.json").read_text(encoding="utf-8"))
    assert meta["state"] == "stopped"
    assert set(meta["cameras"]) == {"cam-1", "cam-2"}
    for cam in meta["cameras"].values():
        assert cam["serial"].startswith("SYN")
        assert cam["frames_written"] > 0
        assert cam["frames_dropped"] == 0
        assert cam["errors"] == []


def test_mkv_container(tmp_path):
    path, _ = _record(_cfg(tmp_path, container="mkv"), seconds=1.0)
    files = list(path.rglob("cam-1.mkv"))
    assert files and _count_frames(files[0]) > 10


@pytest.mark.parametrize("ptype,shape", [
    (pixel.MONO8, (4, 6)), (pixel.BAYER_RG8, (4, 6, 3)), (pixel.RGB8, (4, 6, 3)), (pixel.BGR8, (4, 6, 3)),
])
def test_pixel_conversion(ptype, shape):
    w, h = 6, 4
    nbytes = w * h * (3 if ptype in (pixel.RGB8, pixel.BGR8) else 1)
    img = pixel.to_image(bytes(range(nbytes)), w, h, ptype)
    assert img.shape == shape and img.dtype == np.uint8


def test_rgb_is_converted_to_bgr():
    img = pixel.to_image(bytes([10, 20, 30] * 4), 2, 2, pixel.RGB8)
    assert tuple(img[0, 0]) == (30, 20, 10)
