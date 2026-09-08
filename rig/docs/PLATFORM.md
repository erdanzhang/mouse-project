# Platform strategy

The pipeline is pure Python/OpenCV/numpy and runs anywhere. Exactly **three**
concerns are platform-specific. Each lives behind an interface, is chosen at
runtime by [`capabilities.probe()`](../src/mouse_rig/capabilities.py), and lazily
imports its heavy/platform dependency — so the base install stays cross-platform
and `import mouse_rig` never pulls in torch or a camera SDK.

Run `mouse-rig report` to see what the current machine supports.

| Concern | Interface | macOS (dev) | Windows / Linux + RTX 5070 |
|---------|-----------|-------------|-----------------------------|
| Frame source | `backends.frame_source.FrameSource` | `FileSource`, `WebcamSource` | `GenICamSource` (real cameras) |
| Video encode | `backends.encoder.Encoder` | `hevc_videotoolbox` / `libx265` / OpenCV | `hevc_nvenc` / `libx265` / OpenCV |
| Model compute | `backends.device.get_torch_device()` | `mps` / `cpu` | `cuda` |

## The rule

- **No `import torch` or camera SDK at module top level.** Platform code is a
  guarded, lazily-imported backend. If a dependency is missing, you get a clear
  error *when you use that path*, not at import.
- **Base install** (`numpy`, `opencv-python`, `pyyaml`) runs `report` and `gate`
  on any OS. `capture` and `models` are optional extras.
- **Feature-detect, don't assume.** `best_available_encoder()` and
  `get_torch_device()` ask the probe; they never hard-code NVENC/CUDA.

## Camera capture (the least portable piece)

Real Hikrobot MV-CS016 cameras speak **GenICam / USB3 Vision**, driven through
[Harvesters](https://github.com/genicam/harvesters) + a **GenTL producer (`.cti`)**
that ships with **Hikvision MVS**. That producer is Windows/Linux — so live
capture happens on the lab PC.

- Install MVS, then point the loader at its `.cti`:
  ```bash
  export GENICAM_GENTL64_PATH=/opt/MVS/lib/64/MvProducerU3V.cti   # Linux example
  pip install -r requirements-capture.txt
  ```
- On **macOS** there is no MVS GenTL producer: develop against `FileSource` /
  `WebcamSource`. Downstream code (gate, tracking, classifier) is identical —
  only the source object changes.

## Video encode

`ffmpeg` is detected on `PATH`; its available encoders decide the default:

- **NVIDIA (RTX 5070)** → `hevc_nvenc` (note: single NVENC engine; fine for 2–4
  1080p streams).
- **Apple Silicon** → `hevc_videotoolbox`.
- **Anywhere with ffmpeg** → `libx265` / `libx264` (CPU).
- **No ffmpeg** → OpenCV `mp4v` writer, so encoding still works.

Override with `mouse-rig gate --encoder <name>`.

## Compute (models, M6+)

`get_torch_device()` returns `cuda` on the RTX 5070, `mps` on Apple Silicon,
else `cpu`. Training realistically wants CUDA; inference and development run fine
on MPS/CPU. torch is only needed once you reach the behavior-model milestones.
