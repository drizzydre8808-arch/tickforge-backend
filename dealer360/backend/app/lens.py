"""Lens-distortion correction for wide-angle action cameras.

Most GoPro / DJI Osmo / Insta360 single-lens modes are wide, barrel-distorted
images. Defect sizes and panel positions are wrong at the edges unless this is
undone first. Two ways to deal with it:

  1. Record in the camera's "Linear" (or "Linear + horizon lock") FOV mode, which
     corrects distortion in-camera. Best option; no work needed here.
  2. Send us the lens profile and we convert fisheye -> rectilinear here.

`fisheye_to_rectilinear` assumes an equidistant fisheye model (r = f * theta)
spanning `fov_deg` across the image width. Real action-camera "Wide" modes are
close to but not exactly this; use a measured calibration for survey-grade
sizes. Equirectangular 360 images are handled separately
(`imaging.equirect_to_perspective`), which already outputs a rectilinear view.
"""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np


def fisheye_to_rectilinear(img: np.ndarray, fov_deg: float, out_fov_deg: float = 100.0,
                           out_size: Optional[tuple[int, int]] = None) -> np.ndarray:
    if not (30 <= fov_deg <= 220):
        raise ValueError("fov_deg must be between 30 and 220")
    if not (30 <= out_fov_deg <= 150):
        raise ValueError("out_fov_deg must be between 30 and 150")
    h, w = img.shape[:2]
    ow, oh = out_size or (w, h)
    f_in = (w / 2) / np.radians(fov_deg / 2)
    f_out = (ow / 2) / np.tan(np.radians(out_fov_deg / 2))
    xs = np.arange(ow, dtype=np.float32) - ow / 2 + 0.5
    ys = np.arange(oh, dtype=np.float32) - oh / 2 + 0.5
    x, y = np.meshgrid(xs, ys)
    r_out = np.hypot(x, y)
    theta = np.arctan(r_out / f_out)
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = np.where(r_out > 1e-6, f_in * theta / r_out, f_in / f_out)
    map_x = (x * scale + w / 2 - 0.5).astype(np.float32)
    map_y = (y * scale + h / 2 - 0.5).astype(np.float32)
    return cv2.remap(img, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))


def apply_lens_profile(img: np.ndarray, lens: Optional[dict]) -> np.ndarray:
    """lens: None | {"model": "none"} | {"model": "equidistant", "fov_deg": 120, "out_fov_deg": 100}"""
    if not lens or lens.get("model", "none") == "none":
        return img
    if lens["model"] != "equidistant":
        raise ValueError("lens.model must be 'none' or 'equidistant'")
    try:
        fov, out_fov = float(lens["fov_deg"]), float(lens.get("out_fov_deg", 100.0))
    except (KeyError, TypeError, ValueError):
        raise ValueError("lens needs a numeric fov_deg, e.g. {\"model\": \"equidistant\", \"fov_deg\": 120}")
    return fisheye_to_rectilinear(img, fov, out_fov)
