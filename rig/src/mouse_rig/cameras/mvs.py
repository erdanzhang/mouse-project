"""Hikrobot cameras through the official MVS SDK (``MvImport`` Python wrapper).

Requirements on the camera computer
-----------------------------------
* Install Hikrobot **MVS** (Machine Vision Software). It contains the USB3 Vision
  driver, the native SDK (``MvCameraControl.dll`` / ``libMvCameraControl.so``) and
  the Python wrapper folder ``MvImport``.
* This module finds ``MvImport`` automatically in the standard install folders.
  If it cannot, set ``cameras.mvs_python_path`` in ``recorder.yaml`` or the
  environment variable ``MVS_PYTHON_PATH`` to the ``MvImport`` folder.

Platform support (Hikrobot's, not ours): MVS 4.x supports Windows and Linux.
Hikrobot only published an old MVS 2.0 for macOS; on a Mac this backend reports
"SDK not found" and the recorder still runs with the other backends.
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from pathlib import Path

from . import pixel
from .base import Camera, CameraError, CameraInfo, CameraSettings, Frame

MV_OK = 0
_MV_E_NODATA = 0x80000007

_sdk = None              # the imported MvCameraControl_class module
_sdk_path: str | None = None
_sdk_error: str | None = None
_sdk_lock = threading.Lock()


def candidate_paths(configured: str | None = None) -> list[Path]:
    """Folders that may contain MvImport/MvCameraControl_class.py, in search order."""
    paths: list[Path] = []
    for p in (configured, os.environ.get("MVS_PYTHON_PATH")):
        if p:
            paths.append(Path(os.path.expanduser(p)))
    if sys.platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                     r"C:\Program Files (x86)", r"C:\Program Files"):
            if base:
                paths.append(Path(base) / "MVS" / "Development" / "Samples" / "Python" / "MvImport")
    elif sys.platform.startswith("linux"):
        for arch in ("64", "aarch64"):
            paths.append(Path("/opt/MVS/Samples") / arch / "Python" / "MvImport")
    else:  # macOS: no standard location for the old MVS 2.0 wrapper
        paths.append(Path("/Library/MVS_SDK/Samples/Python/MvImport"))
    seen, unique = set(), []
    for p in paths:
        if str(p) not in seen:
            seen.add(str(p))
            unique.append(p)
    return unique


def _add_windows_dll_dirs() -> None:
    if not sys.platform.startswith("win") or not hasattr(os, "add_dll_directory"):
        return
    runenv = os.environ.get("MVCAM_COMMON_RUNENV")
    dirs = []
    if runenv:
        dirs += [Path(runenv) / "Win64_x64", Path(runenv)]
    for base in (os.environ.get("ProgramFiles(x86)"), r"C:\Program Files (x86)"):
        if base:
            dirs.append(Path(base) / "Common Files" / "MVS" / "Runtime" / "Win64_x64")
    for d in dirs:
        if d.is_dir():
            try:
                os.add_dll_directory(str(d))
            except OSError:
                pass


def load_sdk(configured_path: str | None = None):
    """Import the MVS wrapper once. Raise CameraError with a clear message if absent."""
    global _sdk, _sdk_path, _sdk_error
    with _sdk_lock:
        if _sdk is not None:
            return _sdk
        if sys.maxsize <= 2**32:
            raise CameraError("64-bit Python is required for the MVS SDK")
        found = [p for p in candidate_paths(configured_path) if (p / "MvCameraControl_class.py").is_file()]
        if not found:
            _sdk_error = ("MVS SDK not found. Install Hikrobot MVS (Windows/Linux), or set "
                          "cameras.mvs_python_path in recorder.yaml to the MvImport folder. "
                          "Searched: " + "; ".join(str(p) for p in candidate_paths(configured_path)))
            raise CameraError(_sdk_error)
        path = found[0]
        _add_windows_dll_dirs()
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
        try:
            import MvCameraControl_class as sdk  # type: ignore[import-not-found]
        except Exception as exc:  # the wrapper loads the native library at import time
            _sdk_error = (f"found MvImport at {path} but could not load the native MVS library "
                          f"({type(exc).__name__}: {exc}). Re-install MVS and reboot.")
            raise CameraError(_sdk_error) from exc
        init = getattr(sdk.MvCamera, "MV_CC_Initialize", None)
        if init is not None:
            ret = init()
            if ret != MV_OK:
                raise CameraError(f"MV_CC_Initialize failed: 0x{ret & 0xFFFFFFFF:08X}")
        _sdk, _sdk_path, _sdk_error = sdk, str(path), None
        return sdk


def sdk_status(configured_path: str | None = None) -> dict:
    """For `mouse-rig report`: is the SDK available, and where."""
    try:
        load_sdk(configured_path)
        return {"available": True, "path": _sdk_path, "error": None}
    except CameraError as exc:
        return {"available": False, "path": None, "error": str(exc)}


def _cstr(arr) -> str:
    return bytes(arr).split(b"\0", 1)[0].decode("ascii", "ignore").strip()


def _enumerate(sdk):
    dev_list = sdk.MV_CC_DEVICE_INFO_LIST()
    ret = sdk.MvCamera.MV_CC_EnumDevices(sdk.MV_GIGE_DEVICE | sdk.MV_USB_DEVICE, dev_list)
    if ret != MV_OK:
        raise CameraError(f"MV_CC_EnumDevices failed: 0x{ret & 0xFFFFFFFF:08X}")
    out = []
    for i in range(dev_list.nDeviceNum):
        info = ctypes.cast(dev_list.pDeviceInfo[i], ctypes.POINTER(sdk.MV_CC_DEVICE_INFO)).contents
        if info.nTLayerType == sdk.MV_USB_DEVICE:
            s = info.SpecialInfo.stUsb3VInfo
        elif info.nTLayerType == sdk.MV_GIGE_DEVICE:
            s = info.SpecialInfo.stGigEInfo
        else:
            continue
        out.append((info, _cstr(s.chSerialNumber), _cstr(s.chModelName), _cstr(s.chUserDefinedName)))
    return dev_list, out


def _is_color_model(model: str) -> bool:
    # Hikrobot model suffix: ...-10UM / -10GM = mono, ...-10UC / -10GC = color
    m = model.strip().upper()
    return m.endswith("C") and not m.endswith("M")


def discover(cfg: dict) -> list[CameraInfo]:
    sdk = load_sdk(cfg.get("mvs_python_path"))
    _keep, devices = _enumerate(sdk)
    return [CameraInfo(backend="mvs", serial=serial or f"mvs-{i}", model=model, name=name,
                       is_color=_is_color_model(model))
            for i, (_info, serial, model, name) in enumerate(devices)]


def open_camera(info: CameraInfo, settings: CameraSettings, cfg: dict) -> "MvsCamera":
    return MvsCamera(info, settings, cfg.get("mvs_python_path"))


class MvsCamera(Camera):
    def __init__(self, info: CameraInfo, settings: CameraSettings, sdk_path: str | None):
        super().__init__(info, settings)
        self._sdk = sdk = load_sdk(sdk_path)
        self.warnings: list[str] = []
        dev_list, devices = _enumerate(sdk)  # keep dev_list alive while creating the handle
        match = [d for d in devices if d[1] == info.serial]
        if not match:
            raise CameraError(f"camera {info.serial} not found (unplugged, or open in MVS?)")
        self._cam = sdk.MvCamera()
        self._check(self._cam.MV_CC_CreateHandle(match[0][0]), "CreateHandle")
        ret = self._cam.MV_CC_OpenDevice(sdk.MV_ACCESS_Exclusive, 0)
        if ret != MV_OK:
            self._cam.MV_CC_DestroyHandle()
            raise CameraError(f"cannot open camera {info.serial} (0x{ret & 0xFFFFFFFF:08X}). "
                              "Close the MVS client and any other program that uses the camera.")
        self._opened = True
        self._grabbing = False
        self._configure()

    # -- helpers ---------------------------------------------------------------
    def _check(self, ret: int, what: str) -> None:
        if ret != MV_OK:
            raise CameraError(f"{self.info.serial}: {what} failed (0x{ret & 0xFFFFFFFF:08X})")

    def _try(self, ret: int, what: str) -> bool:
        if ret != MV_OK:
            self.warnings.append(f"{what} failed (0x{ret & 0xFFFFFFFF:08X})")
            return False
        return True

    def _set_enum(self, key: str, value: str) -> bool:
        return self._try(self._cam.MV_CC_SetEnumValueByString(key, value), f"{key}={value}")

    def _set_float(self, key: str, value: float) -> bool:
        return self._try(self._cam.MV_CC_SetFloatValue(key, float(value)), f"{key}={value}")

    def _set_bool(self, key: str, value: bool) -> bool:
        return self._try(self._cam.MV_CC_SetBoolValue(key, bool(value)), f"{key}={value}")

    # -- configuration ---------------------------------------------------------
    def _configure(self) -> None:
        s = self.settings
        if s.pixel_format and s.pixel_format != "auto":
            formats = [s.pixel_format]
        elif self.info.is_color:
            formats = ["BayerRG8", "BayerGB8", "BayerGR8", "BayerBG8", "RGB8Packed"]
        else:
            formats = ["Mono8"]
        for fmt in formats:
            if self._cam.MV_CC_SetEnumValueByString("PixelFormat", fmt) == MV_OK:
                break
        else:
            self.warnings.append(f"could not set PixelFormat to any of {formats}; using camera default")
        self._set_enum("ExposureAuto", "Off")
        self._set_enum("GainAuto", "Off")
        self._set_float("ExposureTime", s.exposure_us)
        self._set_float("Gain", s.gain_db)
        self._select_frame_trigger()
        if s.trigger == "line0":
            self._set_bool("AcquisitionFrameRateEnable", False)
            self._set_enum("TriggerMode", "On")
            self._set_enum("TriggerSource", "Line0")
            self._set_enum("TriggerActivation", "RisingEdge")
        else:
            self._set_enum("TriggerMode", "Off")
            self._set_bool("AcquisitionFrameRateEnable", True)
            self._set_float("AcquisitionFrameRate", s.fps)
        if hasattr(self._cam, "MV_CC_SetImageNodeNum"):
            self._cam.MV_CC_SetImageNodeNum(16)

    def _select_frame_trigger(self) -> None:
        """Make one trigger pulse start one frame.

        Most models call this selector "FrameStart". The Hikrobot CS series (e.g.
        MV-CS016-10UC) only has "FrameBurstStart", which is the same thing with a
        burst of 1 frame.
        """
        cam = self._cam
        if cam.MV_CC_SetEnumValueByString("TriggerSelector", "FrameStart") == MV_OK:
            return
        if cam.MV_CC_SetEnumValueByString("TriggerSelector", "FrameBurstStart") != MV_OK:
            self.warnings.append("could not set TriggerSelector to FrameStart or FrameBurstStart; "
                                 "using the camera default")
            return
        if cam.MV_CC_SetIntValueEx("AcquisitionBurstFrameCount", 1) != MV_OK:
            value = self._sdk.MVCC_INTVALUE_EX()
            if cam.MV_CC_GetIntValueEx("AcquisitionBurstFrameCount", value) == MV_OK and value.nCurValue != 1:
                self.warnings.append(f"AcquisitionBurstFrameCount is {value.nCurValue}, not 1: "
                                     "each trigger pulse makes several frames")

    # -- Camera interface ------------------------------------------------------
    def start(self) -> None:
        self._check(self._cam.MV_CC_StartGrabbing(), "StartGrabbing")
        self._grabbing = True

    def grab(self, timeout_ms: int = 500) -> Frame | None:
        sdk = self._sdk
        out = sdk.MV_FRAME_OUT()
        ctypes.memset(ctypes.byref(out), 0, ctypes.sizeof(out))
        ret = self._cam.MV_CC_GetImageBuffer(out, int(timeout_ms))
        if ret != MV_OK:
            if (ret & 0xFFFFFFFF) == _MV_E_NODATA:
                return None
            if hasattr(self._cam, "MV_CC_IsDeviceConnected") and not self._cam.MV_CC_IsDeviceConnected():
                raise CameraError(f"camera {self.info.serial} disconnected")
            return None
        try:
            fi = out.stFrameInfo
            width = int(getattr(fi, "nExtendWidth", 0) or fi.nWidth)
            height = int(getattr(fi, "nExtendHeight", 0) or fi.nHeight)
            length = int(getattr(fi, "nFrameLenEx", 0) or fi.nFrameLen)
            data = ctypes.string_at(out.pBufAddr, length)
            image = pixel.to_image(data, width, height, int(fi.enPixelType))
            self.width, self.height = width, height
            return Frame(
                image=image,
                host_time=time.time(),
                frame_id=int(fi.nFrameNum),
                device_ts=(int(fi.nDevTimeStampHigh) << 32) | int(fi.nDevTimeStampLow),
                extra={"lost_packets": int(getattr(fi, "nLostPacket", 0))},
            )
        finally:
            self._cam.MV_CC_FreeImageBuffer(out)

    def set_exposure(self, exposure_us: float) -> float:
        if self._set_float("ExposureTime", exposure_us):
            self.settings.exposure_us = float(exposure_us)
        return self.settings.exposure_us

    def set_gain(self, gain_db: float) -> float:
        if self._set_float("Gain", gain_db):
            self.settings.gain_db = float(gain_db)
        return self.settings.gain_db

    def stop(self) -> None:
        if self._grabbing:
            self._cam.MV_CC_StopGrabbing()
            self._grabbing = False

    def close(self) -> None:
        self.stop()
        if self._opened:
            self._cam.MV_CC_CloseDevice()
            self._cam.MV_CC_DestroyHandle()
            self._opened = False
