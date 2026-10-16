"""Local web server: camera preview + one-click recording.

Standard library only (``http.server``), so it runs the same on Windows, macOS and
Linux with no web framework to install. Default address: http://127.0.0.1:8765

API
  GET  /                              the web UI
  GET  /api/status                    cameras, recording state, disk, encoder
  GET  /api/sessions                  recent recordings
  GET  /api/preview/<cam-id>.jpg      latest frame of one camera (JPEG)
  POST /api/record/start              start a recording session; JSON {"minutes": 5} stops it
                                      by itself after exactly 5 minutes (0 = until stopped)
  POST /api/record/stop               stop the recording session
  POST /api/cameras/reconnect         close and re-open all cameras (not while recording)
  POST /api/cameras/<cam-id>/settings JSON {"exposure_us": 3000, "gain_db": 6}
  POST /api/open-folder               open the recordings folder in Explorer / Finder
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .. import __version__
from ..recorder.config import output_dir
from ..recorder.ffmpeg import find_ffmpeg, pick_encoder
from ..recorder.manager import CameraManager
from ..recorder.session import RecordingSession

STATIC = Path(__file__).resolve().parent / "static"


class RecorderApp:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.manager = CameraManager(cfg)
        self.session: RecordingSession | None = None
        self.lock = threading.RLock()
        self.encoder = ""
        self.encoder_error = ""
        self.started = time.time()

    # -- lifecycle -------------------------------------------------------------
    def startup(self) -> None:
        try:
            choice = pick_encoder(self.cfg["recording"]["codec"], str(self.cfg["recording"]["encoder"]))
            self.encoder = choice.name
        except Exception as exc:
            self.encoder_error = str(exc)
        self.manager.open_all()

    def shutdown(self) -> None:
        with self.lock:
            if self.session is not None and self.session.state == "recording":
                self.session.stop("server shut down")
            self.manager.close_all()

    # -- actions ---------------------------------------------------------------
    def recording(self) -> bool:
        return self.session is not None and self.session.state in ("recording", "stopping")

    def start_recording(self, minutes: float | None = None) -> dict:
        with self.lock:
            if self.recording():
                raise RuntimeError("a recording is already running")
            session = RecordingSession(self.cfg, self.manager, minutes=minutes)
            session.start()
            self.session = session
            return session.status()

    def stop_recording(self) -> dict:
        with self.lock:
            if self.session is None or self.session.state != "recording":
                raise RuntimeError("no recording is running")
            self.session.stop()
            return self.session.status()

    def reconnect(self) -> None:
        with self.lock:
            if self.recording():
                raise RuntimeError("stop the recording before you reconnect the cameras")
            self.manager.open_all()

    def open_folder(self) -> str:
        path = output_dir(self.cfg)
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return str(path)

    # -- reporting -------------------------------------------------------------
    def status(self) -> dict:
        root = output_dir(self.cfg)
        probe = root
        while not probe.exists() and probe.parent != probe:   # the folder is made at the first recording:
            probe = probe.parent                              # report the drive it will be on
        if not probe.exists():
            probe = Path.home()
        rec = self.cfg["recording"]
        return {
            "app": {
                "version": __version__,
                "platform": f"{platform.system()} {platform.release()}",
                "python": platform.python_version(),
                "config_path": self.cfg.get("_path"),
                "output_dir": str(root),
                "free_gb": round(shutil.disk_usage(probe).free / 1e9, 1),
                "ffmpeg": find_ffmpeg(),
                "encoder": self.encoder,
                "encoder_error": self.encoder_error,
                "clip_seconds": rec["clip_seconds"],
                "container": rec["container"],
                "codec": rec["codec"],
                "quality": rec["quality"],
                "min_free_gb": rec["min_free_gb"],
                "max_minutes": rec.get("max_minutes") or 0,
                "backends": self.cfg["cameras"]["backends"],
                "discovery_errors": self.manager.discovery_errors,
                "sync": self.manager.sync_status(),
            },
            "recording": self.session.status() if self.session is not None else {"state": "idle"},
            "cameras": self.manager.status(),
        }

    def sessions(self, limit: int = 12) -> list[dict]:
        root = output_dir(self.cfg)
        if not root.is_dir():
            return []
        out = []
        for d in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)[:limit]:
            meta = {}
            try:
                meta = json.loads((d / "session.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            out.append({
                "name": d.name,
                "path": str(d),
                "clips": len([c for c in d.iterdir() if c.is_dir() and c.name.startswith("clip-")]),
                "duration_s": meta.get("duration_s"),
                "size_mb": meta.get("size_mb"),
                "state": meta.get("state"),
                "cameras": len(meta.get("cameras", {})),
            })
        return out


def make_handler(app: RecorderApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"mouse-rig/{__version__}"

        def log_message(self, fmt, *args):  # keep the console readable
            pass

        def _json(self, data, status=HTTPStatus.OK):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _error(self, msg, status=HTTPStatus.BAD_REQUEST):
            self._json({"error": msg}, status)

        def do_GET(self):
            path = urlparse(self.path).path
            try:
                if path in ("/", "/index.html"):
                    body = (STATIC / "index.html").read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/api/status":
                    self._json(app.status())
                elif path == "/api/sessions":
                    self._json(app.sessions())
                elif path.startswith("/api/preview/") and path.endswith(".jpg"):
                    cam_id = path[len("/api/preview/"):-len(".jpg")]
                    jpg = app.manager.preview_jpeg(cam_id)
                    if jpg is None:
                        self._error("no frame yet", HTTPStatus.NOT_FOUND)
                        return
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(jpg)))
                    self.end_headers()
                    self.wfile.write(jpg)
                else:
                    self._error("not found", HTTPStatus.NOT_FOUND)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_POST(self):
            path = urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                self._error("request body is not valid JSON")
                return
            try:
                if path == "/api/record/start":
                    self._json(app.start_recording(body.get("minutes")))
                elif path == "/api/record/stop":
                    self._json(app.stop_recording())
                elif path == "/api/cameras/reconnect":
                    app.reconnect()
                    self._json({"ok": True, "cameras": app.manager.status()})
                elif path.startswith("/api/cameras/") and path.endswith("/settings"):
                    cam_id = path[len("/api/cameras/"):-len("/settings")]
                    self._json(app.manager.apply_settings(cam_id, body.get("exposure_us"), body.get("gain_db")))
                elif path == "/api/open-folder":
                    self._json({"path": app.open_folder()})
                else:
                    self._error("not found", HTTPStatus.NOT_FOUND)
            except RuntimeError as exc:
                self._error(str(exc), HTTPStatus.CONFLICT)
            except ValueError as exc:
                self._error(str(exc), HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self._error(f"{type(exc).__name__}: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)

    return Handler


def make_server(app: RecorderApp, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    return server


def serve(cfg: dict, open_browser: bool | None = None) -> int:
    srv_cfg = cfg["server"]
    host, port = srv_cfg["host"], int(srv_cfg["port"])
    app = RecorderApp(cfg)
    print(f"mouse-rig {__version__} recorder")
    print(f"  config      : {cfg.get('_path') or '(built-in defaults)'}")
    print(f"  backends    : {', '.join(cfg['cameras']['backends'])}")
    print(f"  recordings  : {output_dir(cfg)}")
    print("  opening cameras and testing the video encoder ...")
    app.startup()
    print(f"  encoder     : {app.encoder or 'NONE - ' + app.encoder_error}")
    for cam in app.manager.status():
        print(f"  {cam['id']:<6}: {cam['backend']} {cam['model']} serial={cam['serial']} state={cam['state']} {cam['error']}")
    for err in app.manager.discovery_errors:
        print(f"  WARNING     : {err}")
    try:
        server = make_server(app, host, port)
    except OSError as exc:
        app.shutdown()
        print(f"ERROR: cannot listen on {host}:{port} ({exc}). Another recorder may be running, "
              f"or change server.port in recorder.yaml.")
        return 2
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}/"
    print(f"\n  Web UI: {url}\n  Press Ctrl+C here to stop the server (a running recording is saved first).\n")
    want_browser = srv_cfg.get("open_browser", True) if open_browser is None else open_browser
    if want_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    def _graceful(signum, frame):  # SIGTERM / Ctrl+Break: stop like Ctrl+C, so the recording is saved
        raise KeyboardInterrupt
    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), _graceful)
            except (ValueError, OSError):
                pass
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nstopping ...")
    finally:
        server.server_close()
        app.shutdown()
        print("stopped.")
    return 0
