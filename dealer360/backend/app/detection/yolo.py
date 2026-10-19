"""Adapter for a trained Ultralytics YOLO model.

This is the path to real accuracy: train a detector on labelled vehicle damage
images (your own dealer photos plus public sets such as CarDD), point
DEALER360_YOLO_WEIGHTS at the .pt file, and the pipeline uses it instead of the
classical fallback. Class names are mapped onto our label vocabulary.

    pip install ultralytics
"""
from __future__ import annotations

import numpy as np

from .base import LABELS, RawDetection

# Lower-case model class name -> our label. Extend to match your training set.
DEFAULT_CLASS_MAP = {
    "dent": "dent", "scratch": "scratch", "crack": "crack", "rust": "rust",
    "paint": "paint_damage", "paint_damage": "paint_damage", "chip": "chip", "paint_chip": "chip",
    "glass shatter": "glass_damage", "glass_damage": "glass_damage", "windscreen_crack": "glass_damage",
    "lamp broken": "broken_part", "broken_part": "broken_part", "broken_light": "broken_part",
    "tire flat": "tyre_damage", "tyre_damage": "tyre_damage", "tire_damage": "tyre_damage",
    "misaligned": "misaligned_panel", "misaligned_panel": "misaligned_panel",
}


class YoloDetector:
    name = "yolo"

    def __init__(self, weights: str, conf: float = 0.30, class_map: dict[str, str] | None = None,
                 imgsz: int = 1280):
        try:
            from ultralytics import YOLO  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("ultralytics is not installed: pip install ultralytics") from e
        self.model = YOLO(weights)
        self.conf = conf
        self.imgsz = imgsz
        self.class_map = {**DEFAULT_CLASS_MAP, **(class_map or {})}

    def detect(self, image_bgr: np.ndarray) -> list[RawDetection]:  # pragma: no cover - needs weights
        res = self.model.predict(image_bgr, conf=self.conf, imgsz=self.imgsz, verbose=False)[0]
        names = res.names
        out: list[RawDetection] = []
        if res.boxes is None:
            return out
        for xyxyn, c, k in zip(res.boxes.xyxyn.cpu().numpy(), res.boxes.conf.cpu().numpy(),
                               res.boxes.cls.cpu().numpy()):
            raw = str(names[int(k)]).lower()
            label = self.class_map.get(raw, raw if raw in LABELS else "other")
            x0, y0, x1, y1 = (float(v) for v in xyxyn)
            out.append(RawDetection(label, float(c), (x0, y0, x1, y1), self.name))
        return out
