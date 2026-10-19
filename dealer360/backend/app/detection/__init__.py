from __future__ import annotations

import logging
import os

from .. import config
from .base import HIGH_RISK, LABELS, Detector, RawDetection  # noqa: F401
from .classical import ClassicalDetector

log = logging.getLogger("dealer360.detection")
_cached: Detector | None = None


def get_detector() -> Detector:
    """Pick the detector from DEALER360_DETECTOR: auto | classical | yolo | vlm.

    auto = YOLO if DEALER360_YOLO_WEIGHTS is set and loads, else the classical fallback.
    """
    global _cached
    if _cached is not None:
        return _cached
    mode = os.environ.get("DEALER360_DETECTOR", "auto").lower()
    if mode == "vlm":
        from .vlm import VlmDetector
        _cached = VlmDetector()
        log.info("Using LLM vision detector (%s, tiles %s)", _cached.model, _cached.tiles)
        return _cached
    if mode in ("auto", "yolo") and config.YOLO_WEIGHTS:
        try:
            from .yolo import YoloDetector
            _cached = YoloDetector(config.YOLO_WEIGHTS, conf=config.YOLO_CONF)
            log.info("Using YOLO detector: %s", config.YOLO_WEIGHTS)
            return _cached
        except Exception as e:  # noqa: BLE001
            log.warning("YOLO unavailable (%s); falling back to classical detector", e)
    _cached = ClassicalDetector()
    return _cached


def reset_detector() -> None:
    global _cached
    _cached = None
