"""Compute-device selection for torch models (used from M6 onward).

Kept tiny and lazily-imported so the base install needs no torch. Picks CUDA on
the RTX 5070 PC, MPS on Apple Silicon, else CPU.
"""
from __future__ import annotations


def get_torch_device(prefer: str | None = None):
    """Return a torch.device. Raises a clear error if torch isn't installed."""
    try:
        import torch
    except Exception as exc:
        raise RuntimeError(
            "torch is not installed — install the models extra: "
            "pip install -r requirements-models.txt"
        ) from exc

    if prefer:
        return torch.device(prefer)
    if torch.cuda.is_available():
        return torch.device("cuda")
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")
