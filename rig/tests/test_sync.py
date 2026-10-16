"""Hardware-trigger sync tests (no hardware: synthetic cameras + a virtual Arduino).

They check that every camera gets the same trigger index for the same pulse, that
clips are cut by trigger index (same frame count in every camera), that lost frames
are filled, and that the status line of the sketch is parsed.
"""
import csv
import time

from mouse_rig.recorder import CameraManager, RecordingSession, load_config
from mouse_rig.recorder.arduino import _parse_status
from mouse_rig.recorder.sync import TriggerClock

FPS = 50
CLIP_S = 1


# -- TriggerClock -------------------------------------------------------------
def _feed(clock, cams, pulses, period=1 / 60, skip=()):
    """Feed frames for ``pulses`` to every camera; ``skip`` = {(cam, pulse)} with no frame.

    Returns {cam: [(pulse, index)]}. A skipped pulse is a missed trigger: no frame and
    no counter step, but the camera timestamp keeps running.
    """
    out = {c: [] for c in cams}
    counters = {c: 100 * (n + 1) for n, c in enumerate(cams)}    # counters start at different values
    for p in pulses:
        for n, c in enumerate(cams):
            if (c, p) in skip:
                continue
            counters[c] += 1
            t = 1000.0 + p * period + 0.002 * n                   # same pulse: arrivals 2 ms apart
            out[c].append((p, clock.index(c, counters[c], t, int(t * 1e9))))
    return out


def test_clock_arrival_time_alignment():
    clock = TriggerClock(60)
    out = _feed(clock, ["cam-1", "cam-2", "cam-3"], range(200))
    offsets = {p - i for rows in out.values() for p, i in rows[40:]}
    assert len(offsets) == 1


def test_clock_gated_alignment():
    clock = TriggerClock(60)
    clock.arm_gate()
    out = _feed(clock, ["cam-1", "cam-2"], range(10, 100))
    assert out["cam-1"][0][1] == 0 and out["cam-2"][0][1] == 0
    assert all(p - i == 10 for rows in out.values() for p, i in rows)


def test_clock_missed_trigger_is_corrected():
    clock = TriggerClock(60)
    clock.arm_gate()
    out = _feed(clock, ["cam-1", "cam-2"], range(200), skip={("cam-2", 120)})
    assert clock.corrections == 1
    assert all(p - i == 0 for rows in out.values() for p, i in rows)


# -- recording with the virtual Arduino --------------------------------------
def _cfg(tmp_path, drop_every=0, count=3):
    cfg = load_config(demo=True)
    cfg["recording"].update(output_dir=str(tmp_path), clip_seconds=CLIP_S, min_free_gb=0.1)
    cfg["cameras"]["synthetic"].update(count=count, width=320, height=240, drop_every=drop_every)
    cfg["cameras"]["default"].update(fps=FPS, trigger="line0")
    return cfg


def _record(cfg, seconds):
    mgr = CameraManager(cfg)
    mgr.open_all()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not all(s["state"] == "ok" for s in mgr.status()):
            time.sleep(0.1)
        session = RecordingSession(cfg, mgr)
        path = session.start()
        time.sleep(seconds)
        session.stop()
        return path, session, mgr.sync_status()
    finally:
        mgr.close_all()


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_trigger_recording_frame_locked(tmp_path):
    path, session, sync = _record(_cfg(tmp_path, drop_every=40), seconds=CLIP_S * 3 + 0.5)
    assert sync["mode"] == "line0" and sync["gated"]
    clips = sorted(p for p in path.iterdir() if p.is_dir() and p.name.startswith("clip-"))
    assert len(clips) >= 3
    filled = 0
    for n, clip in enumerate(clips):
        tables = [_rows(clip / f"cam-{c}.frames.csv") for c in (1, 2, 3)]
        indices = [[r["trigger_index"] for r in t] for t in tables]
        assert indices[0] == indices[1] == indices[2], clip.name     # same pulses, same order
        if n < len(clips) - 1:
            assert len(indices[0]) == CLIP_S * FPS                   # full clips are exact
        filled += sum(int(r["filled"]) for t in tables for r in t)
    assert filled > 0                                                # lost frames were filled
    meta = session.status()
    assert all(w["frames_filled"] >= 0 for w in meta["writers"].values())


def test_trigger_recording_session_json(tmp_path):
    import json
    path, _, _ = _record(_cfg(tmp_path), seconds=1.2)
    meta = json.loads((path / "session.json").read_text(encoding="utf-8"))
    assert meta["sync"]["mode"] == "hardware trigger (Line0)"
    assert meta["sync"]["frames_per_clip"] == CLIP_S * FPS
    assert meta["sync"]["aligned_by"].startswith("Arduino gate")
    counts = {c["frames_written"] for c in meta["cameras"].values()}
    assert len(counts) == 1                                          # every camera ends on the same pulse


# -- serial link ----------------------------------------------------------------
def test_parse_status():
    assert _parse_status("fps=60 running=yes pulses=12") == {"fps": 60, "running": True, "pulses": 12}
    assert _parse_status("mouse-project trigger ready") is None
