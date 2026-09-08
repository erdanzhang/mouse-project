"""Frame sources — abstract where video comes from.

    open_source("file:clip.mp4")   -> FileSource     (any OS; dev + M1)
    open_source("cam:0")           -> WebcamSource    (any OS; dev)
    open_source("genicam:SERIAL")  -> GenICamSource   (Win/Linux + MVS; M2+)

Develop the whole pipeline on a Mac against a file or webcam; swap to GenICam on
the lab PC without touching downstream code.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod

import cv2
import numpy as np


class FrameSource(ABC):
    """Yields BGR uint8 frames. Iterable and usable as a context manager."""

    @property
    @abstractmethod
    def fps(self) -> float: ...

    @property
    @abstractmethod
    def size(self) -> tuple[int, int]:
        """(width, height)."""

    @property
    def frame_count(self) -> int:
        """Total frames, or -1 if unknown (e.g. live camera)."""
        return -1

    @abstractmethod
    def read(self) -> tuple[bool, np.ndarray | None]:
        """Return (ok, frame_bgr). ok=False at end of stream."""

    def __iter__(self):
        while True:
            ok, frame = self.read()
            if not ok:
                break
            yield frame

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class _CvSource(FrameSource):
    def __init__(self, target):
        self._cap = cv2.VideoCapture(target)
        if not self._cap.isOpened():
            raise RuntimeError(f"cannot open video source: {target!r}")

    @property
    def fps(self) -> float:
        f = self._cap.get(cv2.CAP_PROP_FPS)
        return float(f) if f and f > 0 else 30.0

    @property
    def size(self) -> tuple[int, int]:
        return (int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

    @property
    def frame_count(self) -> int:
        return int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))

    def read(self):
        ok, frame = self._cap.read()
        return (ok, frame if ok else None)

    def close(self):
        self._cap.release()


class FileSource(_CvSource):
    def __init__(self, path: str):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        self.path = path
        super().__init__(path)


class WebcamSource(_CvSource):
    def __init__(self, index: int = 0):
        super().__init__(int(index))

    @property
    def frame_count(self) -> int:
        return -1


class GenICamSource(FrameSource):
    """Real machine-vision cameras (Hikrobot MV-CS016 etc.) via Harvesters.

    Requires the `harvesters` package and a GenTL producer (.cti) from Hikvision
    MVS. Practically Windows/Linux — this is the M2+ path, not used for Mac dev.
    """

    def __init__(self, serial: str | None = None, cti: str | None = None,
                 fps: float = 60.0):
        try:
            from harvesters.core import Harvester
        except Exception as exc:  # pragma: no cover - depends on optional dep
            raise RuntimeError(
                "GenICam capture needs 'harvesters' (pip install -r "
                "requirements-capture.txt) plus a GenTL .cti producer from "
                "Hikvision MVS. On macOS use a file/webcam source instead."
            ) from exc

        cti = cti or os.environ.get("GENICAM_GENTL64_PATH") or os.environ.get("MVCAM_GENTL64_PATH")
        if not cti:
            raise RuntimeError(
                "no GenTL producer configured — set GENICAM_GENTL64_PATH to the "
                "MVS .cti file, or pass cti=..."
            )
        self._fps = fps
        self._h = Harvester()
        for part in cti.split(os.pathsep):
            if part:
                self._h.add_file(part)
        self._h.update()
        config = {"serial_number": str(serial)} if serial else {}
        self._ia = self._h.create(config) if config else self._h.create()
        self._ia.start()
        self._size = None

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def size(self) -> tuple[int, int]:
        return self._size or (0, 0)

    def read(self):  # pragma: no cover - hardware path
        try:
            with self._ia.fetch(timeout=5) as buffer:
                comp = buffer.payload.components[0]
                h, w = int(comp.height), int(comp.width)
                self._size = (w, h)
                data = comp.data.reshape(h, w)          # Mono8
                return True, cv2.cvtColor(data, cv2.COLOR_GRAY2BGR)
        except Exception:
            return False, None

    def close(self):  # pragma: no cover - hardware path
        try:
            self._ia.stop()
            self._ia.destroy()
        finally:
            self._h.reset()


def open_source(spec, **kwargs) -> FrameSource:
    """Factory: 'file:PATH' | 'cam:N' | 'genicam:SERIAL' | a bare path."""
    if isinstance(spec, int):
        return WebcamSource(spec)
    s = str(spec)
    if s.startswith("file:"):
        return FileSource(s[5:])
    if s.startswith("cam:"):
        return WebcamSource(int(s[4:]))
    if s.startswith("genicam:"):
        return GenICamSource(serial=(s[8:] or None), **kwargs)
    return FileSource(s)
