"""Capture-quality helpers: sharpness / motion-blur filtering and resolution limits."""
from __future__ import annotations

import cv2
import numpy as np


def sharpness(img_bgr: np.ndarray, max_side: int = 1000) -> float:
    """Variance of the Laplacian on a downscaled grey image. Higher = sharper.

    Only meaningful for comparing frames of the same scene (e.g. frames of one
    video pass), not as an absolute number across scenes.
    """
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    k = min(1.0, max_side / max(g.shape[:2]))
    if k < 1:
        g = cv2.resize(g, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def select_sharp(frames: list[np.ndarray], keep: float = 0.7, min_keep: int = 3,
                 min_ratio: float = 0.35) -> list[int]:
    """Indices of the frames worth analysing.

    Drops frames whose sharpness is far below the best frame (motion blur from a
    handheld pan, rolling-shutter smear) and keeps at most the sharpest `keep`
    fraction. Always returns at least `min_keep` frames if there are that many.
    Returned in original (time) order.
    """
    if not frames:
        return []
    scores = np.array([sharpness(f) for f in frames])
    order = np.argsort(-scores)
    n_keep = max(min_keep, int(round(len(frames) * keep)))
    chosen = [int(i) for i in order[:n_keep] if scores[i] >= min_ratio * scores[order[0]]]
    if len(chosen) < min(min_keep, len(frames)):
        chosen = [int(i) for i in order[:min(min_keep, len(frames))]]
    return sorted(chosen)


def min_detectable_mm(mm_per_px: float, px: float = 3.0) -> float:
    """Smallest feature we can honestly claim to resolve: ~3 pixels across."""
    return round(mm_per_px * px, 2)


def mm_per_px_for(view: str, frame_box: tuple[float, float, float, float], img_w: int,
                  length_mm: float, width_mm: float) -> float | None:
    """Scale from known vehicle size, for straight-on views only."""
    if view in ("nearside", "offside"):
        real = length_mm
    elif view in ("front", "rear"):
        real = width_mm
    else:
        return None
    px = (frame_box[2] - frame_box[0]) * img_w
    return real / px if px > 0 else None
