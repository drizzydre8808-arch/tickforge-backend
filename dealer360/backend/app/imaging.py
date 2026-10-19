"""Image helpers: 360 -> flat views, defect crops, annotated overviews, size estimates."""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

SIDE_VIEWS = {"nearside", "offside"}
END_VIEWS = {"front", "rear"}


def equirect_to_perspective(eq: np.ndarray, yaw_deg: float, pitch_deg: float = 0.0,
                            fov_deg: float = 90.0, out_w: int = 1600, out_h: int = 1000) -> np.ndarray:
    """Cut a flat (rectilinear) view out of an equirectangular 360 image.

    yaw: 0 = centre of the panorama, positive = look right. pitch: positive = look up.
    """
    H, W = eq.shape[:2]
    f = 0.5 * out_w / np.tan(np.radians(fov_deg) / 2)
    xs = np.arange(out_w, dtype=np.float32) - out_w / 2 + 0.5
    ys = np.arange(out_h, dtype=np.float32) - out_h / 2 + 0.5
    x, y = np.meshgrid(xs, ys)
    z = np.full_like(x, f)

    p, a = np.radians(pitch_deg), np.radians(yaw_deg)
    y2 = y * np.cos(p) - z * np.sin(p)
    z2 = y * np.sin(p) + z * np.cos(p)
    x3 = x * np.cos(a) + z2 * np.sin(a)
    z3 = -x * np.sin(a) + z2 * np.cos(a)

    lon = np.arctan2(x3, z3)
    lat = np.arcsin(np.clip(-y2 / np.sqrt(x3 ** 2 + y2 ** 2 + z3 ** 2), -1, 1))
    map_x = ((lon / (2 * np.pi) + 0.5) * W).astype(np.float32)
    map_y = ((0.5 - lat / np.pi) * H).astype(np.float32)
    return cv2.remap(eq, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


def crop_defect(img: np.ndarray, box: tuple[float, float, float, float],
                pad: float = 0.45, min_side: int = 192, max_side: int = 1200) -> np.ndarray:
    """Crop around a normalised box with generous context padding."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box[0] * w, box[1] * h, box[2] * w, box[3] * h
    bw, bh = x1 - x0, y1 - y0
    side = max(bw * (1 + 2 * pad), bh * (1 + 2 * pad), min_side)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    cx0 = int(round(max(0, min(w - side, cx - side / 2))))
    cy0 = int(round(max(0, min(h - side, cy - side / 2))))
    cx1 = int(round(min(w, cx0 + side)))
    cy1 = int(round(min(h, cy0 + side)))
    crop = img[cy0:cy1, cx0:cx1].copy()
    # draw the defect box inside the crop so the reviewer sees exactly what was flagged
    cv2.rectangle(crop, (int(x0 - cx0), int(y0 - cy0)), (int(x1 - cx0), int(y1 - cy0)), (0, 0, 255), 2)
    s = max(crop.shape[:2])
    if s > max_side:
        k = max_side / s
        crop = cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    return crop


def annotated_overview(img: np.ndarray, box: tuple[float, float, float, float], label: str,
                       max_side: int = 1600) -> np.ndarray:
    h, w = img.shape[:2]
    k = min(1.0, max_side / max(h, w))
    out = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else img.copy()
    oh, ow = out.shape[:2]
    p0 = (int(box[0] * ow), int(box[1] * oh))
    p1 = (int(box[2] * ow), int(box[3] * oh))
    cv2.rectangle(out, p0, p1, (0, 0, 255), max(2, ow // 400))
    scale = max(0.6, ow / 1800)
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    ty = max(th + 6, p0[1] - 6)
    cv2.rectangle(out, (p0[0], ty - th - 6), (p0[0] + tw + 8, ty + 4), (0, 0, 255), -1)
    cv2.putText(out, label, (p0[0] + 4, ty - 2), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 2, cv2.LINE_AA)
    return out


def estimate_size_mm(box: tuple[float, float, float, float], view: str, img_w: int, img_h: int,
                     frame_box: tuple[float, float, float, float], length_mm: float, width_mm: float,
                     mm_per_px: Optional[float] = None,
                     polygon: Optional[list[tuple[float, float]]] = None) -> Optional[dict]:
    """Defect length / width / area in mm.

    Scale comes from `mm_per_px` if the client supplies it (e.g. from camera
    distance), otherwise from the known vehicle size assuming the car fills the
    guide frame in a straight-on view. Three-quarter views are foreshortened so
    we don't guess without an explicit scale. Length/width come from the mask
    outline when there is one (much tighter than the padded box).
    Approximate: +/-20% on flat panels, worse on curved ones.
    """
    source = "client"
    if mm_per_px is None:
        if view in SIDE_VIEWS:
            real = length_mm
        elif view in END_VIEWS:
            real = width_mm
        else:
            return None
        frame_px = (frame_box[2] - frame_box[0]) * img_w
        if frame_px <= 0:
            return None
        mm_per_px = real / frame_px
        source = "vehicle_size"

    if polygon and len(polygon) >= 3:
        pts = np.array([[x * img_w, y * img_h] for x, y in polygon], np.float32)
        (_, _), (rw, rh), _ = cv2.minAreaRect(pts)
        length_px, width_px = max(rw, rh), min(rw, rh)
        area_px = float(cv2.contourArea(pts))
        basis = "mask"
    else:
        bw, bh = (box[2] - box[0]) * img_w, (box[3] - box[1]) * img_h
        length_px, width_px = max(bw, bh), min(bw, bh)
        area_px = bw * bh
        basis = "bbox"
    k = float(mm_per_px)
    return {
        "length_mm": round(length_px * k, 1), "width_mm": round(width_px * k, 1),
        "area_mm2": round(area_px * k * k), "longest_mm": round(length_px * k),
        "area_basis": basis, "scale_source": source, "mm_per_px": round(k, 3),
        "min_detectable_mm": round(3.0 * k, 2),   # ~3 px: below this we cannot honestly claim to see it
        "approximate": True,
    }


def encode_jpg(img: np.ndarray, quality: int = 92) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("could not encode image")
    return buf.tobytes()
