# Mouse Nose-Scratch Analyzer (POC)

Detects and tracks multiple mice in a video and flags **nose/face scratching**
behavior, producing an annotated video and a JSON report.

- **Goal 1 — tracking:** every mouse gets a colored bounding box + stable ID
  (`mouse 1`, `mouse 2`, …).
- **Goal 2 — scratching:** frames where a mouse is scratching its nose/face are
  drawn with a **red** box labeled `SCRATCHING`.

## How it works

```
video ─▶ detect mice ─▶ track (ByteTrack) ─▶ motion gate ─▶ LLM confirm ─▶ render
         (per frame)     (stable IDs)        (find bursts)   (Claude vision)  (mp4 + json)
```

1. **Detect** — finds mice each frame. Two backends:
   - `blob` *(default)* — classical CV. The input here is a *screen recording*,
     so static UI (labels, the video filmstrip) is auto-removed by an
     "ignore mask" of persistently-bright pixels; the moving white mice remain.
     Body+tail are merged into one box and the largest blobs are kept.
   - `yoloworld` — open-vocabulary YOLO-World prompted with `"mouse"`. Needs no
     training but only works on a clear, close view (it does **not** fire on
     this small top-view footage — kept for clearer recordings).
2. **Track** — [ByteTrack](https://github.com/ifzhang/ByteTrack) assigns stable
   IDs across frames and bridges brief occlusions.
3. **Motion gate** — scratching is a burst of fast, localized motion. Per track
   we measure frame-to-frame change inside the box and pick high-energy windows
   as *candidates*. This is a cheap, high-recall filter — it keeps the number of
   LLM calls small.
4. **LLM confirm** — for each candidate window, a few cropped frames of that one
   mouse are tiled into a montage and sent to **Claude** (vision), which decides
   scratch / not-scratch and returns JSON with a confidence and a reason.
5. **Render** — annotated `.mp4` + a `.json` report of scratch intervals
   (frame ranges + seconds + the model's reason) per mouse.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Put your Anthropic key in `.cred` (already git-ignored):

```
ANTHROPIC_API_KEY=<your-key-here>
```

## Run

```bash
# default: blob detector + Claude confirmation
.venv/bin/python analyze.py data/1139_1782741938.mp4

# outputs/<name>_annotated.mp4  and  outputs/<name>_report.json
```

Useful flags:

| Flag | Default | Meaning |
|------|---------|---------|
| `-o / -r` | `outputs/…` | output video / JSON paths |
| `--detector` | `blob` | `blob` or `yoloworld` |
| `--max-mice` | `4` | max mice kept per frame (blob top-k) |
| `--no-llm` | off | skip Claude; report motion candidates only (fully offline) |
| `--llm-model` | `claude-haiku-4-5-20251001` | vision model for confirmation |
| `--max-llm-calls` | `40` | cap API calls |
| `--motion-percentile` | `90` | lower → more candidate windows (more recall) |
| `--stride` | `1` | process every Nth frame (faster) |
| `--cred` | `.cred` | credentials file |

Run fully offline (no API key needed):

```bash
.venv/bin/python analyze.py data/clip.mp4 --no-llm
```

## Output report

```json
"scratching": {
  "2": [
    {"start": 87, "end": 96, "start_sec": 2.9, "end_sec": 3.2,
     "scratching": true, "confidence": 0.85,
     "reason": "Hind paw raised toward snout across f87-f96 ..."}
  ]
}
```

## Known limitations (POC)

- **ID stability:** the blob detector fragments and merges when the two white
  mice touch, so a mouse may pick up a new ID after an overlap (you'll see more
  IDs than mice). ByteTrack's 2-second memory mitigates but does not eliminate
  this.
- **Detection is appearance-based**, not a trained mouse model — tuned for the
  white-on-dark screen recording in `data/`.
- The motion gate is heuristic; the **LLM is the actual scratch classifier**, so
  quality depends on the chosen model and crop clarity.

## Production upgrade path

- Replace the blob detector with a **fine-tuned mouse detector** (YOLOv8/11 on a
  few hundred labeled frames) for clean, stable boxes and IDs.
- Add **pose estimation** (DeepLabCut / SLEAP) for nose + hind-paw keypoints and
  a geometric scratch rule, or train the
  [Scratch-AID](https://elifesciences.org/articles/84042) CRNN for
  appearance-independent, high-accuracy detection.

## Layout

```
analyze.py                  CLI entrypoint
mouse_analyzer/
  config.py                 .cred loading (secrets never logged)
  detect.py                 BlobDetector + YoloWorldDetector + static-mask calib
  track.py                  ByteTrack wrapper
  scratch_motion.py         motion energy + candidate windows
  scratch_llm.py            Claude vision confirmation (montage -> JSON)
  annotate.py               box / label / HUD drawing
  pipeline.py               4-pass orchestration
```
