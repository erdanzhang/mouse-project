# mouse-project

Tools for recording mice in a multi-camera arena, tracking each animal, and
automatically detecting **nose/face scratching** — while a motion "key-pixel"
gate discards idle footage so storage and analysis stay cheap.

Personal, non-commercial project. Two parts live here:

| Dir | What | Status |
|-----|------|--------|
| [`rig/`](rig/) | The capture + analysis rig — platform-neutral package `mouse_rig` (runs on macOS or Windows/Linux). Done: **M0** (platform harness), **M1** (key-pixel gate), and the **recorder service** (web UI, one-click multi-camera recording, 1-min clips, Arduino hardware sync). | active |
| [`poc/`](poc/) | The original proof-of-concept — classical-CV blob detector + ByteTrack + a Claude-vision scratch confirmer, on a single video. Reference for the rig's behavior model (M6). | reference |

**Start here:** [`HANDOFF.md`](HANDOFF.md) — full context, progress tracker, TODO, and get-started steps. Design docs (architecture, decisions, milestones) are the PDFs in [`docs/`](docs/).

**Installing the recording rig?** Open [`docs/installation-guide.html`](docs/installation-guide.html) (Chinese) in a browser: hardware, wiring diagrams, drivers, first run, checklist.

## Recorder (one click)

| Step | Windows | macOS (demo / analysis only) |
|---|---|---|
| Install | double-click `install_windows.bat` | double-click `install_mac.command` |
| Try without cameras | `start_demo_windows.bat` | `start_demo_mac.command` |
| Record with cameras | `start_recorder_windows.bat` | — (no Hikrobot MVS for macOS) |
| Command window (`mouse-rig cameras`, `mouse-rig check`) | `open_terminal_windows.bat` | `open_terminal_mac.command` |

The recorder opens `http://127.0.0.1:8765`. Click **开始录制** (optionally fill in **定时 N 分钟** first: the recording then stops by itself after exactly N minutes = N full clips); every camera writes
`<output_dir>/YYYY-MM-DD-HHMMSS/clip-YYYY-MM-DD-HHMMSS/cam-N.mp4` (+ `cam-N.frames.csv`), one clip per minute.
Settings live in `rig/config/recorder.local.yaml` (created by the installer, not in git).

## Quick start (developers)

```bash
cd rig
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e . pytest
mouse-rig report        # what this machine can do (encoders, compute device)
pytest -q               # all tests (synthetic cameras, no hardware)
mouse-rig serve --demo  # recorder web UI with 2 virtual cameras
mouse-rig gate path/to/clip.mp4 -o gated.mp4   # M1: drop idle frames + crop + re-encode
```

## Notes

- **Secrets:** API keys go in a git-ignored `.cred` (`ANTHROPIC_API_KEY=…`) or env vars — never committed. This is a **public** repo; keep it that way.
- **Not in git:** the sample video, model weights (`*.pt`), virtualenvs, and outputs are excluded by size. Bring your own clip for `mouse-rig gate` / the POC.
- **Hardware:** 2 Hikrobot color cameras + Arduino on hand; 2× MV-CS016-10UM mono, 8 mm lenses (MVL-MF0824M-5MPE), 940 nm IR lamps, tripods, and glass beakers being bought. See `HANDOFF.md` for the full status.

## License

[MIT](LICENSE).
