"""Synthetic car photos with known damage, for tests and the demo.

Not realistic imagery: a flat-shaded side-on car with a scratch, dent and chips
painted in. Ground-truth boxes are returned so detection can be scored.
"""
from __future__ import annotations

import cv2
import numpy as np

from .config import DEFAULT_FRAME_BOX


def make_side_view(width: int = 1600, height: int = 900, damages: list[dict] | None = None,
                   body_bgr: tuple[int, int, int] = (150, 95, 45), seed: int = 0,
                   frame_box: tuple[float, float, float, float] = DEFAULT_FRAME_BOX):
    """Draw a side-on car filling `frame_box`, then add damage.

    damages: dicts like
      {"kind": "scratch", "p0": (u, v), "p1": (u, v)}     # u,v in frame coords 0..1
      {"kind": "dent", "c": (u, v), "r": 0.03}
      {"kind": "chip", "c": (u, v), "r": 0.006, "rust": False}
    Returns (image_bgr, [{"kind", "box": (x0, y0, x1, y1)} in image-normalised coords]).
    """
    rng = np.random.default_rng(seed)
    img = np.zeros((height, width, 3), np.float32)
    # backdrop: wall + ground
    img[:] = (205, 205, 200)
    img[int(height * 0.86):] = (120, 120, 118)

    fx0, fy0, fx1, fy1 = frame_box
    X0, Y0, X1, Y1 = fx0 * width, fy0 * height, fx1 * width, fy1 * height
    W, H = X1 - X0, Y1 - Y0

    def P(u, v):
        return int(X0 + u * W), int(Y0 + v * H)

    body = np.array([P(0.0, 0.62), P(0.01, 0.50), P(0.08, 0.46), P(0.24, 0.40), P(0.34, 0.12),
                     P(0.44, 0.02), P(0.72, 0.02), P(0.84, 0.10), P(0.93, 0.40), P(0.99, 0.46),
                     P(1.0, 0.64), P(1.0, 0.86), P(0.0, 0.86)], np.int32)
    cv2.fillPoly(img, [body], body_bgr)
    # gentle vertical shading on the body
    shade = np.linspace(1.10, 0.88, height, dtype=np.float32)[:, None, None]
    mask = np.zeros((height, width), np.uint8)
    cv2.fillPoly(mask, [body], 1)
    img = np.where(mask[..., None] > 0, img * shade, img)

    # windows
    win = [np.array([P(0.37, 0.16), P(0.44, 0.06), P(0.57, 0.06), P(0.57, 0.38), P(0.40, 0.38)], np.int32),
           np.array([P(0.60, 0.06), P(0.71, 0.06), P(0.81, 0.14), P(0.86, 0.38), P(0.60, 0.38)], np.int32)]
    for w_ in win:
        cv2.fillPoly(img, [w_], (70, 62, 55))
    # wheels
    for cu in (0.18, 0.82):
        c = P(cu, 0.84)
        cv2.circle(img, c, int(0.075 * W), (25, 25, 25), -1)
        cv2.circle(img, c, int(0.04 * W), (150, 150, 150), -1)

    img = img + rng.normal(0, 1.2, img.shape).astype(np.float32)  # sensor noise
    img = np.clip(img, 0, 255)

    gts = []
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    for d in damages or []:
        k = d["kind"]
        if k == "scratch":
            p0, p1 = P(*d["p0"]), P(*d["p1"])
            cv2.line(img, p0, p1, (215, 215, 225), 2, cv2.LINE_AA)
            x0, x1 = sorted([p0[0], p1[0]])
            y0, y1 = sorted([p0[1], p1[1]])
            gts.append({"kind": "scratch", "box": ((x0 - 4) / width, (y0 - 4) / height,
                                                   (x1 + 4) / width, (y1 + 4) / height)})
        elif k == "dent":
            cx, cy = P(*d["c"])
            s = d["r"] * W
            lobe = (xx - cx) / s * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * s * s))
            amp = d.get("amp", 38.0)
            img = np.clip(img + amp * lobe[..., None], 0, 255)
            gts.append({"kind": "dent", "box": ((cx - 2 * s) / width, (cy - 2 * s) / height,
                                                (cx + 2 * s) / width, (cy + 2 * s) / height)})
        elif k == "chip":
            cx, cy = P(*d["c"])
            r = max(3, int(d["r"] * W))
            colour = (40, 90, 150) if d.get("rust") else (60, 60, 60)
            cv2.circle(img, (cx, cy), r, colour, -1, cv2.LINE_AA)
            gts.append({"kind": "rust" if d.get("rust") else "chip",
                        "box": ((cx - r - 3) / width, (cy - r - 3) / height,
                                (cx + r + 3) / width, (cy + r + 3) / height)})
    return np.clip(img, 0, 255).astype(np.uint8), gts


DEMO_DAMAGES = [
    {"kind": "scratch", "p0": (0.34, 0.60), "p1": (0.46, 0.585)},            # front door, lower area
    {"kind": "dent", "c": (0.64, 0.56), "r": 0.022},                          # rear door
    {"kind": "chip", "c": (0.14, 0.50), "r": 0.007, "rust": True},            # front wing
]
