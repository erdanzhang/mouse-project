"""Camera backends behind one interface (see ``base.py``).

* ``mvs``       — Hikrobot cameras through the MVS SDK (Windows / Linux)
* ``opencv``    — USB webcams (any OS)
* ``synthetic`` — moving test pattern, no hardware needed (any OS)

Backends import their native dependencies lazily, so ``import mouse_rig`` never
needs the camera SDK.
"""
from __future__ import annotations

import importlib

from .base import Camera, CameraError, CameraInfo, CameraSettings, Frame

BACKENDS = {
    "mvs": "mouse_rig.cameras.mvs",
    "opencv": "mouse_rig.cameras.opencv_cam",
    "synthetic": "mouse_rig.cameras.synthetic",
}


def backend_module(name: str):
    if name not in BACKENDS:
        raise CameraError(f"unknown camera backend {name!r}; use one of {sorted(BACKENDS)}")
    return importlib.import_module(BACKENDS[name])


__all__ = ["BACKENDS", "Camera", "CameraError", "CameraInfo", "CameraSettings", "Frame", "backend_module"]
