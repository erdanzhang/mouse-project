"""Recorder commands: ``serve`` (web UI), ``cameras`` (list), ``record`` (headless)."""
from __future__ import annotations

import time


def _common(p):
    p.add_argument("--config", help="path to recorder.yaml (default: rig/config/recorder.yaml)")
    p.add_argument("--demo", action="store_true",
                   help="use synthetic test cameras instead of real ones (no hardware needed)")


def add_parsers(sub):
    p = sub.add_parser("serve", help="start the recorder web UI (preview + one-click recording)")
    _common(p)
    p.add_argument("--host", help="listen address (default from config: 127.0.0.1)")
    p.add_argument("--port", type=int, help="port (default from config: 8765)")
    p.add_argument("--no-browser", action="store_true", help="do not open the web browser")
    p.add_argument("--output", help="recordings folder (overrides recording.output_dir)")
    p.set_defaults(func=run_serve)

    p = sub.add_parser("cameras", help="list the cameras this computer can see")
    _common(p)
    p.set_defaults(func=run_cameras)

    p = sub.add_parser("record", help="record without the web UI (for tests and scripts)")
    _common(p)
    p.add_argument("--seconds", type=float, required=True, help="how long to record")
    p.add_argument("--clip-seconds", type=float, help="override recording.clip_seconds")
    p.add_argument("--output", help="recordings folder (overrides recording.output_dir)")
    p.set_defaults(func=run_record)


def _load(args):
    from ..recorder.config import load_config
    cfg = load_config(args.config, demo=args.demo)
    if getattr(args, "output", None):
        cfg["recording"]["output_dir"] = args.output
    return cfg


def run_serve(args) -> int:
    from ..server import serve
    cfg = _load(args)
    if args.host:
        cfg["server"]["host"] = args.host
    if args.port:
        cfg["server"]["port"] = args.port
    return serve(cfg, open_browser=False if args.no_browser else None)


def run_cameras(args) -> int:
    from ..recorder.manager import CameraManager
    cfg = _load(args)
    mgr = CameraManager(cfg)
    infos = mgr.discover()
    print(f"backends: {', '.join(cfg['cameras']['backends'])}")
    for err in mgr.discovery_errors:
        print(f"  ERROR {err}")
    if not infos:
        print("no camera found")
        return 1
    for n, info in enumerate(infos, start=1):
        kind = "color" if info.is_color else "mono"
        print(f"  cam-{n}: backend={info.backend} model={info.model or '?'} serial={info.serial} "
              f"{kind} {('name=' + info.name) if info.name else ''}")
    print("\nTip: copy the serial numbers into cameras.order in rig/config/recorder.local.yaml to fix the cam-N order.")
    return 0


def run_record(args) -> int:
    from ..recorder.manager import CameraManager
    from ..recorder.session import RecordingSession
    cfg = _load(args)
    if args.clip_seconds:
        cfg["recording"]["clip_seconds"] = args.clip_seconds
    mgr = CameraManager(cfg)
    mgr.open_all()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not any(s["state"] == "ok" for s in mgr.status()):
            time.sleep(0.2)
        for cam in mgr.status():
            print(f"{cam['id']}: {cam['state']} {cam['serial']} {cam['error']}")
        session = RecordingSession(cfg, mgr)
        path = session.start()
        print(f"recording to {path} with {session.encoder} for {args.seconds:g} s ...")
        try:
            time.sleep(args.seconds)
        except KeyboardInterrupt:
            pass
        session.stop()
        st = session.status()
        for cam_id, w in st["writers"].items():
            print(f"{cam_id}: {w['frames_written']} frames, {w['clips']} clips, "
                  f"{w['frames_dropped']} dropped, errors={w['errors']}")
        print(f"done: {path} ({st['size_mb']} MB)")
        return 0
    finally:
        mgr.close_all()


def add_check_parser(sub):
    p = sub.add_parser("check", help="verify a recording: frames per camera per clip")
    p.add_argument("session", nargs="?", help="session folder (default: the newest one)")
    p.add_argument("--config", help="path to recorder.yaml (used to find the newest session)")
    p.add_argument("--decode", action="store_true", help="also decode every video and count its frames (slow)")
    p.set_defaults(func=run_check)


def run_check(args) -> int:
    import csv
    import json
    from pathlib import Path

    from ..recorder.config import load_config, output_dir

    if args.session:
        session = Path(args.session).expanduser()
    else:
        root = output_dir(load_config(args.config))
        found = sorted((p for p in root.iterdir() if p.is_dir()), reverse=True) if root.is_dir() else []
        if not found:
            print(f"no session folder in {root}")
            return 1
        session = found[0]
    meta = {}
    if (session / "session.json").is_file():
        meta = json.loads((session / "session.json").read_text(encoding="utf-8"))
    cams = sorted(meta.get("cameras", {}).keys()) or sorted(
        {p.name.split(".")[0] for p in session.glob("clip-*/cam-*.frames.csv")})
    print(f"session : {session}")
    if meta:
        print(f"state   : {meta.get('state')}  duration {meta.get('duration_s')} s  encoder {meta.get('encoder')}"
              f"  size {meta.get('size_mb')} MB")
        sync = meta.get("sync") or {}
        print(f"sync    : {sync.get('mode', '?')}"
              + (f"  aligned by {sync.get('aligned_by')}  frames/clip {sync.get('frames_per_clip')}"
                 f"  trigger {sync.get('measured_trigger_fps')} fps"
                 f"  missed-trigger corrections {sync.get('missed_trigger_corrections')}"
                 if "frames_per_clip" in sync else ""))
        for cam_id in cams:
            c = meta["cameras"].get(cam_id, {})
            print(f"{cam_id:<8}: serial {c.get('serial')}  {c.get('width')}x{c.get('height')}  "
                  f"measured {c.get('measured_fps')} fps  dropped(queue) {c.get('frames_dropped')}  "
                  f"lost(camera) {c.get('camera_lost_frames')}  filled {c.get('frames_filled', 0)}")
    print()
    print("clip".ljust(26) + "".join(c.ljust(12) for c in cams) + "same?")
    problems = 0
    for clip in sorted(p for p in session.iterdir() if p.is_dir() and p.name.startswith("clip-")):
        counts = []
        for cam_id in cams:
            csv_path = clip / f"{cam_id}.frames.csv"
            if not csv_path.exists():
                counts.append(None)
                continue
            with open(csv_path, newline="", encoding="utf-8") as fh:
                n = max(0, sum(1 for _ in csv.reader(fh)) - 1)
            if args.decode:
                import cv2
                video = next(clip.glob(f"{cam_id}.mp4"), None) or next(clip.glob(f"{cam_id}.mkv"), None)
                cap = cv2.VideoCapture(str(video)) if video else None
                v = 0
                while cap is not None and cap.read()[0]:
                    v += 1
                n = f"{n}/{v}"
            counts.append(n)
        ok = None not in counts and len({str(c) for c in counts}) <= 1
        problems += 0 if ok else 1
        print(clip.name.ljust(26) + "".join(str("missing" if c is None else c).ljust(12) for c in counts)
              + ("yes" if ok else "NO"))
    print("\nFull clips should hold clip_seconds x fps frames (60 s x 60 fps = 3600)."
          "\nTrigger mode (line0): every camera must show the same count in every clip;"
          "\n  'filled' = frames the camera lost, replaced by a copy of the previous frame."
          "\nFree-run mode: a difference of 1-2 frames between cameras is normal.")
    return 0 if problems == 0 else 2
