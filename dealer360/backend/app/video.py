"""Cut a short clip into frames for analysis."""
from __future__ import annotations

import cv2
import numpy as np


def extract_frames(path: str, target_fps: float = 4.0, max_frames: int = 16,
                   max_side: int = 1920) -> list[np.ndarray]:
    """Sample a clip at roughly `target_fps`, up to `max_frames`, downscaled to `max_side`.

    Memory is the limit here (each 1080p frame is ~6 MB), so the defaults are
    conservative. Use a short steady clip of one view rather than a long pass.
    """
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError("could not open video (try MP4/H.264 or MOV)")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / target_fps)))
    frames: list[np.ndarray] = []
    idx = 0
    try:
        while len(frames) < max_frames:
            if not cap.grab():
                break
            if idx % step == 0:
                ok, f = cap.retrieve()
                if not ok:
                    break
                k = min(1.0, max_side / max(f.shape[:2]))
                if k < 1:
                    f = cv2.resize(f, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
                frames.append(f)
            idx += 1
    finally:
        cap.release()
    if not frames:
        raise ValueError("no frames could be read from the video")
    return frames
