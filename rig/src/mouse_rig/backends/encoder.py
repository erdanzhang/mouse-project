"""Video encoders — abstract how frames are written.

`best_available_encoder()` asks the capability probe and picks NVENC (RTX 5070),
VideoToolbox (Apple), or x265; if ffmpeg is missing it falls back to OpenCV's
mp4v writer so encoding always works somewhere. All encoders take BGR uint8
frames of a fixed size.
"""
from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod

import cv2
import numpy as np


def _even(n: int) -> int:
    return n - (n % 2)


class Encoder(ABC):
    @abstractmethod
    def write(self, frame_bgr: np.ndarray) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FfmpegEncoder(Encoder):
    """Pipe raw BGR frames to ffmpeg; codec selects the hardware/software path."""

    def __init__(self, path, size, fps, codec="libx265", quality=28, ffmpeg=None):
        self.ffmpeg = ffmpeg or shutil.which("ffmpeg")
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg not found")
        w, h = _even(size[0]), _even(size[1])
        self.size = (w, h)
        self.codec = codec
        # Rate control differs per encoder family.
        if codec.startswith("lib"):
            qflag = ["-crf", str(quality)]                 # x264/x265
        elif "nvenc" in codec:
            qflag = ["-rc", "vbr", "-cq", str(quality)]    # NVIDIA
        elif "videotoolbox" in codec:
            qflag = ["-q:v", "55"]                         # Apple constant-quality
        else:
            qflag = []                                     # let ffmpeg default
        cmd = [
            self.ffmpeg, "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "bgr24",
            "-s", f"{w}x{h}", "-r", f"{fps:.4f}", "-i", "-",
            "-an", "-c:v", codec, "-pix_fmt", "yuv420p", *qflag, path,
        ]
        self._p = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    def write(self, frame_bgr):
        if (frame_bgr.shape[1], frame_bgr.shape[0]) != self.size:
            frame_bgr = cv2.resize(frame_bgr, self.size)
        assert self._p.stdin is not None
        self._p.stdin.write(np.ascontiguousarray(frame_bgr).tobytes())

    def close(self):
        if self._p.stdin:
            try:
                self._p.stdin.close()
            except Exception:
                pass
        self._p.wait()


class OpenCVEncoder(Encoder):
    """Portable fallback using cv2.VideoWriter (mp4v). No ffmpeg required."""

    def __init__(self, path, size, fps, fourcc="mp4v"):
        w, h = _even(size[0]), _even(size[1])
        self.size = (w, h)
        self._w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*fourcc), float(fps), (w, h))
        if not self._w.isOpened():
            raise RuntimeError(f"cv2.VideoWriter could not open {path!r}")

    def write(self, frame_bgr):
        if (frame_bgr.shape[1], frame_bgr.shape[0]) != self.size:
            frame_bgr = cv2.resize(frame_bgr, self.size)
        self._w.write(frame_bgr)

    def close(self):
        self._w.release()


def best_available_encoder(path, size, fps, *, caps=None, quality=28, prefer=None) -> Encoder:
    """Choose an encoder from the capability probe (or `prefer` override)."""
    from ..capabilities import probe

    caps = caps or probe()
    codec = prefer or caps.recommended_encoder
    if codec in ("opencv-mp4v", "opencv"):
        return OpenCVEncoder(path, size, fps)
    try:
        return FfmpegEncoder(path, size, fps, codec=codec, quality=quality,
                             ffmpeg=caps.ffmpeg)
    except Exception:
        # Never fail to encode just because a HW path is unavailable.
        return OpenCVEncoder(path, size, fps)
