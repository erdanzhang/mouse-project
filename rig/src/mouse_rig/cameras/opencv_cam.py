"""USB webcam backend (UVC) through OpenCV.

Hikrobot machine-vision cameras are USB3 Vision, not UVC, so they do NOT appear
here — use the ``mvs`` backend for them. This backend is for a normal USB webcam,
for example to test the recorder before the real cameras arrive.
"""
from __future__ import annotations

import sys
import time

import cv2

from .base import Camera, CameraError, CameraInfo, CameraSettings, Frame


def _api() -> int:
    if sys.platform.startswith("win"):
        return cv2.CAP_DSHOW
    if sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_ANY


def discover(cfg: dict) -> list[CameraInfo]:
    infos = []
    for index in cfg.get("indices", [0]):
        cap = cv2.VideoCapture(int(index), _api())
        ok = cap.isOpened()
        cap.release()
        if ok:
            infos.append(CameraInfo(backend="opencv", serial=f"webcam-{index}", model="UVC webcam",
                                    is_color=True))
    return infos


def open_camera(info: CameraInfo, settings: CameraSettings, cfg: dict) -> "OpenCVCamera":
    return OpenCVCamera(info, settings, int(info.serial.split("-")[-1]))


class OpenCVCamera(Camera):
    def __init__(self, info: CameraInfo, settings: CameraSettings, index: int):
        super().__init__(info, settings)
        self._cap = cv2.VideoCapture(index, _api())
        if not self._cap.isOpened():
            raise CameraError(f"cannot open webcam index {index}")
        self._cap.set(cv2.CAP_PROP_FPS, float(settings.fps))
        self.width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._n = 0

    def start(self) -> None:
        pass

    def grab(self, timeout_ms: int = 500) -> Frame | None:
        ok, img = self._cap.read()
        if not ok:
            time.sleep(min(timeout_ms, 100) / 1000.0)
            return None
        self._n += 1
        return Frame(image=img, host_time=time.time(), frame_id=self._n)

    def stop(self) -> None:
        pass

    def close(self) -> None:
        self._cap.release()
