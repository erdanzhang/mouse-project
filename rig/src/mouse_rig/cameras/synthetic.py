"""Synthetic camera — a moving test pattern for machines with no camera.

Use it to test the recorder, the web UI and the clip splitting on any computer:
``mouse-rig serve --demo``. Exposure and gain change the image brightness, so the
web UI controls give visible feedback.

With ``trigger: "line0"`` the synthetic cameras wait for a virtual Arduino: one pulse
clock shared by all synthetic cameras. Each camera adds its own transfer delay
(1-5 ms plus jitter) and counts its frames from its own start, like a real camera.
So the demo also tests the hardware-sync path. ``drop_every: N`` (in the
``synthetic`` config) loses about one frame in N on each camera, to test gap filling.
"""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime

import cv2
import numpy as np

from .base import Camera, CameraInfo, CameraSettings, Frame


def discover(cfg: dict) -> list[CameraInfo]:
    count = int(cfg.get("count", 2))
    return [
        CameraInfo(backend="synthetic", serial=f"SYN{i + 1:04d}", model="Synthetic-Mono",
                   name=f"demo {i + 1}", is_color=False)
        for i in range(count)
    ]


def open_camera(info: CameraInfo, settings: CameraSettings, cfg: dict) -> "SyntheticCamera":
    return SyntheticCamera(info, settings, int(cfg.get("width", 1440)), int(cfg.get("height", 1080)),
                           drop_every=int(cfg.get("drop_every", 0) or 0))


class VirtualTrigger:
    """Stands in for the Arduino in demo mode: a thread that counts pulses at fps.

    There is one virtual trigger per process. ``VirtualLink`` gives it the same
    commands as the real serial link (set fps, stop, run).
    """

    _instance: "VirtualTrigger | None" = None
    _guard = threading.Lock()

    def __init__(self, fps: float = 60.0):
        self.period = 1.0 / max(1.0, float(fps))
        self.running = True
        self.count = 0                                   # pulses fired so far
        self._times: dict[int, float] = {}               # pulse -> monotonic time (last ~10 s)
        self._cond = threading.Condition()
        threading.Thread(target=self._run, name="virtual-trigger", daemon=True).start()

    @classmethod
    def instance(cls, fps: float = 60.0) -> "VirtualTrigger":
        with cls._guard:
            if cls._instance is None:
                cls._instance = cls(fps)
            return cls._instance

    def _run(self) -> None:
        nxt = time.monotonic()
        while True:
            nxt += self.period
            wait = nxt - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            else:
                nxt = time.monotonic()
            if not self.running:
                continue
            with self._cond:
                self.count += 1
                self._times[self.count] = nxt
                self._times.pop(self.count - 600, None)
                self._cond.notify_all()

    def wait_for(self, pulse: int, timeout: float) -> float | None:
        """Wait until ``pulse`` has fired; return its time, or None on timeout."""
        with self._cond:
            if not self._cond.wait_for(lambda: self.count >= pulse, timeout):
                return None
            return self._times.get(pulse, time.monotonic())

    # the serial-link commands
    def set_fps(self, fps: float) -> None:
        self.period = 1.0 / max(1.0, float(fps))

    def status(self) -> dict:
        return {"fps": int(round(1.0 / self.period)), "running": self.running, "pulses": self.count}


class VirtualLink:
    """The demo version of ``recorder.arduino.ArduinoLink``."""

    port = "virtual"

    def __init__(self):
        self._trig = VirtualTrigger.instance()

    def set_fps(self, fps: float) -> dict:
        self._trig.set_fps(fps)
        return self._trig.status()

    def stop(self) -> dict:
        self._trig.running = False
        return self._trig.status()

    def run(self) -> dict:
        self._trig.running = True
        return self._trig.status()

    def status(self) -> dict:
        return self._trig.status()

    def info(self) -> dict:
        return {"port": self.port, **self._trig.status()}

    def close(self) -> None:
        pass


class SyntheticCamera(Camera):
    def __init__(self, info: CameraInfo, settings: CameraSettings, width: int, height: int,
                 drop_every: int = 0):
        super().__init__(info, settings)
        self.width = width - width % 2
        self.height = height - height % 2
        self._running = False
        self._next = 0.0
        self._n = 0
        seed = sum(ord(c) for c in info.serial)
        self._rng = np.random.default_rng(seed)
        self._phase = seed * 0.37
        self._bg = self._make_background()
        self._drop_every = drop_every
        self._latency = 0.001 + (seed % 5) * 0.001       # 1-5 ms "USB transfer" per camera
        self._pulse: int | None = None                    # next trigger pulse (line0 mode)
        self._label = ""

    def _make_background(self) -> np.ndarray:
        bg = np.full((self.height, self.width), 35, np.uint8)
        cx, cy = self.width // 2, self.height // 2
        r = int(min(self.width, self.height) * 0.42)
        cv2.circle(bg, (cx, cy), r, 60, thickness=-1)          # beaker floor
        cv2.circle(bg, (cx, cy), r, 110, thickness=6)          # beaker rim
        noise = self._rng.integers(0, 6, size=bg.shape, dtype=np.uint8)
        return cv2.add(bg, noise)

    def start(self) -> None:
        self._running = True
        self._next = time.monotonic()
        self._pulse = None

    def grab(self, timeout_ms: int = 500) -> Frame | None:
        if not self._running:
            return None
        if self.settings.trigger == "line0":
            return self._grab_triggered(timeout_ms)
        self._label = ""
        period = 1.0 / max(1.0, float(self.settings.fps))
        now = time.monotonic()
        wait = self._next - now
        if wait > timeout_ms / 1000.0:
            time.sleep(timeout_ms / 1000.0)
            return None
        if wait > 0:
            time.sleep(wait)
        self._next = max(self._next + period, time.monotonic() - period)
        img = self._render()
        self._n += 1
        return Frame(image=img, host_time=time.time(), frame_id=self._n, device_ts=int(time.monotonic() * 1e9))

    def _grab_triggered(self, timeout_ms: int) -> Frame | None:
        trig = VirtualTrigger.instance(self.settings.fps)
        if self._pulse is None:                           # the camera starts with the next pulse
            self._pulse = trig.count + 1
            self._n = 0
        elif trig.count - self._pulse > 0.5 / trig.period:   # host too slow: the camera buffer overflows
            self._n += trig.count - self._pulse
            self._pulse = trig.count
        while True:
            fired = trig.wait_for(self._pulse, timeout_ms / 1000.0)
            if fired is None:
                return None
            due = fired + self._latency + float(self._rng.uniform(0, 0.002))
            wait = due - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            pulse = self._pulse
            self._pulse += 1
            self._n += 1                                       # camera frame counter
            if self._drop_every and float(self._rng.random()) < 1.0 / self._drop_every:
                continue                                       # lost on the "USB link": the counter skips
            self._label = f"pulse {pulse}"
            img = self._render()
            return Frame(image=img, host_time=time.time(), frame_id=self._n,
                         device_ts=int(fired * 1e9), extra={"pulse": pulse})

    def _render(self) -> np.ndarray:
        img = self._bg.copy()
        t = self._n / max(1.0, float(self.settings.fps)) + self._phase
        cx, cy = self.width // 2, self.height // 2
        r = min(self.width, self.height) * 0.28
        mx = int(cx + r * math.cos(t * 0.35) * math.cos(t * 0.11))
        my = int(cy + r * math.sin(t * 0.35))
        body = (max(4, self.width // 24), max(3, self.width // 40))
        angle = math.degrees(t * 0.35) + 90
        cv2.ellipse(img, (mx, my), body, angle, 0, 360, 225, thickness=-1)
        # a "scratch bout" for 3 s out of every 12 s: a fast-moving hind paw near the head
        if (t % 12.0) < 3.0:
            jitter = int(body[1] * 0.8 * math.sin(t * 2 * math.pi * 8))
            cv2.circle(img, (mx + body[0], my + jitter), max(2, body[1] // 3), 255, -1)
        brightness = (self.settings.exposure_us / 4000.0) * (10 ** (self.settings.gain_db / 20.0))
        if abs(brightness - 1.0) > 1e-3:
            img = cv2.convertScaleAbs(img, alpha=max(0.05, min(brightness, 8.0)))
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        text = f"{self.info.serial}  frame {self._n}  {self._label or stamp}"
        scale = max(0.5, self.width / 1600)
        cv2.putText(img, text, (20, int(40 * scale)), cv2.FONT_HERSHEY_SIMPLEX, scale, 255, 2, cv2.LINE_AA)
        return img

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        self._running = False
