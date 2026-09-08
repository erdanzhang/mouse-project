# mouse-project

Tools for recording mice in a multi-camera arena, tracking each animal, and
automatically detecting **nose/face scratching** — while a motion "key-pixel"
gate discards idle footage so storage and analysis stay cheap.

Personal, non-commercial project. Two parts live here:

| Dir | What | Status |
|-----|------|--------|
| [`rig/`](rig/) | The capture + analysis rig — platform-neutral package `mouse_rig` (runs on macOS or Windows/Linux). Milestones **M0** (platform harness) and **M1** (key-pixel gate) are done. | active |
| [`poc/`](poc/) | The original proof-of-concept — classical-CV blob detector + ByteTrack + a Claude-vision scratch confirmer, on a single video. Reference for the rig's behavior model (M6). | reference |

**Start here:** [`HANDOFF.md`](HANDOFF.md) — full context, progress tracker, TODO, and get-started steps. Design docs (architecture, decisions, milestones) are the PDFs in [`docs/`](docs/).

## Quick start (the rig)

```bash
cd rig
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e . pytest
mouse-rig report        # what this machine can do (encoders, compute device)
pytest -q               # M0 + M1 tests
mouse-rig gate path/to/clip.mp4 -o gated.mp4   # M1: drop idle frames + crop + re-encode
```

## Notes

- **Secrets:** API keys go in a git-ignored `.cred` (`ANTHROPIC_API_KEY=…`) or env vars — never committed. This is a **public** repo; keep it that way.
- **Not in git:** the sample video, model weights (`*.pt`), virtualenvs, and outputs are excluded by size. Bring your own clip for `mouse-rig gate` / the POC.
- **Hardware:** cameras (Hikrobot MV-CS016-10UM) + Arduino have arrived; IR light, mounts, cylinder, and mice are pending. See `HANDOFF.md` for the full status.

## License

[MIT](LICENSE).
