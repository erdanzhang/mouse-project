"""ffmpeg discovery, encoder selection, and one encoder process per video file.

ffmpeg search order: env ``MOUSE_RIG_FFMPEG`` -> ``ffmpeg`` on PATH -> the binary
bundled with the ``imageio-ffmpeg`` package (installed with this project, so a
working ffmpeg always exists on Windows, macOS and Linux).

``pick_encoder()`` tests each candidate with a real 15-frame encode and keeps the
first one that works. A listed-but-broken encoder (for example ``h264_nvenc`` on
a PC without an NVIDIA GPU) is skipped automatically.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# quality presets: high / balanced / small
_QUALITY = {
    "libx264": ("-crf", (18, 21, 25)),
    "h264_nvenc": ("-cq", (19, 22, 26)),
    "h264_qsv": ("-global_quality", (20, 23, 27)),
    "h264_videotoolbox": ("-q:v", (70, 66, 60)),
    "libx265": ("-crf", (20, 23, 27)),
    "hevc_nvenc": ("-cq", (21, 24, 28)),
    "hevc_qsv": ("-global_quality", (22, 25, 29)),
    "hevc_videotoolbox": ("-q:v", (68, 62, 55)),
    "mpeg4": ("-q:v", (2, 4, 6)),
}
_QIDX = {"high": 0, "balanced": 1, "small": 2}


def find_ffmpeg() -> str | None:
    env = os.environ.get("MOUSE_RIG_FFMPEG")
    if env and Path(env).is_file():
        return env
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


@lru_cache(maxsize=4)
def available_encoders(ffmpeg: str) -> frozenset:
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True,
                             timeout=30, creationflags=_NO_WINDOW).stdout
    except Exception:
        return frozenset()
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] == "V":
            names.add(parts[1])
    return frozenset(names)


def candidates(codec: str) -> list[str]:
    if codec == "h265":
        hw = ["hevc_videotoolbox"] if sys.platform == "darwin" else ["hevc_nvenc", "hevc_qsv"]
        return hw + ["libx265"]
    hw = ["h264_videotoolbox"] if sys.platform == "darwin" else ["h264_nvenc", "h264_qsv"]
    return hw + ["libx264", "mpeg4"]


def encoder_args(name: str, quality: str, fps: float, x264_preset: str = "veryfast") -> list[str]:
    gop = str(max(1, int(round(fps))))           # one keyframe per second: fast seeking
    flag, values = _QUALITY.get(name, ("-q:v", (2, 4, 6)))
    q = str(values[_QIDX[quality]])
    args = ["-c:v", name, flag, q, "-g", gop]
    if name == "libx264":
        args += ["-preset", x264_preset]
    elif name == "libx265":
        args += ["-preset", "fast", "-x265-params", "log-level=error"]
    elif name.endswith("_nvenc"):
        args += ["-preset", "p4", "-rc", "vbr", "-b:v", "0"]
    if name in ("libx265", "hevc_nvenc", "hevc_qsv", "hevc_videotoolbox"):
        args += ["-tag:v", "hvc1"]               # plays in QuickTime / Apple apps
    return args


def container_args(container: str) -> list[str]:
    if container == "mp4":
        # fragmented MP4: a file stays readable even if the program stops suddenly
        return ["-movflags", "+frag_keyframe+empty_moov+default_base_moof", "-f", "mp4"]
    return ["-f", "matroska"]


def _test_encoder(ffmpeg: str, name: str) -> bool:
    w, h, n = 640, 480, 15
    frames = np.zeros((n, h, w), np.uint8)
    for i in range(n):
        frames[i, :, (i * 20) % w:] = 128
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "gray",
           "-s", f"{w}x{h}", "-r", "30", "-i", "-", *encoder_args(name, "balanced", 30),
           "-pix_fmt", "yuv420p", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, input=frames.tobytes(), capture_output=True, timeout=60,
                           creationflags=_NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


@dataclass
class EncoderChoice:
    ffmpeg: str
    name: str
    tried: list


@lru_cache(maxsize=8)
def pick_encoder(codec: str = "h264", preferred: str = "auto") -> EncoderChoice:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found. Run: pip install imageio-ffmpeg")
    have = available_encoders(ffmpeg)
    order = candidates(codec) if preferred in (None, "", "auto") else [preferred] + candidates(codec)
    tried = []
    for name in order:
        if name not in have:
            tried.append(f"{name}: not in this ffmpeg build")
            continue
        if _test_encoder(ffmpeg, name):
            return EncoderChoice(ffmpeg=ffmpeg, name=name, tried=tried)
        tried.append(f"{name}: test encode failed")
    raise RuntimeError("no working video encoder: " + "; ".join(tried))


class EncoderProcess:
    """One ffmpeg process that turns raw frames (from stdin) into one video file."""

    def __init__(self, ffmpeg: str, path: Path, width: int, height: int, color: bool, fps: float,
                 encoder: str, quality: str, container: str, log_path: Path, x264_preset: str = "veryfast"):
        self.path = path
        self.encoder = encoder
        self.frames = 0
        self._log = open(log_path, "ab")
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "bgr24" if color else "gray",
               "-s", f"{width}x{height}", "-r", f"{fps:g}", "-i", "-", "-an",
               *encoder_args(encoder, quality, fps, x264_preset), "-pix_fmt", "yuv420p",
               *container_args(container), str(path)]
        self._log.write((" ".join(cmd) + "\n").encode())
        self._log.flush()
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                      stderr=self._log, creationflags=_NO_WINDOW)

    def write(self, image: np.ndarray) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(np.ascontiguousarray(image).data)
        self.frames += 1

    def alive(self) -> bool:
        return self._proc.poll() is None

    def close(self, timeout: float = 60.0) -> int:
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            code = self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            code = -9
        self._log.close()
        return code
