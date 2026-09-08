"""Mouse detectors.

Two interchangeable backends, both returning per-frame detections as
(xyxy float32 array [N,4], confidence float32 array [N]):

* YoloWorldDetector  - open-vocabulary YOLO-World prompted with "mouse".
                       No training data needed; separates overlapping mice.
* BlobDetector       - classical white-on-dark thresholding + contours.
                       Zero downloads, very fast; may merge touching mice.
"""
from __future__ import annotations

import numpy as np


class YoloWorldDetector:
    def __init__(
        self,
        prompts: list[str] | None = None,
        model_name: str = "yolov8s-world.pt",
        conf: float = 0.02,
        device: str | None = None,
    ) -> None:
        from ultralytics import YOLO

        self.model = YOLO(model_name)
        self.prompts = prompts or ["mouse", "rat", "white mouse", "rodent"]
        self.model.set_classes(self.prompts)
        self.conf = conf
        self.device = device

    def __call__(self, frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        res = self.model.predict(
            frame, conf=self.conf, verbose=False, device=self.device
        )[0]
        if res.boxes is None or len(res.boxes) == 0:
            return np.empty((0, 4), np.float32), np.empty((0,), np.float32)
        xyxy = res.boxes.xyxy.cpu().numpy().astype(np.float32)
        conf = res.boxes.conf.cpu().numpy().astype(np.float32)
        return xyxy, conf


def _bright_mask(frame: np.ndarray):
    """Otsu bright-region mask of a (screen-recorded) frame."""
    import cv2

    gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return mask


def build_static_mask(video: str, samples: int = 30, frac: float = 0.55):
    """Mark pixels that are bright in most frames (static UI: labels, filmstrip).

    Mice move, so they are excluded; the result is an 'ignore' mask we subtract
    from each frame's bright mask, automatically removing screen-recording chrome
    regardless of where it sits.
    """
    import cv2

    cap = cv2.VideoCapture(video)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    acc, cnt = None, 0
    for fi in np.linspace(0, n - 1, min(samples, n)).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(fi))
        ok, fr = cap.read()
        if not ok:
            continue
        m = (_bright_mask(fr) > 0).astype(np.float32)
        acc = m if acc is None else acc + m
        cnt += 1
    cap.release()
    if acc is None:
        return None
    static = ((acc / cnt) > frac).astype(np.uint8) * 255
    return cv2.dilate(static, np.ones((9, 9), np.uint8), iterations=2)


class BlobDetector:
    """Threshold bright mice on a dark arena and emit bounding boxes.

    Static screen-recording chrome is removed via ``ignore_mask``; heavy closing
    merges each mouse's body and tail into one component. The ``top_k`` largest
    valid components are kept (set to the expected number of mice).
    """

    def __init__(
        self,
        ignore_mask: np.ndarray | None = None,
        min_area_frac: float = 0.005,
        max_area_frac: float = 0.30,
        top_k: int = 4,
    ) -> None:
        self.ignore_mask = ignore_mask
        self.min_area_frac = min_area_frac
        self.max_area_frac = max_area_frac
        self.top_k = top_k

    def __call__(self, frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        import cv2

        h, w = frame.shape[:2]
        area = h * w
        mask = _bright_mask(frame)
        if self.ignore_mask is not None:
            mask = cv2.bitwise_and(mask, cv2.bitwise_not(self.ignore_mask))
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8), iterations=2
        )
        # large close to bridge body<->tail and limb gaps into one blob
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_CLOSE, np.ones((21, 21), np.uint8), iterations=2
        )
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        cand = []
        for i in range(1, n):
            x, y, bw, bh, a = stats[i]
            if a < self.min_area_frac * area or a > self.max_area_frac * area:
                continue
            cand.append((a, [x, y, x + bw, y + bh]))
        cand.sort(key=lambda t: -t[0])
        cand = cand[: self.top_k]
        if not cand:
            return np.empty((0, 4), np.float32), np.empty((0,), np.float32)
        boxes = np.array([b for _, b in cand], np.float32)
        # Blob hits are geometric, not probabilistic: give them high, size-
        # scaled confidence so the tracker reliably activates tracks.
        confs = np.array(
            [float(np.clip(0.6 + a / (self.max_area_frac * area), 0.6, 0.99))
             for a, _ in cand],
            np.float32,
        )
        return boxes, confs


def build_detector(
    name: str,
    prompts: list[str] | None,
    conf: float,
    video: str | None = None,
    top_k: int = 4,
):
    name = name.lower()
    if name in ("yoloworld", "yolo-world", "yolo"):
        return YoloWorldDetector(prompts=prompts, conf=conf)
    if name == "blob":
        ignore = build_static_mask(video) if video else None
        return BlobDetector(ignore_mask=ignore, top_k=top_k)
    raise ValueError(f"unknown detector: {name!r} (use 'yoloworld' or 'blob')")
