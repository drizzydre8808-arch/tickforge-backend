from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from typing import Protocol

import numpy as np

# Defect vocabulary the rest of the system understands. A trained model should
# emit (or be mapped onto) these labels.
LABELS = (
    "dent", "chip", "scratch", "crack", "rust", "paint_damage",
    "broken_part", "tyre_damage", "glass_damage", "misaligned_panel", "other",
)

# These are at least "moderate" regardless of size.
HIGH_RISK = {"crack", "broken_part", "tyre_damage", "glass_damage", "misaligned_panel", "rust"}


@dataclass
class RawDetection:
    label: str
    score: float                              # 0..1
    box: tuple[float, float, float, float]    # normalised x0, y0, x1, y1
    detector: str = ""
    polygon: Optional[list[tuple[float, float]]] = None   # normalised outline, if the detector gives one
    extra: Optional[dict] = None                           # detector-specific notes (e.g. frames seen)


class Detector(Protocol):
    name: str

    def detect(self, image_bgr: np.ndarray) -> list[RawDetection]: ...


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if inter <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter)


def nms(dets: list[RawDetection], thr: float = 0.4) -> list[RawDetection]:
    out: list[RawDetection] = []
    for d in sorted(dets, key=lambda d: -d.score):
        if all(iou(d.box, k.box) < thr for k in out):
            out.append(d)
    return out
