# mouse-scratch-rig

Multi-camera capture + analysis rig that tracks mice and automatically flags
**nose/face scratching**, while a motion **key-pixel gate** throws away idle
footage so storage and analysis stay cheap.

Personal, non-commercial project. Platform-neutral: the pipeline is pure
Python/OpenCV and runs on **macOS or Windows/Linux**; the three platform-specific
concerns (camera capture, video encode, model compute) sit behind interfaces that
are feature-detected at runtime — see [`docs/PLATFORM.md`](docs/PLATFORM.md).

> Full context, architecture diagrams, decisions and the milestone plan live in
> the project brief (shared separately). This repo implements it, milestone by
> milestone.

## Status

| Milestone | What | State |
|-----------|------|-------|
| **M0** | Repo + platform capability harness (`mouse-rig report`) | ✅ in this repo |
| **M1** | Key-pixel gate (`mouse-rig gate`) — runs on any OS | ✅ in this repo |
| M2–M5 | Camera bring-up, sync, calibration, dry-run | needs the rig |
| M6–M7 | Behavior model + active-learning loop | needs mice |

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e .                    # base deps only — works everywhere
```

Optional extras, installed only where needed:

```bash
pip install -r requirements-capture.txt   # real cameras (Win/Linux + Hikvision MVS)
pip install -r requirements-models.txt    # pose / behavior models (M6+)
```

`ffmpeg` on `PATH` unlocks hardware H.265 (NVENC on the RTX 5070, VideoToolbox on
a Mac). Without it, the gate falls back to OpenCV's mp4v writer.

## Use

**M0 — what can this machine do?**

```bash
mouse-rig report
```

```
mouse-rig — platform capabilities
──────────────────────────────────────────────
  OS / arch          Darwin / arm64
  ffmpeg encoders    hevc_videotoolbox, libx265, libx264
  torch device       not installed (fine until M6 / models)
  GenICam cameras    no
──────────────────────────────────────────────
  → encoder          hevc_videotoolbox
  → compute device   cpu
```

**M1 — key-pixel gate a clip** (drop idle frames, crop the motion region, re-encode):

```bash
mouse-rig gate path/to/clip.mp4 -o clip_gated.mp4
# force a specific encoder / keep the full frame:
mouse-rig gate clip.mp4 --encoder libx265 --roi none
```

It prints how many frames were kept and the file-size reduction, and writes a
JSON sidecar with the active segments and ROI.

## Test

```bash
pip install pytest
pytest                 # M0 + M1 smoke/e2e tests — pass on any OS
```

## Layout

```
src/mouse_rig/
  capabilities.py        # runtime probe: OS, ffmpeg encoders, torch device, GenICam
  cli.py                 # `mouse-rig` entrypoint
  backends/
    frame_source.py      # FrameSource: File / Webcam / GenICam
    encoder.py           # Encoder: NVENC / VideoToolbox / x265 / OpenCV (+ auto-pick)
    device.py            # get_torch_device(): cuda / mps / cpu
  processing/
    motion_gate.py       # M1 key-pixel gate
  commands/              # report, gate
tests/                   # test_capabilities.py (M0), test_gate.py (M1)
docs/PLATFORM.md         # what's platform-specific and how it's abstracted
config/default.yaml      # rig config template (no secrets)
```

## License

[MIT](LICENSE). Secrets (API keys) go in a git-ignored `.cred` / env vars — never
committed.
