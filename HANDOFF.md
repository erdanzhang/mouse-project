# mouse-project — handoff, progress & tracker

**Purpose:** bootstrap a new session or a second computer with full context. Read this, then `cd rig` and follow "Get started". Design docs are the PDFs in [`docs/`](docs/).

**Updated:** 2026-09-08 · **Type:** personal, non-commercial · **Owner:** erdanzhang · **Repo:** https://github.com/erdanzhang/mouse-project (public)

---

## TL;DR

- **Goal:** multi-camera rig that records mice in a clear cylinder, tracks each mouse with a stable ID, and auto-flags **nose/face scratching**; a motion "key-pixel" gate drops idle footage to keep storage/analysis cheap.
- **Repo layout:** `rig/` = the real platform-neutral package (`mouse_rig`), `poc/` = the original proof-of-concept, `docs/` = brief PDFs (EN/ZH).
- **Done:** **M0** (platform harness, `mouse-rig report`) and **M1** (key-pixel gate, `mouse-rig gate`) — tested, cross-platform.
- **Next (no hardware needed):** harden `GenICamSource`, scaffold M3 (dual capture + Arduino sync), port the POC scratch logic into `rig/`. See TODO below.
- **Blocked on hardware:** M2–M5 need the cameras/rig; M6–M7 need live mice.

---

## Progress tracker

| Milestone | What | State |
|---|---|---|
| **M0** | Repo + platform capability harness (`mouse-rig report`) | ✅ done |
| **M1** | Key-pixel gate (`mouse-rig gate`) — any OS | ✅ done |
| M2 | Camera first light + Python grab (GenICam) | ☐ needs cameras |
| M3 | Dual capture + Arduino hardware sync | ☐ needs cameras (scaffold now) |
| M4 | Stereo calibration + triangulation (fuse) | ☐ practice now, real on mounts |
| M5 | Integrated capture dry-run | ☐ needs rig |
| M6 | Behavior model bootstrap (pose + scratch classifier) | ☐ needs mice |
| M7 | Active-learning loop (A-SOiD) | ☐ needs mice + M6 |

**Hardware:** ✅ arrived → 2× Hikrobot **MV-CS016-10UM** (mono global-shutter, Sony **IMX296**, 1.6 MP), 2× C-mount **6–8 mm** lenses, **Arduino UNO** + 6-pin IO cable (**MV-ACC-01-2101**), 2× USB3 cables. ☐ pending → **940 nm IR** light, mounts/rail, acrylic **cylinder Ø30×50 cm**, **mice**.

**Compute:** capture + NVENC + training on a **Windows/Ubuntu PC with an RTX 5070** (single NVENC engine). **Mac** for cross-platform dev.

---

## TODO (near-term, actionable — do these next)

- [ ] **Harden `GenICamSource`** (`rig/src/mouse_rig/backends/frame_source.py`) against a real MV-CS016-10UM via Harvesters + the Hikvision MVS GenTL `.cti`. Currently best-effort, not yet run on hardware.
- [ ] **Scaffold M3** — a `capture-dual` command (open two sources by serial, write both streams with a shared frame index) + a `sync-check` (verify same-index frames match on a known LED/timer signal).
- [ ] **Port the POC scratch logic** from `poc/mouse_analyzer/` into `rig/src/mouse_rig/processing/` for M6 (blob + ByteTrack + Claude-vision confirmer).
- [ ] **Practice M4 calibration** with two webcams + a printed ChArUco board to validate triangulation before real cameras.
- [ ] **When hardware arrives:** install MVS on the RTX 5070 PC, wire the Arduino trigger (`rig/hardware/sync_trigger.ino`), do first light per camera, then dual sync. Follow the bring-up runbook.
- [ ] **Buy the pending hardware** (940 nm IR + diffuser, mounts/rail, cylinder) — see the hardware proposal PDF/artifact.

---

## Repo layout

```
mouse-project/
├── README.md              # overview
├── HANDOFF.md             # this file
├── docs/                  # mouse-scratch-rig-brief-EN.pdf, -ZH.pdf (architecture, decisions, milestones)
├── rig/                   # the real system (installable package)
│   ├── src/mouse_rig/
│   │   ├── capabilities.py     # runtime probe: OS, ffmpeg encoders, torch device, GenICam
│   │   ├── cli.py              # `mouse-rig` entrypoint (report, gate)
│   │   ├── backends/           # FrameSource (File/Webcam/GenICam), Encoder (NVENC/VideoToolbox/x265/OpenCV), device
│   │   ├── processing/motion_gate.py   # M1 key-pixel gate
│   │   └── commands/           # report, gate
│   ├── tests/                  # test_capabilities.py (M0), test_gate.py (M1)
│   ├── docs/PLATFORM.md        # what's platform-specific + how it's abstracted
│   ├── config/default.yaml, hardware/sync_trigger.ino, pyproject.toml, requirements*.txt
└── poc/                   # original proof-of-concept (reference for M6)
    ├── mouse_analyzer/    # blob detector + ByteTrack + Claude scratch confirmer
    ├── analyze.py, requirements.txt, README.md
```

**Not in git** (excluded by size/secrets — bring your own): the sample video, model weights (`*.pt`), virtualenvs, outputs, and `.cred` (API key).

---

## Get started

```bash
git clone https://github.com/erdanzhang/mouse-project
cd mouse-project/rig
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e . pytest

mouse-rig report        # NVENC/CUDA on the RTX 5070 PC; VideoToolbox/MPS on a Mac
pytest -q               # 4 passed on any OS

# M1 needs a video (sample not in repo — use any .mp4):
mouse-rig gate path/to/clip.mp4 -o gated.mp4
```

For the POC (needs its own key): `cd poc`, `pip install -r requirements.txt`, put `ANTHROPIC_API_KEY=…` in `poc/.cred`, then `python analyze.py <video>`.

---

## Architecture (condensed)

**Hardware:** cameras high around the cylinder, angled top-down, 90° apart → Arduino fires one trigger pulse to every camera `Line0` (hardware sync) → USB3 into one PC → RTX 5070 does NVENC encode + GPU analysis → NVMe. Start 2 cameras, scale to 4.

**Software:** capture (synced) → **① key-pixel gate** (motion + ROI crop) → **encode/store** (H.265/NVENC) → **② track & fuse** (SLEAP per view → Anipose 3D, or YOLO/ByteTrack) → **③ scratch classifier** (IDs + timestamps) → low-confidence clips → **human label & retrain** (A-SOiD) → back to classifier.

**Platform-neutrality (hard requirement):** three concerns behind interfaces, feature-detected at runtime by `capabilities.probe()`; base install runs anywhere, heavy/platform deps are lazily imported.

| Concern | Interface | macOS (dev) | Windows/Linux + RTX 5070 |
|---|---|---|---|
| Frame source | `FrameSource` | File / Webcam | GenICam (Harvesters) |
| Video encode | `Encoder` | VideoToolbox / x265 | NVENC / x265 |
| Model compute | `get_device()` | MPS / CPU | CUDA |

---

## Key decisions

| Decision | Choice | Why |
|---|---|---|
| Detector (start) | blob + Claude VLM; YOLO/SLEAP later | YOLO-World failed on the screen-recorded sample; blob+VLM needs no labels |
| Camera shutter | global shutter | scratching is fast; rolling shutter smears the paw |
| Mono vs color | mono (for IR) | under 940 nm IR a color sensor gives no real color and is dimmer/softer |
| IR wavelength | 940 nm (not 850) | invisible to mice, doesn't disturb circadian rhythm; 850 nm glows red |
| Interface | USB3 | best bandwidth for a compact rig into one PC |
| Scale | 2 → 4 cameras | software is camera-count-agnostic; adding cameras re-runs calibration |
| 3D vs 2D | 2D best-view first, then Anipose 3D | Scratch-AID hit ~97% from one view; 3D is a superset — keep frames synced |
| Compute | RTX 5070 PC (not Mac) | camera SDK + NVENC need it; Mac is for dev |
| Licensing | ignore copyleft/AGPL | personal, non-commercial → whole stack free |

---

## OSS stack (all free for this project)

Harvesters+GenICam (capture), Hikvision MVS (driver/GenTL), OpenCV (gate/calibration/triangulation), FFmpeg (encode), **SLEAP**/DeepLabCut (pose), **Anipose** (3D triangulation), ByteTrack (IDs), **A-SOiD** (active learning), SimBA/BORIS/DeepEthogram (labeling+classifiers), Scratch-AID (reference scratch CRNN), Claude API (VLM auto-labeler). Reference rig: the published **Anipose "Quadrascopic"** cylinder setup.

---

## Gotchas & constraints

- **Public repo** — keep secrets out. Keys go in git-ignored `.cred`/env vars; the receiving machine needs its own `ANTHROPIC_API_KEY`.
- **M1 byte-savings depend on input bitrate.** On the already-compressed screen-recording sample the gated file *grew* ~17%; on a high-bitrate (camera-like) baseline the same gate cut **43 MB → 818 KB (98%)**. The input-independent metric is **frames kept** (~80% dropped on that sample).
- **RTX 5070 has one NVENC engine** — fine for 2–4 × 1080p; 5070 Ti/5080 (dual) if high-fps 3D + live encode ever run together.
- **Calibration is only valid while cameras don't move**; **IR shifts focus** (refocus when 940 nm replaces room light).
- **Animal welfare:** clear the setup (esp. continuous IR) with local animal-care / vet / IACUC before any mice.
- **macOS can't run the real cameras** (no MVS GenTL producer) — dev against file/webcam, run GenICam on the lab PC.

---

## Full docs

Architecture, BOM, and the step-by-step bring-up checklist are the PDFs in [`docs/`](docs/): `mouse-scratch-rig-brief-EN.pdf` (13 pp) and `-ZH.pdf` (11 pp). The interactive versions (hardware proposal, brief EN/ZH, bring-up runbook) exist as Claude Artifacts owned by erdanzhang if you have the links.
