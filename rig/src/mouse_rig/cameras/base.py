"""Camera interface shared by every backend.

A backend has two jobs:
  * ``discover(cfg) -> list[CameraInfo]`` — find cameras without opening them.
  * ``open_camera(info, settings) -> Camera`` — open one camera and configure it.

A ``Camera`` then delivers ``Frame`` objects from ``grab()``. Everything above this
layer (preview, recording, the web UI) only talks to this interface, so it runs the
same way on Windows, macOS and Linux.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field

import numpy as np


class CameraError(RuntimeError):
    """A camera or a camera backend failed. The message is shown in the web UI."""


@dataclass
class CameraInfo:
    backend: str          # "mvs" | "opencv" | "synthetic"
    serial: str           # stable identity; used to fix the cam-N order
    model: str = ""
    name: str = ""        # user-defined name stored in the camera, if any
    is_color: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class CameraSettings:
    fps: float = 60.0
    exposure_us: float = 4000.0
    gain_db: float = 0.0
    trigger: str = "free"         # "free" = free-run, "line0" = external trigger on Line0
    pixel_format: str = "auto"    # "auto" | "Mono8" | "BayerRG8" | "RGB8Packed" ...
    enabled: bool = True
    label: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Frame:
    image: np.ndarray             # HxW uint8 (mono) or HxWx3 uint8 (BGR)
    host_time: float              # time.time() when the frame reached the host
    frame_id: int = -1            # camera frame counter (-1 if unknown)
    device_ts: int = 0            # camera timestamp in device ticks (0 if unknown)
    extra: dict = field(default_factory=dict)


class Camera(ABC):
    def __init__(self, info: CameraInfo, settings: CameraSettings):
        self.info = info
        self.settings = settings
        self.width = 0
        self.height = 0

    @abstractmethod
    def start(self) -> None:
        """Start acquisition."""

    @abstractmethod
    def grab(self, timeout_ms: int = 500) -> Frame | None:
        """Return the next frame, or None if no frame arrived before the timeout."""

    @abstractmethod
    def stop(self) -> None:
        """Stop acquisition (the camera stays open)."""

    @abstractmethod
    def close(self) -> None:
        """Release the camera."""

    def set_exposure(self, exposure_us: float) -> float:
        self.settings.exposure_us = float(exposure_us)
        return self.settings.exposure_us

    def set_gain(self, gain_db: float) -> float:
        self.settings.gain_db = float(gain_db)
        return self.settings.gain_db
