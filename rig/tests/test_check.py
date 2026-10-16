"""`mouse-rig check` verdicts on hand-made session folders (no video needed)."""
import argparse
import csv
import json

from mouse_rig.commands.recorder import run_check


def _session(tmp_path, mode, counts):
    s = tmp_path / "2026-10-16-120000"
    clip = s / "clip-2026-10-16-120000"
    clip.mkdir(parents=True)
    cams = {}
    for n, count in enumerate(counts, start=1):
        cams[f"cam-{n}"] = {"serial": f"S{n}"}
        with open(clip / f"cam-{n}.frames.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["frame_in_clip"])
            w.writerows([[i] for i in range(count)])
    (s / "session.json").write_text(json.dumps({"sync": {"mode": mode}, "cameras": cams}), encoding="utf-8")
    return s


def _check(session):
    return run_check(argparse.Namespace(session=str(session), config=None, decode=False))


def test_free_run_allows_small_difference(tmp_path, capsys):
    assert _check(_session(tmp_path, "free-run", [3601, 3600])) == 0
    assert "yes (free-run, 1 apart)" in capsys.readouterr().out


def test_free_run_large_difference_fails(tmp_path):
    assert _check(_session(tmp_path, "free-run", [3600, 3590])) == 2


def test_trigger_mode_needs_equal_counts(tmp_path):
    assert _check(_session(tmp_path, "hardware trigger (Line0)", [3601, 3600])) == 2


def test_trigger_mode_equal_counts_pass(tmp_path):
    assert _check(_session(tmp_path, "hardware trigger (Line0)", [3600, 3600])) == 0
