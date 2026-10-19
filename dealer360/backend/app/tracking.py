"""Spatiotemporal confirmation across the frames of one short pass.

Real paint defects are rigidly attached to the bodywork. Reflections, glare and
lens flare are attached to the *camera / light*, so as the operator moves they
slide across the panel. We register every frame onto one reference frame
(homography from matched ORB features on the vehicle) and look at where each
detection lands in reference coordinates:

  * a defect lands on the same spot in (almost) every frame that can see it -> keep
  * a reflection lands somewhere different each time                       -> drop

Assumes a short, steady clip of one walkaround view (a few seconds, mostly the
same panels in frame). It is not a full-vehicle video stitcher.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from .detection.base import RawDetection
from .quality import sharpness

_FAMILY = {"chip": "paint", "rust": "paint", "paint_damage": "paint"}


def _family(label: str) -> str:
    return _FAMILY.get(label, label)


def register_to_reference(frame: np.ndarray, ref: np.ndarray, max_side: int = 1000) -> Optional[np.ndarray]:
    """Homography mapping normalised frame coords -> normalised reference coords, or None."""
    def prep(img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        k = min(1.0, max_side / max(g.shape[:2]))
        if k < 1:
            g = cv2.resize(g, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        return g

    gf, gr = prep(frame), prep(ref)
    orb = cv2.ORB_create(4000, fastThreshold=10)
    kf, df = orb.detectAndCompute(gf, None)
    kr, dr = orb.detectAndCompute(gr, None)
    if df is None or dr is None or len(kf) < 20 or len(kr) < 20:
        return None
    matches = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(df, dr), key=lambda m: m.distance)[:600]
    if len(matches) < 15:
        return None
    pf = np.float32([kf[m.queryIdx].pt for m in matches])
    pr = np.float32([kr[m.trainIdx].pt for m in matches])
    H, inl = cv2.findHomography(pf, pr, cv2.RANSAC, 3.0)
    if H is None or inl is None or int(inl.sum()) < 12:
        return None
    # pixel -> normalised
    sf = np.diag([1.0 / gf.shape[1], 1.0 / gf.shape[0], 1.0])
    sr = np.diag([1.0 / gr.shape[1], 1.0 / gr.shape[0], 1.0])
    return sr @ H @ np.linalg.inv(sf)


def _project(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    p = np.hstack([pts, np.ones((len(pts), 1))]) @ H.T
    return p[:, :2] / p[:, 2:3]


def _box_pts(b) -> np.ndarray:
    return np.array([[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]], float)


@dataclass
class _Track:
    family: str
    hits: list = field(default_factory=list)   # (frame_idx, label, score, box_ref, poly_ref, is_ref)

    def centre(self) -> np.ndarray:
        return np.mean([[(h[3][0] + h[3][2]) / 2, (h[3][1] + h[3][3]) / 2] for h in self.hits], axis=0)


def confirm_detections(frames: list[np.ndarray], dets_per_frame: list[list[RawDetection]],
                       ref_idx: Optional[int] = None, min_hits: int = 3, min_frac: float = 0.6,
                       tol: float = 0.015):
    """Keep only detections that stay put on the vehicle across frames.

    Returns (confirmed, rejected, info). `confirmed` detections are expressed in
    the coordinates of frames[info["ref_idx"]].
    """
    n = len(frames)
    if n == 0 or n != len(dets_per_frame):
        return [], [], {"ref_idx": 0, "frames": n, "registered": 0}
    if ref_idx is None:
        ref_idx = int(np.argmax([sharpness(f) for f in frames]))
    ref = frames[ref_idx]

    Hs: dict[int, np.ndarray] = {ref_idx: np.eye(3)}
    for i, f in enumerate(frames):
        if i == ref_idx:
            continue
        H = register_to_reference(f, ref)
        if H is not None:
            Hs[i] = H
    info = {"ref_idx": ref_idx, "frames": n, "registered": len(Hs)}
    if len(Hs) < min(min_hits, n):
        return [], [], {**info, "note": "not enough frames could be registered to the reference"}

    # project every detection into reference coordinates, ref frame first
    projected = []
    for i in sorted(Hs, key=lambda i: (i != ref_idx, abs(i - ref_idx))):
        for d in dets_per_frame[i]:
            pts = _project(Hs[i], _box_pts(d.box))
            box = (float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max()))
            poly = None
            if d.polygon:
                pp = _project(Hs[i], np.array(d.polygon, float))
                poly = [(float(x), float(y)) for x, y in pp]
            projected.append((i, d, box, poly))

    tracks: list[_Track] = []
    for i, d, box, poly in projected:
        c = np.array([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2])
        best, best_dist = None, tol
        for t in tracks:
            if t.family != _family(d.label):
                continue
            if any(h[0] == i for h in t.hits):      # one hit per frame per track
                continue
            dist = float(np.linalg.norm(t.centre() - c))
            if dist < best_dist:
                best, best_dist = t, dist
        if best is None:
            best = _Track(_family(d.label))
            tracks.append(best)
        best.hits.append((i, d.label, d.score, box, poly, i == ref_idx))

    Hinv = {i: np.linalg.inv(H) for i, H in Hs.items()}
    confirmed, rejected = [], []
    for t in tracks:
        c = t.centre()
        visible = 0
        for i in Hs:
            x, y = _project(Hinv[i], c[None, :])[0]
            if 0.02 <= x <= 0.98 and 0.02 <= y <= 0.98:
                visible += 1
        hits = len(t.hits)
        frac = hits / visible if visible else 0.0
        summary = {"label": t.hits[0][1], "centre": [round(float(c[0]), 4), round(float(c[1]), 4)],
                   "hits": hits, "visible_in": visible}
        if hits >= min_hits and frac >= min_frac:
            top = max(t.hits, key=lambda h: (h[5], h[2]))
            boxes = np.array([h[3] for h in t.hits])
            box = tuple(float(v) for v in np.clip(boxes.mean(axis=0), 0.0, 1.0))
            poly = top[4] if top[4] and top[5] else None   # only trust a polygon drawn on the reference frame
            label = max({h[1] for h in t.hits}, key=lambda lb: sum(1 for h in t.hits if h[1] == lb))
            score = float(np.mean([h[2] for h in t.hits]) * (0.5 + 0.5 * min(1.0, frac)))
            confirmed.append(RawDetection(label, score, box, "tracked", polygon=poly,
                                          extra={"frames_seen": hits, "frames_visible": visible}))
        else:
            rejected.append({**summary, "reason": "not locked to the bodywork across frames (reflection, glare or noise)"})
    return confirmed, rejected, info
