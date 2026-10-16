# mouse-project — handoff, progress & tracker

**Purpose:** bootstrap a new session or a second computer with full context. Read this, then `cd rig` and follow "Get started". Design docs are the PDFs in [`docs/`](docs/).

**Updated:** 2026-10-16 · **Type:** personal, non-commercial · **Owner:** erdanzhang · **Repo:** https://github.com/erdanzhang/mouse-project (public)

---

## TL;DR

- **Goal:** multi-camera rig that records mice in a clear glass chamber, tracks each mouse with a stable ID, and auto-flags **nose/face scratching**; a motion "key-pixel" gate drops idle footage to keep storage/analysis cheap.
- **Repo layout:** `rig/` = the real platform-neutral package (`mouse_rig`), `poc/` = the original proof-of-concept, `docs/` = brief PDFs (EN/ZH).
- **Done:** **M0** (platform harness, `mouse-rig report`), **M1** (key-pixel gate, `mouse-rig gate`), and the **recorder service** (`mouse-rig serve`: Chinese web UI, one-click recording, 1-min H.264 clips, Hikrobot MVS backend, Arduino Line0 hardware sync with a shared trigger index, timed recordings that end on a clip boundary, `mouse-rig check`). 37 hardware-free tests. **Hardware-tested 2026-10-16** on the Windows lab PC (2× MV-CS016-10UC, Arduino UNO on COM5, MVS V5.0.2, NVENC): a 5-minute trigger-mode recording gave five 1-minute clips of exactly 3600/3600 frames, identical trigger indices on both cameras, 0 dropped / lost / filled.
- **Installation guide (Chinese):** [`docs/installation-guide.html`](docs/installation-guide.html) — BOM, connection + wiring diagrams, drivers, first run, FAQ, hardware checklist. **Open this first on the hardware PC.**
- **Next (needs hardware):** finish the guide's checklist (section 13) with the final rig — the Arduino-unplug test, a 1-hour run, the mono cameras under 940 nm IR, and 4 cameras on two USB3 controllers.
- **Blocked on hardware:** M2–M5 need the cameras/rig; M6–M7 need live mice.

---

## Progress tracker

| Milestone | What | State |
|---|---|---|
| **M0** | Repo + platform capability harness (`mouse-rig report`) | ✅ done |
| **M1** | Key-pixel gate (`mouse-rig gate`) — any OS | ✅ done |
| **Rec** | Recorder service: web UI, clips, MVS backend, Line0 sync, installers, guide | ✅ hardware-tested 2026-10-16 (2 color cams, 5-min synced run); ☐ 1-hour run, 4 cams |
| M2 | Camera first light + Python grab (MVS) | ✅ 2× MV-CS016-10UC through `cameras/mvs.py` (BayerRG8, 60 fps) |
| M3 | Multi-camera capture + Arduino hardware sync | ✅ 2 cameras frame-locked by the Arduino gate; ☐ 4 cameras |
| M4 | Stereo calibration + triangulation (fuse) | ☐ practice now, real on mounts |
| M5 | Integrated capture dry-run | ☐ needs rig |
| M6 | Behavior model bootstrap (pose + scratch classifier) | ☐ needs mice |
| M7 | Active-learning loop (A-SOiD) | ☐ needs mice + M6 |

**Hardware:** ✅ on hand → 2× Hikrobot **color** cameras with 2× **8 mm** lenses — color cams carry an IR-cut filter, so they're for **visible-light sessions only**; **Arduino UNO** + 6-pin IO cable (**MV-ACC-01-2101**); 2× USB3 cables. ☐ buying now → **2× MV-CS016-10UM mono** (1440×1080, global shutter, USB3, for 940 nm IR) + **2× `MVL-MF0824M-5MPE`** (8 mm, F2.4, 2/3", C-mount, front thread **M35.5×0.5**; same model as the color cams' lenses). **940 nm bandpass filter: optional — skip for now** (expensive; add only if room light leaks in). ☐ pending → **940 nm "无红暴" IR lamps, DC 12 V, always on** — 2 per station at 30–45° from vertical, with a diffuser, over a **matte floor** (dark for white mice, light for black mice); tripods with a boom + 1/4-inch screw; **unmarked glass beakers** (15 & 20 cm); one 6-pin IO cable per camera; a PCIe USB3 card for 4 cameras; **mice** — target **4** systems. Camera height (lens front → beaker floor, 8 mm lens): **≈37 cm** for the 15 cm beaker, **≈49 cm** for 20 cm.

**Trigger wiring (sketch `rig/hardware/sync_trigger/sync_trigger.ino`):** each camera's IO cable → **yellow (pin 2, Line0+) → 470 Ω → Arduino D9 / D10 / D11 / D12**, **green (pin 5, Line0−) → Arduino GND** (all greens joined). **Orange (pin 1) is camera power — never connect it.** Other wires unused, insulated. Verify colors with a multimeter. D9–D12 are one PORTB write, so all cameras fire together; 1 ms pulse; serial 115200 (`<n>` fps, `s` stop, `r` run, `?` status). The recorder sets the Arduino fps from the config and gates the trigger at camera open.

**Compute:** capture + NVENC + training on a **Windows/Ubuntu PC with an RTX 5070** (single NVENC engine). **Mac** for cross-platform dev.

---

## TODO (near-term, actionable — do these next)

- [x] **First hardware test on the Windows lab PC** (2026-10-16) — install script, demo, free-run, Line0 trigger with the Arduino gate, 5-minute timed run → 5 × 3600-frame clips, all `yes`. Fixed on the way: CS-series cameras only have `TriggerSelector=FrameBurstStart`; `check` now accepts a 1–2 frame free-run difference; timed recordings end exactly on a clip boundary.
- [ ] **Finish the hardware checklist:** Arduino-unplug test, 1-hour run (dropped / lost / filled stay 0, no sleep), 4 cameras on two USB3 controllers.
- [ ] **Re-measure data volume** with the mono cameras under IR at low gain. Color cams at 16 dB gain with the new `balanced` (h264_nvenc cq 24, 2026-10-16): ~30–60 MB/min/camera ≈ 2–3.5 GB/h. Measured against a lossless capture: cq 22 → 24 saves 40–50 % for −0.3 VMAF; most bits are sensor noise; HEVC/AV1 were not smaller at equal quality.
- [ ] **Check `quality: small` (cq 26, ~1/3 the size) on real mouse footage** — fine paw/whisker detail during fast scratching — before using it for long recordings.
- [x] **Trigger-index assumptions hold on hardware:** `nFrameNum` gap-free, the gate gives both cameras the same first pulse, camera timestamps step 16.655 ms on both, `missed_trigger_corrections` 0.
- [ ] **Port the POC scratch logic** from `poc/mouse_analyzer/` into `rig/src/mouse_rig/processing/` for M6 (blob + ByteTrack + Claude-vision confirmer).
- [ ] **Practice M4 calibration** with two webcams + a printed ChArUco board to validate triangulation before real cameras.
- [ ] **Finish ordering hardware:** 2× MV-CS016-10UM mono + 2× MVL-MF0824M-5MPE, 940 nm 12 V IR lamps (2 per station) + diffusers, tripods with booms, one 6-pin IO cable per camera, unmarked glass beakers (15 & 20 cm), a PCIe USB3 card. Filters optional (M35.5×0.5). Scale toward **4 systems**.
- [ ] **Build the labeling workflow** — 双K standard (2 annotators independently record scratch-onset time), reconcile disagreements, **target > 70% agreement**; wire the POC Claude auto-labeler to pre-seed labels and cut human load; plan external clinical cross-validation.
- [ ] **Tune the scratch classifier for long, mostly-quiet windows** (guard against long-duration false positives) so observation can extend toward hours.
- [ ] **Post-holiday timeline:** week 1 — build the rig + challenge the mice; week 2 — produce the new labeling video data.

---

## Repo layout

```
mouse-project/
├── README.md              # overview
├── HANDOFF.md             # this file
├── install_windows.bat, start_recorder_windows.bat, start_demo_windows.bat, open_terminal_windows.bat
├── install_mac.command, start_recorder_mac.command, start_demo_mac.command, open_terminal_mac.command
├── docs/                  # installation-guide.html (ZH), img/, brief PDFs EN/ZH
├── rig/                   # the real system (installable package)
│   ├── src/mouse_rig/
│   │   ├── capabilities.py     # runtime probe: OS, ffmpeg encoders, torch device, MVS, GenICam
│   │   ├── cli.py              # `mouse-rig` entrypoint (serve, cameras, record, check, report, gate)
│   │   ├── cameras/            # Camera interface; mvs (Hikrobot), opencv, synthetic (+ virtual Arduino)
│   │   ├── recorder/           # config, ffmpeg, writer (clips), manager, session, sync, arduino
│   │   ├── server/             # web UI (stdlib http.server) + static/index.html (Chinese)
│   │   ├── backends/           # FrameSource (File/Webcam/GenICam), Encoder, device (gate path)
│   │   ├── processing/motion_gate.py   # M1 key-pixel gate
│   │   └── commands/           # recorder, report, gate
│   ├── tests/                  # capabilities, gate, recorder, server, sync (hardware-free)
│   ├── docs/PLATFORM.md        # what's platform-specific + how it's abstracted
│   ├── config/recorder.yaml    # template → recorder.local.yaml (per computer, git-ignored)
│   ├── hardware/sync_trigger/sync_trigger.ino, pyproject.toml, requirements*.txt
└── poc/                   # original proof-of-concept (reference for M6)
    ├── mouse_analyzer/    # blob detector + ByteTrack + Claude scratch confirmer
    ├── analyze.py, requirements.txt, README.md
```

**Not in git** (excluded by size/secrets — bring your own): the sample video, model weights (`*.pt`), virtualenvs, outputs, and `.cred` (API key).

---

## Get started

**Hardware PC (Windows):** clone to `D:\mouse-project`, then follow `docs/installation-guide.html` — double-click `install_windows.bat`, then `start_demo_windows.bat`, then `start_recorder_windows.bat`.

**Developers (any OS):**

```bash
git clone https://github.com/erdanzhang/mouse-project
cd mouse-project/rig
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

mouse-rig report        # NVENC/CUDA on the RTX 5070 PC; VideoToolbox/MPS on a Mac
pytest -q               # 37 passed on any OS (synthetic cameras)
mouse-rig serve --demo  # recorder UI with 2 virtual cameras

# M1 needs a video (sample not in repo — use any .mp4):
mouse-rig gate path/to/clip.mp4 -o gated.mp4
```

For the POC (needs its own key): `cd poc`, `pip install -r requirements.txt`, put `ANTHROPIC_API_KEY=…` in `poc/.cred`, then `python analyze.py <video>`.

---

## Architecture (condensed)

**Hardware:** cameras **top-down** over the glass beaker(s) — ideal adds a bottom view later; mice stay unrestrained — 90° apart → Arduino fires one trigger pulse to every camera `Line0` (hardware sync) → USB3 into one PC → RTX 5070 does NVENC encode + GPU analysis → NVMe. Start 2 cameras, scale to 4 for multi-cage parallel.

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
| Mono vs color | mono for IR; keep the 2 existing color cams for visible-light sessions | color cams have an IR-cut filter → blind at 940 nm; mono has no Bayer filter → more NIR-sensitive and sharper |
| IR wavelength | 940 nm (not 850) | invisible to mice, doesn't disturb circadian rhythm; 850 nm glows red |
| Interface | USB3 | best bandwidth for a compact rig into one PC |
| Scale | 2 → 4 cameras | software is camera-count-agnostic; adding cameras re-runs calibration |
| 3D vs 2D | 2D best-view first, then Anipose 3D | Scratch-AID hit ~97% from one view; 3D is a superset — keep frames synced |
| Compute | RTX 5070 PC (not Mac) | camera SDK + NVENC need it; Mac is for dev |
| Arena | unmarked glass beaker, 1–3 mice each (was acrylic) | better light transmission + easy cleaning; test 15 cm & 20 cm diameters |
| Camera view | start top-down; bottom-view deferred | ideal = top-down + bottom array; keep mice unrestrained to avoid behavior bias |
| Sensitization | continuous/intermittent allergen during dosing | mimic pollen-season exposure; single-dose-then-recover was rejected |
| Test article | the collaborating team's test preparation (details kept private) | efficacy readout = reduced scratching |
| Observation window | ~15 min now, extend later | bottleneck is labeling throughput; want hours for the natural decay curve |
| Labeling | 双K: 2 annotators record scratch-onset time | reconcile disagreements; target >70% agreement |
| Camera count | 4 capture systems (up from 2) | multi-cage parallel recording |
| Licensing | ignore copyleft/AGPL | personal, non-commercial → whole stack free |

---

## Experiment design & plan (2026-09-28 sync)

*Experiment-planning sync between the two collaborating teams. Personal names, the partner institution, and the internal site are omitted from this public file — keep them in private notes if needed.*

**Disease model & test article.** A **chronic allergic-sensitization model** is established. Allergen is dripped into the mouse's nose; symptoms peak in the first ~15 min and ease over time. Mice are **continuously / intermittently sensitized during dosing** to mimic year-round pollen exposure ("treat while irritating") — single-sensitization-then-recover was rejected. The **treatment being dosed is the collaborating team's test preparation** (details kept private; efficacy readout = reduced scratching). The mice used in earlier work are used up, so the model must be **re-established to collect training data**; skip a separate pre-experiment and run **~5 mice with repeated nasal challenge** directly.

**Observation window & the labeling bottleneck.** The literature standard is a **15-min manual-count window**, capped by **manpower** (annotation throughput), not equipment; the team wants **several hours** to see the natural decay curve, but proceeds on the **15-min baseline near-term**. This is exactly what the rig attacks: the **M1 key-pixel gate** cuts the frames a human must review, the **Claude VLM auto-labeler** (POC) pre-seeds labels, and the **A-SOiD active-learning loop (M7)** only asks humans about uncertain clips — shrinking the labeling load so longer windows become feasible. Favor **longer-duration data even if fewer samples** ("few but clean"), and tune the classifier against long-window false positives.

**Capture setup.** Keep mice **unrestrained** (don't restrict movement — intervention biases behavior). **Ideal = a top-down + bottom-view camera array**; **near-term start top-down only** to test the model (bottom-view deferred). Arena switches to an **unmarked (no-graduation) large glass beaker** — better light transmission and easy cleaning than the acrylic bucket; **test 15 cm and 20 cm diameters**. Each chamber holds **1–3 mice**.

**Labeling standard.** Minimal rules: the **双K method** — **2 annotators independently record the scratch-onset time** (~first second of onset); reconcile non-overlapping cases by discussion; **target > 70% inter-annotator agreement**. Plan **external clinical cross-validation**. Budget currently caps it at two annotators ("两K").

**Scale & housing.** **≥6–8 mice per group (ideally 10)**, in **separate cages** for multi-cage parallel recording.

**Hardware plan (confirms + extends this repo's setup).** Cameras: **Hikvision mono + IR + illumination** (matches the 2 already on hand). Color and B/W drivers are interchangeable; **IR mode yields B/W only** — no extra channels to handle. **Buy 4 capture systems** (up from 2) for **multi-cage parallel** recording; **tripods first**, modular fixed boxes later for production. The current stopgap recorder has inadequate quality and duration; the dedicated cameras replace it; compute impact expected small. **Our side owns system adaptation** (this repo).

**Timeline.** Order all hardware **before the early-October holiday**. After the holiday: **week 1 — build the rig + challenge the mice**; **week 2 — produce the new labeling video data**. (Site, ethics, and other logistics are kept in private notes.)

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
- **macOS can't run the real cameras** (no MVS 4.x for macOS) — the recorder runs there in demo/webcam mode; real capture is on the Windows lab PC.
- **Recorder settings** go in `rig/config/recorder.local.yaml` (git-ignored, created by the installer) so `git pull` never conflicts. Web-UI exposure/gain changes are not saved — copy them into that file.
- **Close the MVS client and the Arduino Serial Monitor before starting the recorder** — each holds its device exclusively.
- **Trigger mode needs the Arduino on the recording PC's USB** for the exact gate; without it, camera offsets come from arrival times (works if latency differences stay < half a frame period).
- **Hardware-tested (2026-10-16):** `cameras/mvs.py`, the Arduino serial gate, NVENC, `install_windows.bat` / `start_recorder_windows.bat`. Hikrobot CS-series cameras have no `FrameStart` trigger selector — the backend falls back to `FrameBurstStart` with a burst of 1 frame (same behavior).

---

## Full docs

Architecture, BOM, and the step-by-step bring-up checklist are the PDFs in [`docs/`](docs/): `mouse-scratch-rig-brief-EN.pdf` (13 pp) and `-ZH.pdf` (11 pp). The interactive versions (hardware proposal, brief EN/ZH, bring-up runbook) exist as Claude Artifacts owned by erdanzhang if you have the links.
