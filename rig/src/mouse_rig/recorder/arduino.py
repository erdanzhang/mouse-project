"""USB serial link to the Arduino trigger (optional, used with ``trigger: "line0"``).

With the link, the recorder:
  1. sets the Arduino frame rate to the ``fps`` in recorder.yaml, so they always match;
  2. stops the pulses while it opens the cameras, then starts them again. The first
     pulse after the restart is the first frame of every camera, so the shared
     trigger index is exact (see ``sync.py``).

Without the link (Arduino powered from another USB port, or no pyserial), recording
still works: the trigger index then comes from the frame arrival times.

The sketch ``rig/hardware/sync_trigger/sync_trigger.ino`` answers at 115200 baud:
``<number>`` sets fps, ``s`` stops, ``r`` runs, ``?`` gives the status line
``fps=60 running=yes pulses=1234``.
"""
from __future__ import annotations

import threading
import time

# USB vendor IDs of Arduino boards and common USB-serial chips on clones
_VIDS = {0x2341, 0x2A03, 0x1A86, 0x0403, 0x10C4, 0x067B}


class LinkError(RuntimeError):
    pass


def _parse_status(line: str) -> dict | None:
    if not line.startswith("fps="):
        return None
    out = {}
    for part in line.split():
        key, _, value = part.partition("=")
        out[key] = value
    try:
        return {"fps": int(out.get("fps", 0)), "running": out.get("running") == "yes",
                "pulses": int(out.get("pulses", 0))}
    except ValueError:
        return None


class ArduinoLink:
    def __init__(self, ser, port: str, status: dict):
        self._ser = ser
        self.port = port
        self.state = status
        self._lock = threading.Lock()

    # -- connect ---------------------------------------------------------------
    @classmethod
    def find(cls, port: str | None = "auto", boot_wait: float = 3.0) -> tuple["ArduinoLink | None", str]:
        """Open the trigger Arduino. Returns (link, message); link is None if not found."""
        if port in (None, "", "none", "off", False):
            return None, "serial link off (cameras.arduino_port)"
        try:
            import serial  # noqa: F401
            from serial.tools import list_ports
        except ImportError:
            return None, "pyserial is not installed"
        if port == "auto":
            candidates = [p.device for p in list_ports.comports() if p.vid in _VIDS]
            if not candidates:
                return None, "no Arduino found on a USB serial port"
        else:
            candidates = [str(port)]
        notes = []
        for dev in candidates:
            try:
                link = cls._open(dev, boot_wait)
            except Exception as exc:  # busy port, permission, not our sketch
                notes.append(f"{dev}: {exc}")
                continue
            if link is not None:
                return link, f"Arduino on {dev}"
            notes.append(f"{dev}: no answer from the trigger sketch")
        return None, "; ".join(notes)

    @classmethod
    def _open(cls, dev: str, boot_wait: float) -> "ArduinoLink | None":
        import serial
        ser = serial.Serial(dev, 115200, timeout=0.1, write_timeout=1.0)
        # Opening the port restarts an UNO (about 2 s). The sketch then prints a banner
        # and a status line. Boards that do not restart get a "?" after the wait.
        start = time.time()
        asked = False
        while time.time() - start < boot_wait + 1.5:
            raw = ser.readline()
            status = _parse_status(raw.decode("ascii", "replace").strip()) if raw else None
            if status is not None:
                return cls(ser, dev, status)
            if not asked and time.time() - start > boot_wait:
                ser.write(b"?\n")
                asked = True
        ser.close()
        return None

    # -- commands --------------------------------------------------------------
    def command(self, text: str, timeout: float = 1.0) -> dict:
        with self._lock:
            self._ser.reset_input_buffer()
            self._ser.write(text.encode("ascii") + b"\n")
            end = time.time() + timeout
            while time.time() < end:
                status = _parse_status(self._ser.readline().decode("ascii", "replace").strip())
                if status is not None:
                    self.state = status
                    return status
        raise LinkError(f"no answer from the Arduino on {self.port} to {text!r}")

    def set_fps(self, fps: float) -> dict:
        n = int(round(fps))
        if not 1 <= n <= 200:
            raise LinkError(f"fps {fps} is outside 1..200")
        return self.command(str(n))

    def stop(self) -> dict:
        return self.command("s")

    def run(self) -> dict:
        return self.command("r")

    def status(self) -> dict:
        return self.command("?")

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass

    def info(self) -> dict:
        return {"port": self.port, **self.state}
