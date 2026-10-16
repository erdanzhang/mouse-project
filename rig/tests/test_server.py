"""Web server tests: the UI page, the status API, preview images, start/stop."""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from mouse_rig.recorder import load_config
from mouse_rig.server import RecorderApp, make_server


@pytest.fixture()
def server(tmp_path):
    cfg = load_config(demo=True)
    cfg["recording"].update(output_dir=str(tmp_path), clip_seconds=1, min_free_gb=0.1)
    cfg["cameras"]["synthetic"].update(count=2, width=320, height=240)
    cfg["cameras"]["default"]["fps"] = 20
    app = RecorderApp(cfg)
    app.startup()
    srv = make_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    time.sleep(0.8)
    yield base, tmp_path
    srv.shutdown()
    app.shutdown()


def _get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def _post(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def test_ui_page(server):
    base, _ = server
    status, ctype, body = _get(base + "/")
    assert status == 200 and "text/html" in ctype
    assert "小鼠行为录制".encode() in body


def test_status_and_preview(server):
    base, _ = server
    st = json.loads(_get(base + "/api/status")[2])
    assert st["recording"]["state"] == "idle"
    assert [c["id"] for c in st["cameras"]] == ["cam-1", "cam-2"]
    assert st["app"]["encoder"]
    status, ctype, jpg = _get(base + "/api/preview/cam-1.jpg")
    assert status == 200 and ctype == "image/jpeg" and jpg[:2] == b"\xff\xd8"


def test_start_stop_recording(server):
    base, out = server
    started = _post(base + "/api/record/start")
    assert started["state"] == "recording"
    time.sleep(2.5)
    st = json.loads(_get(base + "/api/status")[2])
    assert st["recording"]["writers"]["cam-1"]["frames_written"] > 0
    stopped = _post(base + "/api/record/stop")
    assert stopped["state"] == "stopped"
    session_dir = out / stopped["name"]
    assert (session_dir / "session.json").exists()
    assert len(list(session_dir.glob("clip-*/cam-2.mp4"))) >= 2
    sessions = json.loads(_get(base + "/api/sessions")[2])
    assert sessions[0]["name"] == stopped["name"]


def test_settings_and_errors(server):
    base, _ = server
    s = _post(base + "/api/cameras/cam-1/settings", {"exposure_us": 2000, "gain_db": 3})
    assert s["exposure_us"] == 2000 and s["gain_db"] == 3
    with pytest.raises(urllib.error.HTTPError) as err:
        _post(base + "/api/record/stop")
    assert err.value.code == 409
