# Platform strategy

The pipeline is pure Python/OpenCV/numpy and runs anywhere. Exactly **three**
concerns are platform-specific. Each lives behind an interface, is chosen at
runtime by [`capabilities.probe()`](../src/mouse_rig/capabilities.py), and lazily
imports its heavy/platform dependency — so the base install stays cross-platform
and `import mouse_rig` never pulls in torch or a camera SDK.

Run `mouse-rig report` to see what the current machine supports.

## Recorder service (`mouse-rig serve`)

The recorder is one Python process with a stdlib web server and a browser UI, so it
runs the same way on Windows and macOS. Only the camera backend and the ffmpeg
encoder change per platform; both are picked at runtime.

| Piece | Windows (lab PC) | macOS | Linux |
|---|---|---|---|
| Web UI, clip writer, `check` | ✅ | ✅ | ✅ |
| Hikrobot cameras (`backends: [mvs]`) | ✅ MVS 4.x Python wrapper (`MvImport`, ctypes → `MvCameraControl.dll`) | ❌ no MVS 4.x for macOS | ✅ `/opt/MVS` (`libMvCameraControl.so`) |
| USB webcams (`backends: [opencv]`) | ✅ DirectShow | ✅ AVFoundation | ✅ V4L2 |
| Demo cameras (`--demo`) | ✅ | ✅ | ✅ |
| Arduino trigger link (pyserial) | ✅ COMn | ✅ /dev/cu.usbmodem* | ✅ /dev/ttyACM* |
| Encoder (`encoder: auto`, real test-encode) | `h264_nvenc` → `h264_qsv` → `libx264` | `h264_videotoolbox` → `libx264` | `h264_nvenc` → `h264_qsv` → `libx264` |
| ffmpeg source | `MOUSE_RIG_FFMPEG` → `PATH` → bundled `imageio-ffmpeg` | same | same |
| Keep awake while recording | `SetThreadExecutionState` | `caffeinate -i` | — |

**MVS backend** (`cameras/mvs.py`): finds the MVS Python wrapper in the default
install folder (`C:\Program Files (x86)\MVS\Development\Samples\Python\MvImport`,
`/opt/MVS/Samples/64/Python/MvImport`), or in `cameras.mvs_python_path` /
`MVS_PYTHON_PATH`. It needs 64-bit Python. Per camera it sets PixelFormat (Mono8 or
Bayer 8-bit), exposure, gain, and either free-run (`AcquisitionFrameRate`) or
`TriggerMode On, TriggerSource Line0, RisingEdge`.

**Sync** (`recorder/sync.py`, `recorder/arduino.py`): with `trigger: "line0"` the
recorder stops the Arduino over USB serial, opens the cameras, then restarts it, so
the first pulse is frame 1 in every camera. Each frame gets a shared trigger index;
clips are cut by index (`clip_seconds × fps` frames), and lost frames are filled
with the previous image (`filled=1` in `frames.csv`). Without the serial link, the
offset between camera counters comes from frame arrival times (less robust).

The older `backends/frame_source.GenICamSource` (Harvesters + GenTL `.cti`) below is
kept for the gate/analysis path; the recorder uses the MVS backend.

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
