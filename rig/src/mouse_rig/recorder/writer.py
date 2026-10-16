"""Per-camera clip writer: queue -> ffmpeg, split into fixed-length clips.

Two ways to cut clips:

* Free-run (``trigger: "free"``): clip k holds the frames with
  ``t0 + k*clip_seconds <= host_time < t0 + (k+1)*clip_seconds``, where ``t0`` is the
  session start that all cameras share.
* Hardware trigger (all cameras ``trigger: "line0"``): every frame carries a shared
  trigger index (see ``sync.py``). Clip k holds the indices
  ``start + k*frames_per_clip ... start + (k+1)*frames_per_clip - 1``. If a camera
  misses an index (a lost frame), the writer repeats the previous image and marks
  the row ``filled=1`` in the CSV. So frame i of clip k is the same trigger pulse in
  every camera, and every camera has the same number of frames in every clip.

In both modes, clip k goes into the folder ``clip-<t0 + k*clip_seconds>`` for every camera.

A timed recording ends exactly on a clip boundary: free-run drops frames from
``end_time`` on, trigger mode drops indices from ``start + max_frames`` on (see
``SyncPlan.window_end``), so a 5-minute recording is exactly five 1-minute clips.

Files written for clip k of camera N::

    <session>/clip-2026-10-16-143105/cam-N.mp4          the video
    <session>/clip-2026-10-16-143105/cam-N.frames.csv   one row per frame (timestamps)

The video is encoded at the nominal frame rate. The CSV keeps the real host and
camera timestamp of every frame, so dropped frames and timing stay visible.
"""
from __future__ import annotations

import csv
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from ..cameras.base import Frame
from .ffmpeg import EncoderProcess
from .sync import SyncPlan

STAMP = "%Y-%m-%d-%H%M%S"


def clip_name(t: float) -> str:
    return "clip-" + datetime.fromtimestamp(t).strftime(STAMP)


class CameraClipWriter:
    def __init__(self, *, cam_index: int, session_dir: Path, t0: float, clip_seconds: float,
                 fps: float, ffmpeg: str, encoder: str, quality: str, container: str,
                 x264_preset: str, queue_frames: int, log_dir: Path, sync: SyncPlan | None = None,
                 end_time: float | None = None):
        self.cam_index = cam_index
        self.session_dir = session_dir
        self.t0 = t0
        self.clip_seconds = float(clip_seconds)
        self.fps = float(fps)
        self.ffmpeg = ffmpeg
        self.encoder = encoder
        self.quality = quality
        self.container = container
        self.x264_preset = x264_preset
        self.log_path = log_dir / f"ffmpeg-cam-{cam_index}.log"
        self.sync = sync
        self.end_time = end_time                         # timed free-run recording: drop frames from here on
        self.max_fill = max(1, int(round(self.fps)))     # fill gaps up to 1 s; a longer gap is a trigger stop
        self._q: queue.Queue = queue.Queue(maxsize=max(10, int(queue_frames)))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"writer-cam-{cam_index}", daemon=True)
        # state for the open clip
        self._clip_k: int | None = None
        self._enc: EncoderProcess | None = None
        self._csv_fh = None
        self._csv = None
        self._frame_in_clip = 0
        self._shape = None
        self._enc_failed_clip: int | None = None
        self._next_index: int | None = None     # trigger index expected next (sync mode)
        self._last_image = None
        # stats
        self.frames_written = 0
        self.frames_dropped = 0            # queue full: the encoder fell behind
        self.frames_filled = 0             # sync mode: copies of the previous image for missing indices
        self.frames_skipped = 0            # sync mode: frames outside the recording window
        self.clips = 0
        self.errors: list[str] = []
        self.current_clip = ""

    # -- public ----------------------------------------------------------------
    def start(self) -> None:
        self._thread.start()

    def submit(self, frame: Frame) -> None:
        try:
            self._q.put_nowait(frame)
        except queue.Full:
            self.frames_dropped += 1

    def stop(self, timeout: float = 120.0) -> None:
        self._stop.set()
        self._thread.join(timeout=timeout)

    def stats(self) -> dict:
        return {
            "frames_written": self.frames_written,
            "frames_dropped": self.frames_dropped,
            "frames_filled": self.frames_filled,
            "queue": self._q.qsize(),
            "clips": self.clips,
            "current_clip": self.current_clip,
            "encoder": self.encoder,
            "errors": self.errors[-5:],
        }

    # -- worker ----------------------------------------------------------------
    def _run(self) -> None:
        try:
            while True:
                try:
                    frame = self._q.get(timeout=0.2)
                except queue.Empty:
                    if self._stop.is_set():
                        break
                    continue
                self._handle(frame)
            self._fill_to_end()
        finally:
            self._close_clip()

    def _handle(self, frame: Frame) -> None:
        if self.sync is None:
            if self.end_time is not None and frame.host_time >= self.end_time:
                self.frames_skipped += 1
                return
            k = max(0, int((frame.host_time - self.t0) // self.clip_seconds))
            self._enter_clip(k, frame.image)
            self._write(frame.image, frame, "", 0)
            return
        idx = frame.extra.get("trigger_index")
        if idx is None:
            self.frames_skipped += 1
            return
        start = self.sync.resolve_start(idx)
        end = self.sync.window_end()
        if idx < start or (end is not None and idx >= end) or (
                self._next_index is not None and idx < self._next_index):
            self.frames_skipped += 1
            return
        expected = start if self._next_index is None else self._next_index
        if idx > expected:
            self._fill(expected, idx, frame.image)
        self._enter_clip((idx - start) // self.sync.frames_per_clip, frame.image)
        self._write(frame.image, frame, idx, 0)
        self._next_index = idx + 1
        self._last_image = frame.image

    def _fill(self, first: int, stop: int, fallback) -> None:
        """Repeat the previous image for the trigger indices first..stop-1 that did not arrive."""
        gap = stop - first
        if gap > self.max_fill:
            self.errors.append(f"no frames for trigger {first}..{stop - 1} ({gap} frames, "
                               f"trigger stopped?); not filled")
            return
        image = self._last_image if self._last_image is not None else fallback
        for idx in range(first, stop):
            self._enter_clip((idx - self.sync.start) // self.sync.frames_per_clip, image)
            self._write(image, None, idx, 1)
        self.frames_filled += gap

    def _fill_to_end(self) -> None:
        """At stop, give every camera the same last trigger index."""
        end = self.sync.window_end() if self.sync is not None else None
        if end is None or self._next_index is None:
            return
        if self._next_index < end:
            self._fill(self._next_index, end, self._last_image)
            self._next_index = end

    def _enter_clip(self, k: int, image) -> None:
        if k != self._clip_k:
            self._close_clip()
            self._open_clip(k, image)

    def _write(self, image, frame: Frame | None, trigger_index, filled: int) -> None:
        if self._shape is not None and image.shape != self._shape:
            image = image[: self._shape[0], : self._shape[1]]
        if self._enc is not None:
            try:
                self._enc.write(image)
            except (BrokenPipeError, OSError, ValueError) as exc:
                self._encoder_failed(f"encoder stopped on frame {self._frame_in_clip}: {exc}")
        self._write_row(frame, trigger_index, filled)

    def _open_clip(self, k: int, image) -> None:
        self._clip_k = k
        start = self.t0 + k * self.clip_seconds
        clip_dir = self.session_dir / clip_name(start)
        clip_dir.mkdir(parents=True, exist_ok=True)
        self.current_clip = clip_dir.name
        h, w = image.shape[:2]
        h, w = h - h % 2, w - w % 2                         # yuv420p needs even sizes
        self._shape = (h, w) + image.shape[2:]
        color = image.ndim == 3
        video = clip_dir / f"cam-{self.cam_index}.{self.container}"
        self._frame_in_clip = 0
        self._enc = None
        if self._enc_failed_clip != k:
            try:
                self._enc = EncoderProcess(self.ffmpeg, video, w, h, color, self.fps, self.encoder,
                                           self.quality, self.container, self.log_path, self.x264_preset)
            except OSError as exc:
                self.errors.append(f"cannot start ffmpeg: {exc}")
        self._csv_fh = open(clip_dir / f"cam-{self.cam_index}.frames.csv", "w", newline="", encoding="utf-8")
        self._csv = csv.writer(self._csv_fh)
        self._csv.writerow(["frame_in_clip", "frame_in_session", "host_time_unix", "host_time_local",
                            "camera_frame_id", "camera_timestamp", "trigger_index", "filled"])
        self.clips += 1

    def _write_row(self, frame: Frame | None, trigger_index, filled: int) -> None:
        if self._csv is None:
            return
        if frame is None:                                   # a filled frame has no camera data
            row = [self._frame_in_clip, self.frames_written, "", "", "", "", trigger_index, filled]
        else:
            local = datetime.fromtimestamp(frame.host_time).isoformat(timespec="milliseconds")
            row = [self._frame_in_clip, self.frames_written, f"{frame.host_time:.6f}", local,
                   frame.frame_id, frame.device_ts, trigger_index, filled]
        self._csv.writerow(row)
        self._frame_in_clip += 1
        self.frames_written += 1
        if self._frame_in_clip % 120 == 0:
            self._csv_fh.flush()

    def _encoder_failed(self, msg: str) -> None:
        self.errors.append(f"{self.current_clip}: {msg} (see {self.log_path.name})")
        if self._enc is not None:
            self._enc.close(timeout=5)
        self._enc = None
        self._enc_failed_clip = self._clip_k     # try again at the next clip

    def _close_clip(self) -> None:
        if self._enc is not None:
            code = self._enc.close()
            if code != 0:
                self.errors.append(f"{self.current_clip}: ffmpeg exit code {code} (see {self.log_path.name})")
            self._enc = None
        if self._csv_fh is not None:
            self._csv_fh.close()
            self._csv_fh = None
            self._csv = None
