"""Recorder configuration: defaults, YAML loading, per-camera settings.

Search order for the config file:
  1. ``--config PATH`` on the command line
  2. environment variable ``MOUSE_RIG_CONFIG``
  3. ``rig/config/recorder.local.yaml`` (this computer's settings; not in git,
     the install scripts copy it from recorder.yaml)
  4. ``rig/config/recorder.yaml`` in this repository (the template)
  5. built-in defaults (below)
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

from ..cameras.base import CameraSettings

REPO_CONFIG = Path(__file__).resolve().parents[3] / "config" / "recorder.yaml"
LOCAL_CONFIG = REPO_CONFIG.with_name("recorder.local.yaml")

DEFAULTS: dict = {
    "server": {"host": "127.0.0.1", "port": 8765, "open_browser": True},
    "recording": {
        "output_dir": "~/MouseRecordings",
        "clip_seconds": 60,
        "container": "mp4",          # mp4 (fragmented, crash-safe) | mkv
        "codec": "h264",             # h264 | h265
        "encoder": "auto",           # auto | libx264 | h264_nvenc | h264_videotoolbox | h264_qsv | ...
        "quality": "balanced",       # high | balanced | small
        "x264_preset": "veryfast",
        "min_free_gb": 10,
        "max_minutes": 0,            # 0 = no limit
        "queue_seconds": 3,          # frames buffered per camera while the encoder catches up
    },
    "cameras": {
        "backends": ["mvs"],
        "mvs_python_path": None,
        "arduino_port": "auto",      # trigger Arduino: auto | "COM3" | "/dev/ttyACM0" | none
        "order": [],                 # serial numbers -> cam-1, cam-2, ...
        "default": {
            "fps": 60,
            "exposure_us": 4000,
            "gain_db": 0,
            "trigger": "free",       # free | line0
            "pixel_format": "auto",
        },
        "overrides": {},             # {serial: {exposure_us: ..., label: ..., enabled: false}}
        "synthetic": {"count": 2, "width": 1440, "height": 1080},
        "opencv": {"indices": [0]},
    },
}


def _merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def config_path(explicit: str | None = None) -> Path | None:
    for candidate in (explicit, os.environ.get("MOUSE_RIG_CONFIG")):
        if candidate:
            p = Path(os.path.expanduser(candidate))
            if not p.is_file():
                raise FileNotFoundError(f"config file not found: {p}")
            return p
    for candidate in (LOCAL_CONFIG, REPO_CONFIG):
        if candidate.is_file():
            return candidate
    return None


def load_config(explicit: str | None = None, demo: bool = False) -> dict:
    path = config_path(explicit)
    loaded = {}
    if path:
        with open(path, encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
    cfg = _merge(DEFAULTS, loaded)
    if demo:
        cfg["cameras"]["backends"] = ["synthetic"]
    cfg["_path"] = str(path) if path else None
    _validate(cfg)
    return cfg


def _validate(cfg: dict) -> None:
    rec = cfg["recording"]
    if rec["container"] not in ("mp4", "mkv"):
        raise ValueError("recording.container must be mp4 or mkv")
    if rec["codec"] not in ("h264", "h265"):
        raise ValueError("recording.codec must be h264 or h265")
    if rec["quality"] not in ("high", "balanced", "small"):
        raise ValueError("recording.quality must be high, balanced or small")
    if float(rec["clip_seconds"]) <= 0:
        raise ValueError("recording.clip_seconds must be > 0")
    trig = str(cfg["cameras"]["default"].get("trigger"))
    if trig not in ("free", "line0"):
        raise ValueError("cameras.default.trigger must be 'free' or 'line0' (quote it in YAML)")


def output_dir(cfg: dict) -> Path:
    return Path(os.path.expanduser(str(cfg["recording"]["output_dir"]))).resolve()


def settings_for(cfg: dict, serial: str) -> CameraSettings:
    merged = dict(cfg["cameras"]["default"])
    merged.update(cfg["cameras"].get("overrides", {}).get(serial, {}) or {})
    fields = CameraSettings().as_dict().keys()
    s = CameraSettings(**{k: v for k, v in merged.items() if k in fields})
    s.trigger = str(s.trigger)
    return s
