"""Classical-CV fallback detector.

Purely heuristic: thin bright/dark ridges -> scratches, soft shading blobs ->
dents, small colour outliers -> paint damage / rust. It exists so the whole
pipeline (zones, crops, reports, review flow) works before you have a trained
model. It WILL miss real damage and flag panel gaps, stickers and reflections.
Do not trust it for real condition reports; train the YOLO model instead.
"""
from __future__ import annotations

import cv2
import numpy as np

from ..config import DEFAULT_FRAME_BOX
from .base import RawDetection, nms


def _contained(small: tuple, big: tuple, frac: float = 0.5) -> bool:
    ix0, iy0 = max(small[0], big[0]), max(small[1], big[1])
    ix1, iy1 = min(small[2], big[2]), min(small[3], big[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area = (small[2] - small[0]) * (small[3] - small[1])
    return area > 0 and inter / area >= frac


class ClassicalDetector:
    name = "classical-heuristic"

    def __init__(self, sensitivity: float = 1.0, max_dets: int = 12, max_side: int = 1280,
                 frame_box: tuple[float, float, float, float] = DEFAULT_FRAME_BOX):
        self.sens = sensitivity
        self.max_dets = max_dets
        self.max_side = max_side
        self.frame_box = frame_box

    # -- helpers -----------------------------------------------------------------
    def _prep(self, img: np.ndarray):
        h, w = img.shape[:2]
        s = min(1.0, self.max_side / max(h, w))
        if s < 1.0:
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        return img

    @staticmethod
    def _polygon(region: np.ndarray, w: int, h: int, max_pts: int = 24):
        """Outline of a boolean region as a normalised polygon."""
        cs, _ = cv2.findContours(region.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cs:
            return None
        c = max(cs, key=cv2.contourArea)
        eps = 0.01 * cv2.arcLength(c, True)
        a = cv2.approxPolyDP(c, eps, True)
        while len(a) > max_pts:
            eps *= 1.5
            a = cv2.approxPolyDP(c, eps, True)
        if len(a) < 3:   # thin line collapsed to a segment: use its rotated rectangle instead
            a = cv2.boxPoints(cv2.minAreaRect(c)).reshape(-1, 1, 2)
        return [(float(x) / w, float(y) / h) for x, y in a.reshape(-1, 2)]

    @staticmethod
    def _norm_box(x: int, y: int, bw: int, bh: int, w: int, h: int, pad: float = 0.0):
        px, py = bw * pad, bh * pad
        return (float(max(0.0, (x - px) / w)), float(max(0.0, (y - py) / h)),
                float(min(1.0, (x + bw + px) / w)), float(min(1.0, (y + bh + py) / h)))

    # -- detectors ---------------------------------------------------------------
    def _scratches(self, L: np.ndarray, mask: np.ndarray, edges_d: np.ndarray) -> list[RawDetection]:
        h, w = L.shape
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        dark = cv2.morphologyEx(L, cv2.MORPH_BLACKHAT, k)
        bright = cv2.morphologyEx(L, cv2.MORPH_TOPHAT, k)
        resp = np.maximum(dark, bright)
        thr = 12.0 / self.sens
        bw = ((resp > thr) & (mask > 0)).astype(np.uint8)
        bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
        out = []
        for i in range(1, n):
            x, y, bw_, bh_, area = stats[i]
            if area < 12:
                continue
            ys, xs = np.where(lab == i)
            pts = np.column_stack([xs, ys]).astype(np.float32)
            (_, _), (rw, rh), _ = cv2.minAreaRect(pts)
            long_, short_ = max(rw, rh), max(1.0, min(rw, rh))
            if long_ < 0.012 * w or long_ / short_ < 4.0 or short_ > 0.012 * w:
                continue
            strength = float(resp[ys, xs].mean())
            score = float(np.clip(0.35 + 0.5 * min(1.0, strength / (thr * 3)), 0.3, 0.9))
            out.append(RawDetection("scratch", score, self._norm_box(x, y, bw_, bh_, w, h, 0.25), self.name,
                                    polygon=self._polygon(lab == i, w, h)))
        return out

    def _dents(self, L: np.ndarray, mask: np.ndarray, edges_d: np.ndarray) -> list[RawDetection]:
        """Soft shading blobs. Shading is estimated inside each smooth region
        separately (regions are bounded by structural edges), so window, wheel
        and silhouette edges can't leak into the estimate."""
        h, w = L.shape
        smooth = ((edges_d < 0.5) & (mask > 0)).astype(np.uint8)
        n_r, regions, rstats, _ = cv2.connectedComponentsWithStats(smooth, 4)
        order = sorted(range(1, n_r), key=lambda i: -rstats[i, cv2.CC_STAT_AREA])[:8]
        thr = 5.0 / self.sens
        er = max(3, int(w * 0.02))
        ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * er + 1, 2 * er + 1))
        kk = max(3, int(w * 0.012) | 1)
        close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kk, kk))
        out = []
        for ri in order:
            if rstats[ri, cv2.CC_STAT_AREA] < 0.01 * h * w:
                continue
            m = (regions == ri).astype(np.float32)

            def nconv(sig, m=m):
                num = cv2.GaussianBlur(L * m, (0, 0), sig)
                den = cv2.GaussianBlur(m, (0, 0), sig)
                return num / np.maximum(den, 1e-3), den

            small, _ = nconv(w * 0.010)
            bg, den_bg = nconv(w * 0.050)
            d = np.abs(small - bg)
            valid = cv2.erode(m.astype(np.uint8), ker)
            bw = ((d > thr) & (valid > 0) & (den_bg > 0.6)).astype(np.uint8)
            bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, close_k)
            n, lab, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
            for i in range(1, n):
                x, y, bw_, bh_, area = stats[i]
                frac = area / float(h * w)
                if not (0.0004 < frac < 0.03):
                    continue
                if max(bw_, bh_) / max(1, min(bw_, bh_)) > 3.5:
                    continue
                strength = float(d[lab == i].mean())
                score = float(np.clip(0.30 + 0.5 * min(1.0, strength / (thr * 3)), 0.3, 0.85))
                out.append(RawDetection("dent", score, self._norm_box(x, y, bw_, bh_, w, h, 0.1), self.name,
                                        polygon=self._polygon(lab == i, w, h)))
        return out

    def _colour(self, lab: np.ndarray, mask: np.ndarray, struct_d: np.ndarray) -> list[RawDetection]:
        h, w = lab.shape[:2]
        if mask.sum() < 100:
            return []
        # Compare each pixel with the median colour of its own neighbourhood. A global
        # "body colour" is fragile (the frame is part body, part backdrop); a local one
        # isn't, and chips/rust are by definition local outliers.
        a8, b8, L8 = (np.clip(lab[..., c], 0, 255).astype(np.uint8) for c in (1, 2, 0))
        k = max(15, int(w * 0.05) | 1)
        ma, mb, mL = (cv2.medianBlur(ch, k).astype(np.float32) for ch in (a8, b8, L8))
        a, b = lab[..., 1], lab[..., 2]
        dist = np.sqrt((a - ma) ** 2 + (b - mb) ** 2) + 0.35 * np.abs(lab[..., 0] - mL)
        thr = 26.0 / self.sens
        bw = ((dist > thr) & (mask > 0)).astype(np.uint8)
        bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
        out = []
        for i in range(1, n):
            x, y, bw_, bh_, area = stats[i]
            frac = area / float(h * w)
            if not (0.00004 < frac < 0.004):
                continue
            if max(bw_, bh_) / max(1, min(bw_, bh_)) > 3.5 or min(bw_, bh_) < 4:
                continue   # slivers along silhouette / frame edges are not chips
            region = labels == i
            if struct_d[region].mean() > 0.5:      # JPEG/chroma bleed along a long structural edge
                continue
            ra, rb, rL = a[region].mean() - 128, b[region].mean() - 128, lab[..., 0][region].mean()
            label = "rust" if (ra > 6 and rb > 14 and rL < 150) else "chip"
            score = float(np.clip(0.30 + 0.5 * min(1.0, float(dist[region].mean()) / (thr * 2.5)), 0.3, 0.85))
            out.append(RawDetection(label, score, self._norm_box(x, y, bw_, bh_, w, h, 0.5), self.name,
                                    polygon=self._polygon(region, w, h)))
        return out

    # -- public ------------------------------------------------------------------
    def detect(self, image_bgr: np.ndarray) -> list[RawDetection]:
        img = self._prep(image_bgr)
        h, w = img.shape[:2]
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
        L = lab[..., 0]

        fx0, fy0, fx1, fy1 = self.frame_box
        mask = np.zeros((h, w), np.uint8)
        m = 0.012  # stay off the very edge of the vehicle box
        mask[int((fy0 + m) * h):int((fy1 - m) * h), int((fx0 + m) * w):int((fx1 - m) * w)] = 1

        # structural edges (windows, wheels, lights, silhouette), thickened
        edges = cv2.Canny(cv2.GaussianBlur(L.astype(np.uint8), (0, 0), 1.5), 16, 48)
        edges_d = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))).astype(np.float32) / 255.0

        # long edges only (silhouette, wheels, windows): short ones belong to chips/scratches themselves
        n_e, e_lab, e_st, _ = cv2.connectedComponentsWithStats(edges, 8)
        long_e = np.zeros_like(edges)
        for i in range(1, n_e):
            if e_st[i, cv2.CC_STAT_AREA] >= 0.06 * w:
                long_e[e_lab == i] = 255
        struct_d = cv2.dilate(long_e, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))).astype(np.float32) / 255.0

        scratches = self._scratches(L, mask, edges_d)
        dents = self._dents(L, mask, edges_d)
        colour = self._colour(lab, mask, struct_d)
        # a dent's light/dark lobes also look like colour outliers; don't report them twice
        colour = [c for c in colour if not any(_contained(c.box, d.box) for d in dents)]
        dets = [d for d in nms(scratches + dents + colour, 0.35) if d.score >= 0.3]
        return dets[: self.max_dets]
