"""Convert raw camera buffers (GenICam PFNC pixel formats) to numpy images.

Mono formats become HxW uint8. Color formats become HxWx3 uint8 in BGR order
(OpenCV convention). The numeric codes are the GenICam PFNC values, which the
Hikrobot MVS SDK also uses (``PixelType_Gvsp_*``).
"""
from __future__ import annotations

import cv2
import numpy as np

MONO8 = 0x01080001
BAYER_GR8 = 0x01080008
BAYER_RG8 = 0x01080009
BAYER_GB8 = 0x0108000A
BAYER_BG8 = 0x0108000B
RGB8 = 0x02180014
BGR8 = 0x02180015

PIXEL_NAMES = {
    MONO8: "Mono8",
    BAYER_GR8: "BayerGR8",
    BAYER_RG8: "BayerRG8",
    BAYER_GB8: "BayerGB8",
    BAYER_BG8: "BayerBG8",
    RGB8: "RGB8Packed",
    BGR8: "BGR8Packed",
}


def _bayer_code(pixel_type: int) -> int:
    # OpenCV names Bayer patterns by the second row, so the sensor pattern
    # RGGB maps to COLOR_BayerBG2BGR. OpenCV >= 4.5 also has explicit aliases.
    table = {
        BAYER_RG8: ("COLOR_BayerRGGB2BGR", "COLOR_BayerBG2BGR"),
        BAYER_GR8: ("COLOR_BayerGRBG2BGR", "COLOR_BayerGB2BGR"),
        BAYER_GB8: ("COLOR_BayerGBRG2BGR", "COLOR_BayerGR2BGR"),
        BAYER_BG8: ("COLOR_BayerBGGR2BGR", "COLOR_BayerRG2BGR"),
    }
    alias, legacy = table[pixel_type]
    return getattr(cv2, alias, getattr(cv2, legacy))


def to_image(data: bytes, width: int, height: int, pixel_type: int) -> np.ndarray:
    """Return a mono (HxW) or BGR (HxWx3) uint8 image for a raw buffer."""
    buf = np.frombuffer(data, dtype=np.uint8)
    n = width * height
    if pixel_type == MONO8:
        return buf[:n].reshape(height, width).copy()
    if pixel_type in (BAYER_GR8, BAYER_RG8, BAYER_GB8, BAYER_BG8):
        raw = buf[:n].reshape(height, width)
        return cv2.cvtColor(raw, _bayer_code(pixel_type))
    if pixel_type == RGB8:
        return np.ascontiguousarray(buf[: n * 3].reshape(height, width, 3)[:, :, ::-1])
    if pixel_type == BGR8:
        return buf[: n * 3].reshape(height, width, 3).copy()
    raise ValueError(
        f"unsupported pixel format 0x{pixel_type:08X}; set pixel_format to Mono8 "
        f"(mono camera) or BayerRG8 (color camera) in recorder.yaml"
    )
