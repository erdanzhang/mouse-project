"""Camera manager: discover, open, acquire continuously, preview, and fan out frames.

Each open camera gets one acquisition thread. The thread keeps the latest frame
for the web preview and passes every frame to a "sink" (the clip writer) while a
recording runs. Cameras stay open between recordings, so the preview is always on.

When every enabled camera uses ``trigger: "line0"``, the manager also gives each
frame a shared trigger index (``frame.extra["trigger_index"]``, see ``sync.py``).
If the Arduino is on a USB serial port, the manager sets its frame rate and stops
the pulses while the cameras open, so the index is exact (see ``arduino.py``).
"""
from __future__ import annotations

import collections
import threading
import time
from dataclasses import dataclass, field

import cv2

from ..cameras import CameraError, backend_module
from ..cameras.base import Camera, CameraInfo, CameraSettings, Frame
from .arduino import ArduinoLink
from .config import settings_for
from .sync import TriggerClock


@dataclass
class CameraSlot:
    cam_id: str                     # "cam-1", "cam-2", ...
    index: int                      # 1, 2, ...
    info: CameraInfo
    settings: CameraSettings
    camera: Camera | None = None
    thread: threading.Thread | None = None
    latest: Frame | None = None
    sink: object = None             # callable(frame) or None
    state: str = "closed"           # closed | ok | waiting | error | disabled
    error: str = ""
    warnings: list = field(default_factory=list)
    frames_total: int = 0
    lost_frames: int = 0            # gaps in the camera frame counter
    last_frame_id: int = -1
    times: collections.deque = field(default_factory=lambda: collections.deque(maxlen=120))

    def fps(self) -> float:
        if len(self.times) < 2:
            return 0.0
        span = self.times[-1] - self.times[0]
        if time.time() - self.times[-1] > 2.0:
            return 0.0
        return (len(self.times) - 1) / span if span > 0 else 0.0


class CameraManager:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.slots: list[CameraSlot] = []
        self.discovery_errors: list[str] = []
        self.clock: TriggerClock | None = None    # set when all cameras use the hardware trigger
        self.link = None                          # ArduinoLink (or the demo VirtualLink), if found
        self.link_note = ""
        self._stop = threading.Event()
        self._lock = threading.RLock()

    # -- discovery -------------------------------------------------------------
    def discover(self) -> list[CameraInfo]:
        cam_cfg = self.cfg["cameras"]
        infos: list[CameraInfo] = []
        self.discovery_errors = []
        for backend in cam_cfg["backends"]:
            sub = dict(cam_cfg.get(backend, {}) or {})
            sub["mvs_python_path"] = cam_cfg.get("mvs_python_path")
            try:
                infos += backend_module(backend).discover(sub)
            except CameraError as exc:
                self.discovery_errors.append(f"{backend}: {exc}")
            except Exception as exc:  # keep the server alive on any backend failure
                self.discovery_errors.append(f"{backend}: {type(exc).__name__}: {exc}")
        order = [str(s) for s in cam_cfg.get("order") or []]
        rank = {s: i for i, s in enumerate(order)}
        infos.sort(key=lambda i: (rank.get(i.serial, len(order)), i.backend, i.serial))
        return infos

    # -- open / close ----------------------------------------------------------
    def open_all(self) -> None:
        with self._lock:
            self.close_all(release_link=False)
            self._stop.clear()
            for n, info in enumerate(self.discover(), start=1):
                settings = settings_for(self.cfg, info.serial)
                self.slots.append(CameraSlot(cam_id=f"cam-{n}", index=n, info=info, settings=settings))
            enabled = [s for s in self.slots if s.settings.enabled]
            gate = False
            if enabled and all(s.settings.trigger == "line0" for s in enabled):
                self.clock = TriggerClock(enabled[0].settings.fps)
                gate = self._prepare_link(enabled)
            for slot in self.slots:
                if not slot.settings.enabled:
                    slot.state = "disabled"
                    continue
                self._open_slot(slot)
            if gate:
                time.sleep(0.2)                   # pulses already in flight reach the cameras
                self.clock.arm_gate()
                try:
                    self.link.run()
                except Exception as exc:
                    self.link_note = f"could not start the Arduino: {exc}"

    def _prepare_link(self, enabled: list) -> bool:
        """Find the Arduino, set its fps, and stop its pulses. True if the gate is ready."""
        if self.link is None:
            if all(s.info.backend == "synthetic" for s in enabled):
                from ..cameras.synthetic import VirtualLink
                self.link, self.link_note = VirtualLink(), "virtual Arduino (demo)"
            else:
                port = self.cfg["cameras"].get("arduino_port", "auto")
                self.link, self.link_note = ArduinoLink.find(port)
        if self.link is None:
            return False
        try:
            self.link.set_fps(enabled[0].settings.fps)
            self.link.stop()
            return True
        except Exception as exc:
            self.link_note = f"Arduino on {self.link.port} did not answer: {exc}"
            self.link.close()
            self.link = None
            return False

    def _open_slot(self, slot: CameraSlot) -> None:
        backend = slot.info.backend
        sub = dict(self.cfg["cameras"].get(backend, {}) or {})
        sub["mvs_python_path"] = self.cfg["cameras"].get("mvs_python_path")
        try:
            cam = backend_module(backend).open_camera(slot.info, slot.settings, sub)
            cam.start()
        except Exception as exc:
            slot.state, slot.error = "error", str(exc)
            return
        slot.camera = cam
        slot.warnings = list(getattr(cam, "warnings", []))
        slot.state = "waiting"
        slot.thread = threading.Thread(target=self._acquire, args=(slot,), name=f"acq-{slot.cam_id}", daemon=True)
        slot.thread.start()

    def close_all(self, release_link: bool = True) -> None:
        with self._lock:
            self._stop.set()
            for slot in self.slots:
                if slot.thread is not None:
                    slot.thread.join(timeout=3)
                if slot.camera is not None:
                    try:
                        slot.camera.close()
                    except Exception:
                        pass
                slot.camera = None
                slot.state = "closed"
            self.slots = []
            self.clock = None
            if release_link and self.link is not None:
                self.link.close()
                self.link = None

    # -- acquisition -----------------------------------------------------------
    def _acquire(self, slot: CameraSlot) -> None:
        cam = slot.camera
        misses = 0
        while not self._stop.is_set():
            try:
                frame = cam.grab(timeout_ms=500)
            except Exception as exc:
                slot.state, slot.error = "error", str(exc)
                return
            if frame is None:
                misses += 1
                if misses >= 4:          # ~2 s without frames
                    slot.state = "waiting"
                continue
            misses = 0
            slot.state = "ok"
            if slot.last_frame_id >= 0 and frame.frame_id > slot.last_frame_id + 1:
                slot.lost_frames += frame.frame_id - slot.last_frame_id - 1
            slot.last_frame_id = frame.frame_id
            slot.frames_total += 1
            slot.times.append(frame.host_time)
            clock = self.clock
            if clock is not None:
                frame.extra["trigger_index"] = clock.index(slot.cam_id, frame.frame_id, frame.host_time,
                                                           frame.device_ts)
            slot.latest = frame
            sink = slot.sink
            if sink is not None:
                sink(frame)

    # -- used by the recorder and the web UI -----------------------------------
    def open_slots(self) -> list[CameraSlot]:
        return [s for s in self.slots if s.camera is not None and s.state in ("ok", "waiting")]

    def slot(self, cam_id: str) -> CameraSlot | None:
        return next((s for s in self.slots if s.cam_id == cam_id), None)

    def preview_jpeg(self, cam_id: str, width: int = 640) -> bytes | None:
        slot = self.slot(cam_id)
        if slot is None or slot.latest is None:
            return None
        img = slot.latest.image
        h, w = img.shape[:2]
        if w > width:
            img = cv2.resize(img, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return buf.tobytes() if ok else None

    def apply_settings(self, cam_id: str, exposure_us: float | None, gain_db: float | None) -> dict:
        slot = self.slot(cam_id)
        if slot is None or slot.camera is None:
            raise CameraError(f"{cam_id} is not open")
        if exposure_us is not None:
            slot.camera.set_exposure(float(exposure_us))
        if gain_db is not None:
            slot.camera.set_gain(float(gain_db))
        slot.warnings = list(getattr(slot.camera, "warnings", []))[-5:]
        return slot.camera.settings.as_dict()

    def sync_status(self) -> dict:
        if self.clock is None:
            return {"mode": "free"}
        link = None
        if self.link is not None:
            try:
                link = self.link.info()
            except Exception:
                link = {"port": self.link.port}
        return {"mode": "line0", "gated": self.clock.gated, "corrections": self.clock.corrections,
                "trigger_fps": round(1.0 / self.clock.period, 2), "arduino": link, "note": self.link_note}

    def status(self) -> list[dict]:
        out = []
        for s in self.slots:
            img = s.latest.image if s.latest is not None else None
            fps = s.fps()
            # trigger mode: the Arduino sets the frame rate; it must match the fps in the config
            fps_mismatch = (s.settings.trigger == "line0" and s.state == "ok" and fps > 0
                            and abs(fps - s.settings.fps) > 0.03 * s.settings.fps)
            out.append({
                "id": s.cam_id,
                "index": s.index,
                "backend": s.info.backend,
                "serial": s.info.serial,
                "model": s.info.model,
                "label": s.settings.label or s.info.name,
                "color": bool(img is not None and img.ndim == 3) if img is not None else s.info.is_color,
                "state": s.state,
                "error": s.error,
                "warnings": s.warnings[-5:],
                "width": int(img.shape[1]) if img is not None else 0,
                "height": int(img.shape[0]) if img is not None else 0,
                "fps": round(fps, 1),
                "fps_mismatch": fps_mismatch,
                "frames_total": s.frames_total,
                "lost_frames": s.lost_frames,
                "settings": s.settings.as_dict(),
            })
        return out
