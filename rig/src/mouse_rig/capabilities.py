"""Runtime capability probe — the heart of platform-neutrality.

`probe()` reports what THIS machine can do (OS, ffmpeg hardware encoders, torch
device, GenICam camera support) and recommends a video-encoder + compute device.
Everything else in the package asks this module rather than hard-coding a
platform, so the same code runs on a Mac laptop and on the RTX 5070 lab PC.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field

# Encoders we care about, best → most-portable.
_ENCODERS_OF_INTEREST = [
    "hevc_nvenc", "av1_nvenc", "h264_nvenc",        # NVIDIA (RTX 5070)
    "hevc_videotoolbox", "h264_videotoolbox",       # Apple
    "hevc_qsv", "hevc_vaapi",                        # Intel / Linux
    "libx265", "libx264",                            # CPU fallback
]


@dataclass
class Capabilities:
    os: str
    machine: str
    python: str
    ffmpeg: str | None
    ffmpeg_encoders: list[str] = field(default_factory=list)
    torch_installed: bool = False
    torch_version: str | None = None
    torch_device: str | None = None            # cuda | mps | cpu | None
    genicam_available: bool = False
    genicam_note: str = ""
    recommended_encoder: str = "opencv-mp4v"   # value understood by backends.encoder
    recommended_device: str = "cpu"

    def as_dict(self) -> dict:
        return asdict(self)


def _detect_ffmpeg_encoders(ffmpeg: str | None) -> list[str]:
    if not ffmpeg:
        return []
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=20,
        ).stdout
    except Exception:
        return []
    names = set()
    for line in out.splitlines():
        parts = line.split()
        # rows look like: " V....D hevc_nvenc   NVIDIA NVENC hevc encoder"
        if len(parts) >= 2 and parts[0] and parts[0][0] in "VAS":
            names.add(parts[1])
    return [e for e in _ENCODERS_OF_INTEREST if e in names]


def _detect_torch() -> tuple[bool, str | None, str | None]:
    try:
        import torch  # noqa: F401  (optional heavy dep)
    except Exception:
        return False, None, None
    version = getattr(torch, "__version__", "?")
    try:
        if torch.cuda.is_available():
            return True, version, "cuda"
    except Exception:
        pass
    try:
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return True, version, "mps"
    except Exception:
        pass
    return True, version, "cpu"


def _detect_genicam() -> tuple[bool, str]:
    try:
        import harvesters  # noqa: F401
    except Exception:
        return False, "harvesters not installed (pip install -r requirements-capture.txt)"
    cti = os.environ.get("GENICAM_GENTL64_PATH") or os.environ.get("MVCAM_GENTL64_PATH")
    if cti:
        return True, f"GenTL producer path: {cti}"
    return True, ("harvesters installed, but no GenTL .cti producer configured — "
                  "install Hikvision MVS and set GENICAM_GENTL64_PATH")


def _recommend_encoder(encoders: list[str]) -> str:
    for pref in ("hevc_nvenc", "hevc_videotoolbox", "libx265", "libx264"):
        if pref in encoders:
            return pref
    return "opencv-mp4v"


def probe() -> Capabilities:
    ffmpeg = shutil.which("ffmpeg")
    encoders = _detect_ffmpeg_encoders(ffmpeg)
    torch_ok, torch_ver, torch_dev = _detect_torch()
    genicam_ok, genicam_note = _detect_genicam()
    return Capabilities(
        os=platform.system(),
        machine=platform.machine(),
        python=platform.python_version(),
        ffmpeg=ffmpeg,
        ffmpeg_encoders=encoders,
        torch_installed=torch_ok,
        torch_version=torch_ver,
        torch_device=torch_dev,
        genicam_available=genicam_ok,
        genicam_note=genicam_note,
        recommended_encoder=_recommend_encoder(encoders),
        recommended_device=torch_dev or "cpu",
    )


def format_report(caps: Capabilities) -> str:
    def line(label, value):
        return f"  {label:<22} {value}"

    enc = ", ".join(caps.ffmpeg_encoders) or "none found"
    torch_line = (
        f"{caps.torch_device}  (torch {caps.torch_version})"
        if caps.torch_installed else "not installed (fine until M6 / models)"
    )
    rows = [
        "mouse-rig — platform capabilities",
        "─" * 46,
        line("OS / arch", f"{caps.os} / {caps.machine}"),
        line("Python", caps.python),
        line("ffmpeg", caps.ffmpeg or "NOT FOUND (install ffmpeg for HW encode)"),
        line("ffmpeg encoders", enc),
        line("torch device", torch_line),
        line("GenICam cameras", "yes" if caps.genicam_available else "no"),
        line("", caps.genicam_note),
        "─" * 46,
        line("→ encoder", caps.recommended_encoder),
        line("→ compute device", caps.recommended_device),
    ]
    return "\n".join(rows)
