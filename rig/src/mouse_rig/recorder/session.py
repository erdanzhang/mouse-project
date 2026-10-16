"""One recording session: folder layout, writers, session.json, safety checks.

Folder layout (one folder per session, one sub-folder per clip)::

    <output_dir>/2026-10-16-143005/
        session.json                    settings, cameras (serial -> cam-N), statistics
        logs/ffmpeg-cam-1.log           encoder messages
        clip-2026-10-16-143005/cam-1.mp4, cam-1.frames.csv, cam-2.mp4, ...
        clip-2026-10-16-143105/...      (a new clip every recording.clip_seconds)
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .. import __version__
from .config import output_dir
from .ffmpeg import pick_encoder
from .manager import CameraManager
from .sync import SyncPlan
from .writer import STAMP, CameraClipWriter


class KeepAwake:
    """Stop the computer from sleeping while a recording runs (Windows and macOS)."""

    def __init__(self):
        self._proc = None

    def __enter__(self):
        if sys.platform.startswith("win"):
            import ctypes
            ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
            ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        elif sys.platform == "darwin" and shutil.which("caffeinate"):
            self._proc = subprocess.Popen(["caffeinate", "-i"])
        return self

    def __exit__(self, *exc):
        if sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        elif self._proc is not None:
            self._proc.terminate()


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def _limit_minutes(value) -> float:
    try:
        minutes = float(value or 0)
    except (TypeError, ValueError):
        raise ValueError(f"recording length must be a number of minutes, not {value!r}") from None
    if not 0 <= minutes < float("inf"):           # also rejects NaN
        raise ValueError(f"recording length must be 0 (no limit) or more minutes, not {value!r}")
    return minutes


class RecordingSession:
    """One recording. ``minutes`` > 0 stops it by itself after exactly that long
    (default: ``recording.max_minutes``; 0 = until stopped)."""

    # a timed trigger-mode recording that gets no pulses still stops this long after its end
    LIMIT_GRACE_S = 5.0

    def __init__(self, cfg: dict, manager: CameraManager, minutes: float | None = None):
        self.cfg = cfg
        self.manager = manager
        self.rec = cfg["recording"]
        self.limit_s = 60.0 * _limit_minutes(self.rec.get("max_minutes") if minutes is None else minutes)
        self.limit_reached = False
        self.root = output_dir(cfg)
        self.writers: dict[str, CameraClipWriter] = {}
        self.sync: SyncPlan | None = None     # set when all cameras use the hardware trigger
        self.t0 = 0.0
        self.t_end = 0.0
        self.dir: Path | None = None
        self.state = "idle"             # idle | recording | stopping | stopped
        self.stop_reason = ""
        self.encoder = ""
        self.size_bytes = 0
        self._monitor: threading.Thread | None = None
        self._halt = threading.Event()
        self._awake = KeepAwake()

    # -- start / stop ----------------------------------------------------------
    def start(self) -> Path:
        slots = self.manager.open_slots()
        if not slots:
            raise RuntimeError("no camera is open; check the camera list in the web UI")
        self.root.mkdir(parents=True, exist_ok=True)
        free_gb = shutil.disk_usage(self.root).free / 1e9
        if free_gb < float(self.rec["min_free_gb"]):
            raise RuntimeError(f"only {free_gb:.1f} GB free in {self.root} (min_free_gb={self.rec['min_free_gb']})")
        choice = pick_encoder(self.rec["codec"], str(self.rec["encoder"]))
        self.encoder = choice.name
        self.t0 = time.time()
        name = datetime.fromtimestamp(self.t0).strftime(STAMP)
        self.dir = self.root / name
        n = 2
        while self.dir.exists():
            self.dir = self.root / f"{name}-{n}"
            n += 1
        (self.dir / "logs").mkdir(parents=True)
        clock = self.manager.clock
        if clock is not None:
            # start two pulses after the newest frame: no camera has that pulse yet
            fps = float(slots[0].settings.fps)
            per_clip = max(1, round(float(self.rec["clip_seconds"]) * fps))
            newest = clock.newest
            self.sync = SyncPlan(per_clip, start=None if newest is None else newest + 2,
                                 max_frames=round(self.limit_s * fps) if self.limit_s else None)
        for slot in slots:
            fps = float(slot.settings.fps)
            writer = CameraClipWriter(
                cam_index=slot.index, session_dir=self.dir, t0=self.t0,
                clip_seconds=float(self.rec["clip_seconds"]), fps=fps, ffmpeg=choice.ffmpeg,
                encoder=choice.name, quality=self.rec["quality"], container=self.rec["container"],
                x264_preset=self.rec.get("x264_preset", "veryfast"),
                queue_frames=int(fps * float(self.rec.get("queue_seconds", 3))),
                log_dir=self.dir / "logs", sync=self.sync,
                end_time=self.t0 + self.limit_s if self.limit_s and self.sync is None else None)
            writer.start()
            self.writers[slot.cam_id] = writer
            slot.sink = writer.submit
        self.state = "recording"
        self._awake.__enter__()
        self._write_json()
        self._monitor = threading.Thread(target=self._watch, name="session-monitor", daemon=True)
        self._monitor.start()
        return self.dir

    def stop(self, reason: str = "stopped by user") -> None:
        if self.state != "recording":
            return
        self.state = "stopping"
        self.stop_reason = reason
        self._halt.set()
        clock = self.manager.clock
        if self.sync is not None and clock is not None and clock.newest is not None:
            # end at the same trigger index in every camera: let the newest pulse reach all
            # cameras, then cut after the newest index that any camera delivered
            self.sync.end = clock.newest + 2
            time.sleep(min(0.5, 3 * clock.period + 0.05))
            self.sync.end = min(self.sync.end, clock.newest + 1)
        for slot in self.manager.slots:
            slot.sink = None
        for writer in self.writers.values():
            writer.stop()
        self.t_end = time.time()
        self._awake.__exit__(None, None, None)
        self.size_bytes = _dir_size(self.dir)
        self.state = "stopped"
        self._write_json()

    # -- monitoring ------------------------------------------------------------
    def _limit_done(self) -> bool:
        """True once a timed recording has all its frames."""
        if not self.limit_s:
            return False
        now = time.time()
        if self.sync is not None:
            clock, end = self.manager.clock, self.sync.window_end()
            if clock is not None and clock.newest is not None and end is not None and clock.newest >= end:
                return True                      # a camera already has the first pulse after the end
            return now >= self.t0 + self.limit_s + self.LIMIT_GRACE_S
        return now >= self.t0 + self.limit_s + 0.3   # frames up to end_time have reached the writers

    def _watch(self) -> None:
        min_free = float(self.rec["min_free_gb"])
        next_check = time.time() + 5.0
        while not self._halt.wait(0.2):
            if self._limit_done():
                self.limit_reached = True
                threading.Thread(target=self.stop, args=(f"time limit reached ({self.limit_s / 60:g} min)",),
                                 daemon=True).start()
                return
            if time.time() < next_check:
                continue
            next_check = time.time() + 5.0
            self.size_bytes = _dir_size(self.dir)
            if shutil.disk_usage(self.root).free / 1e9 < min_free:
                threading.Thread(target=self.stop, args=(f"disk almost full (< {min_free} GB free)",),
                                 daemon=True).start()
                return
            self._write_json()

    # -- reporting -------------------------------------------------------------
    def elapsed(self) -> float:
        if self.state == "idle":
            return 0.0
        return (self.t_end or time.time()) - self.t0

    def status(self) -> dict:
        cams = {}
        for slot in self.manager.slots:
            w = self.writers.get(slot.cam_id)
            if w is not None:
                cams[slot.cam_id] = w.stats()
        return {
            "state": self.state,
            "name": self.dir.name if self.dir else "",
            "path": str(self.dir) if self.dir else "",
            "elapsed_s": round(self.elapsed(), 1),
            "limit_s": self.limit_s,
            "limit_reached": self.limit_reached,
            "encoder": self.encoder,
            "size_mb": round(self.size_bytes / 1e6, 1),
            "stop_reason": self.stop_reason,
            "writers": cams,
        }

    def _sync_info(self) -> dict:
        if self.sync is None:
            return {"mode": "free-run", "note": "clips are cut by host time; cameras are not frame-locked"}
        clock = self.manager.clock
        link = self.manager.link
        return {"mode": "hardware trigger (Line0)", **self.sync.as_dict(),
                "aligned_by": ("Arduino gate over USB serial (exact)" if clock and clock.gated
                               else "frame arrival time (no serial link)"),
                "arduino_port": link.port if link is not None else None,
                "measured_trigger_fps": round(1.0 / clock.period, 3) if clock else None,
                "missed_trigger_corrections": clock.corrections if clock else None}

    def _write_json(self) -> None:
        if self.dir is None:
            return
        cameras = {}
        for slot in self.manager.slots:
            w = self.writers.get(slot.cam_id)
            if w is None:
                continue
            img = slot.latest.image if slot.latest is not None else None
            cameras[slot.cam_id] = {
                "serial": slot.info.serial, "model": slot.info.model, "backend": slot.info.backend,
                "label": slot.settings.label or slot.info.name,
                "color": bool(img is not None and img.ndim == 3),
                "width": int(img.shape[1]) if img is not None else None,
                "height": int(img.shape[0]) if img is not None else None,
                "settings": slot.settings.as_dict(),
                "measured_fps": round(slot.fps(), 2),
                "camera_lost_frames": slot.lost_frames,
                **w.stats(),
            }
        doc = {
            "session": self.dir.name,
            "state": self.state,
            "started": datetime.fromtimestamp(self.t0).isoformat(timespec="seconds"),
            "stopped": datetime.fromtimestamp(self.t_end).isoformat(timespec="seconds") if self.t_end else None,
            "stop_reason": self.stop_reason,
            "duration_s": round(self.elapsed(), 1),
            "timed_minutes": self.limit_s / 60 if self.limit_s else None,
            "clip_seconds": self.rec["clip_seconds"],
            "container": self.rec["container"],
            "codec": self.rec["codec"],
            "encoder": self.encoder,
            "quality": self.rec["quality"],
            "sync": self._sync_info(),
            "size_mb": round(self.size_bytes / 1e6, 1),
            "cameras": cameras,
            "host": {"os": platform.platform(), "python": platform.python_version(),
                     "mouse_rig": __version__, "config": self.cfg.get("_path")},
        }
        tmp = self.dir / "session.json.tmp"
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.dir / "session.json")
