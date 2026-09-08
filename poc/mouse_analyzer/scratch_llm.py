"""Confirm candidate scratch windows with Claude vision.

For each candidate window we sample a few frames, crop the tracked mouse (with
padding), tile them into a single montage image, and ask Claude whether the
mouse is scratching its face/nose with a hind paw. The model returns strict
JSON so the result is machine-readable.

The montage (time-lapse strip) lets the model judge the rhythmic hind-paw
motion that defines scratching, not just a single static pose.
"""
from __future__ import annotations

import base64
import json

import cv2
import numpy as np

PROMPT = """You are analyzing a lab mouse for NOSE/FACE SCRATCHING behavior.

The image is a time-ordered montage (left-to-right, top-to-bottom) of cropped
frames of ONE mouse over a fraction of a second. Frame numbers are labeled.

Nose/face scratching = a HIND paw is rapidly/rhythmically raised to and flicked
against the snout, nose, ear, or face. It is distinct from walking, grooming
with the front paws, rearing, resting, or simply turning.

Judge the SEQUENCE, not one frame. Reply with ONLY a JSON object:
{"scratching": true|false, "confidence": 0.0-1.0, "reason": "<short>"}"""


def _montage(crops: list[np.ndarray], labels: list[str], cell: int = 224) -> np.ndarray:
    n = len(crops)
    cols = min(4, n)
    rows = (n + cols - 1) // cols
    canvas = np.zeros((rows * cell, cols * cell, 3), np.uint8)
    for i, (crop, label) in enumerate(zip(crops, labels)):
        r, c = divmod(i, cols)
        h, w = crop.shape[:2]
        scale = cell / max(h, w)
        rs = cv2.resize(crop, (max(1, int(w * scale)), max(1, int(h * scale))))
        rh, rw = rs.shape[:2]
        y0, x0 = r * cell + (cell - rh) // 2, c * cell + (cell - rw) // 2
        canvas[y0 : y0 + rh, x0 : x0 + rw] = rs
        cv2.putText(
            canvas, label, (c * cell + 4, r * cell + 18),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA,
        )
    return canvas


def _b64_jpeg(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("failed to encode montage")
    return base64.b64encode(buf.tobytes()).decode()


class LlmScratchConfirmer:
    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001"):
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def confirm(self, crops: list[np.ndarray], frame_labels: list[str]) -> dict:
        montage = _montage(crops, frame_labels)
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg",
                        "data": _b64_jpeg(montage)}},
                    {"type": "text", "text": PROMPT},
                ],
            }],
        )
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        return _parse(text)


def _parse(text: str) -> dict:
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        data = json.loads(text[start:end])
        return {
            "scratching": bool(data.get("scratching", False)),
            "confidence": float(data.get("confidence", 0.0)),
            "reason": str(data.get("reason", ""))[:200],
        }
    except (ValueError, json.JSONDecodeError):
        return {"scratching": False, "confidence": 0.0,
                "reason": f"unparseable: {text[:80]}"}
