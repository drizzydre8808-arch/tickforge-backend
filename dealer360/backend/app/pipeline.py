"""Ingest a capture -> (undistort) -> detect -> locate on the car -> crop -> log."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from . import zones
from .config import DEFAULT_FRAME_BOX, DEFAULT_LENGTH_MM, DEFAULT_WIDTH_MM
from .db import Database
from .detection import HIGH_RISK, Detector, RawDetection
from .imaging import annotated_overview, crop_defect, encode_jpg, equirect_to_perspective, estimate_size_mm
from .lens import apply_lens_profile
from .quality import min_detectable_mm, mm_per_px_for, select_sharp, sharpness
from .tracking import confirm_detections
from .video import extract_frames

VALID_KINDS = {"photo", "equirect"}
SEVERITY_ORDER = ["minor", "moderate", "severe"]


def severity_for(label: str, box: tuple[float, float, float, float],
                 frame_box: tuple[float, float, float, float]) -> str:
    """Size-of-defect-relative-to-the-car heuristic, bumped for risky types.

    Area is measured as a fraction of the vehicle frame box. Calibrate these
    thresholds against your dealers' own grading standard (e.g. BVRLA / Cox).
    """
    fw = frame_box[2] - frame_box[0]
    fh = frame_box[3] - frame_box[1]
    area = max(0.0, (box[2] - box[0]) * (box[3] - box[1])) / (fw * fh)
    idx = 0 if area < 0.0015 else (1 if area < 0.008 else 2)
    if label == "scratch":
        # scratches are long and thin: judge by length instead of area
        length = max(box[2] - box[0], box[3] - box[1]) / fw
        idx = 0 if length < 0.06 else (1 if length < 0.18 else 2)
    if label in HIGH_RISK:
        idx = max(idx, 1)
    return SEVERITY_ORDER[idx]


def _ext_for(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    return ".jpg"


def decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image (send JPEG or PNG)")
    return img


class Pipeline:
    def __init__(self, db: Database, media_dir: Path, detector: Detector,
                 frame_box: tuple[float, float, float, float] = DEFAULT_FRAME_BOX):
        self.db = db
        self.media = media_dir
        self.detector = detector
        self.frame_box = frame_box

    # -- paths -------------------------------------------------------------------
    def _rel(self, vid: int, sub: str, name: str) -> str:
        p = Path(str(vid)) / sub
        (self.media / p).mkdir(parents=True, exist_ok=True)
        return str(p / name)

    def _write(self, rel: str, data: bytes) -> None:
        (self.media / rel).write_bytes(data)

    def _dims(self, vehicle: dict) -> tuple[float, float]:
        return (vehicle.get("length_mm") or DEFAULT_LENGTH_MM, vehicle.get("width_mm") or DEFAULT_WIDTH_MM)

    def _quality(self, vehicle: dict, view: str, img: np.ndarray, mm_per_px: Optional[float],
                 lens: Optional[dict], extra: Optional[dict] = None) -> dict:
        length, width = self._dims(vehicle)
        scale = mm_per_px or mm_per_px_for(view, self.frame_box, img.shape[1], length, width)
        q = {"sharpness": round(sharpness(img), 1)}
        if scale:
            q["mm_per_px"] = round(scale, 3)
            q["min_detectable_mm"] = min_detectable_mm(scale)
        if lens and lens.get("model", "none") != "none":
            q["lens_corrected"] = True
        return {**q, **(extra or {})}

    # -- photos and 360 ---------------------------------------------------------------
    def ingest(self, vehicle: dict, data: bytes, view: Optional[str], kind: str = "photo",
               source_camera: Optional[str] = None, yaw_views: Optional[dict[str, float]] = None,
               mm_per_px: Optional[float] = None, lens: Optional[dict] = None) -> dict:
        if kind not in VALID_KINDS:
            raise ValueError(f"kind must be one of {sorted(VALID_KINDS)}")
        vid = vehicle["id"]
        img = decode_image(data)
        h, w = img.shape[:2]

        if kind == "photo":
            if view not in zones.VIEWS:
                raise ValueError(f"view must be one of {sorted(zones.VIEWS)}")
        else:
            yaw_views = yaw_views or ({view: 0.0} if view else None)
            if not yaw_views:
                raise ValueError("equirect needs `view` (what yaw 0 faces) or `yaw_views`")
            bad = [v for v in yaw_views if v not in zones.VIEWS]
            if bad:
                raise ValueError(f"unknown views in yaw_views: {bad}")
            if abs(w / h - 2.0) > 0.15:
                raise ValueError("equirect images should be ~2:1 (e.g. 5760x2880)")
        apply_lens_profile(img[:2, :2], lens)  # validate lens params early (cheap)

        sid = self.db.add_shot(vehicle_id=vid, view=view if kind == "photo" else None, kind=kind,
                               source_camera=source_camera, path="", width=w, height=h)
        rel = self._rel(vid, "shots", f"{sid}{_ext_for(data)}")
        self._write(rel, data)
        self.db.update_shot_path(sid, rel)

        entries: list[tuple[str, np.ndarray, int]] = []
        derived_ids: list[int] = []
        if kind == "photo":
            if lens and lens.get("model", "none") != "none":
                flat = apply_lens_profile(img, lens)
                did = self._save_derived(vid, sid, view, flat, source_camera, None)  # type: ignore[arg-type]
                derived_ids.append(did)
                entries.append((view, flat, did))  # type: ignore[arg-type]
            else:
                entries.append((view, img, sid))  # type: ignore[arg-type]
        else:
            for v, yaw in yaw_views.items():  # type: ignore[union-attr]
                flat = equirect_to_perspective(img, float(yaw), 0.0, 90.0, 1600, 1000)
                did = self._save_derived(vid, sid, v, flat, source_camera, float(yaw))
                derived_ids.append(did)
                entries.append((v, flat, did))

        results = []
        for v, im, shot_id in entries:
            self.db.update_shot_quality(shot_id, self._quality(vehicle, v, im, mm_per_px, lens))
            results += self._log(vehicle, v, im, shot_id, self.detector.detect(im), mm_per_px)
        return {"shot_id": sid, "derived_shot_ids": derived_ids, "defects": results}

    def _save_derived(self, vid: int, parent: int, view: str, img: np.ndarray, cam: Optional[str],
                      yaw: Optional[float]) -> int:
        did = self.db.add_shot(vehicle_id=vid, parent_id=parent, view=view, kind="derived",
                               source_camera=cam, path="", width=img.shape[1], height=img.shape[0], yaw=yaw)
        rel = self._rel(vid, "shots", f"{did}.jpg")
        self._write(rel, encode_jpg(img, 92))
        self.db.update_shot_path(did, rel)
        return did

    # -- video ---------------------------------------------------------------------------
    def ingest_video(self, vehicle: dict, data: bytes, view: str, source_camera: Optional[str] = None,
                     lens: Optional[dict] = None, mm_per_px: Optional[float] = None,
                     target_fps: float = 4.0, max_frames: int = 16, min_hits: int = 3) -> dict:
        """Short steady clip of ONE view: sharp frames -> detect each -> keep only what stays locked
        to the bodywork across frames (drops reflections/glare) -> log against the sharpest frame."""
        if view not in zones.VIEWS:
            raise ValueError(f"view must be one of {sorted(zones.VIEWS)}")
        apply_lens_profile(np.zeros((4, 4, 3), np.uint8), lens)
        vid = vehicle["id"]
        with tempfile.NamedTemporaryFile(suffix=".mp4") as tmp:
            tmp.write(data)
            tmp.flush()
            frames = extract_frames(tmp.name, target_fps=target_fps, max_frames=max_frames)
        n_extracted = len(frames)
        if lens and lens.get("model", "none") != "none":
            frames = [apply_lens_profile(f, lens) for f in frames]
        keep = select_sharp(frames)
        frames = [frames[i] for i in keep]
        dets = [self.detector.detect(f) for f in frames]
        confirmed, rejected, info = confirm_detections(frames, dets, min_hits=min(min_hits, len(frames)))
        ref = frames[info["ref_idx"]]

        sid = self.db.add_shot(vehicle_id=vid, view=view, kind="photo",
                               source_camera=f"{source_camera or 'video'} (video)", path="",
                               width=ref.shape[1], height=ref.shape[0])
        rel = self._rel(vid, "shots", f"{sid}.jpg")
        self._write(rel, encode_jpg(ref, 94))
        self.db.update_shot_path(sid, rel)
        tracking = {"frames_extracted": n_extracted, "frames_analysed": len(frames),
                    "frames_registered": info.get("registered"), "confirmed": len(confirmed),
                    "rejected_as_glare_or_noise": rejected[:25], "note": info.get("note")}
        self.db.update_shot_quality(sid, self._quality(vehicle, view, ref, mm_per_px, lens, {"tracking": tracking}))
        results = self._log(vehicle, view, ref, sid, confirmed, mm_per_px)
        return {"shot_id": sid, "defects": results, "tracking": tracking}

    # -- logging ---------------------------------------------------------------------------
    def _log(self, vehicle: dict, view: str, img: np.ndarray, shot_id: int,
             detections: list[RawDetection], mm_per_px: Optional[float] = None) -> list[dict]:
        h, w = img.shape[:2]
        vid = vehicle["id"]
        length, width = self._dims(vehicle)
        out = []
        for det in detections:
            zone = zones.resolve(view, det.box, self.frame_box)
            if zone is None:
                continue  # background, not the car
            size = estimate_size_mm(det.box, view, w, h, self.frame_box, length, width, mm_per_px, det.polygon)
            sev = severity_for(det.label, det.box, self.frame_box)

            existing = self._find_duplicate(vid, det.label, zone)
            if existing is not None:
                seen = list(existing.get("seen_in") or [])
                if view not in seen:
                    seen.append(view)
                self.db.update_defect(existing["id"], seen_in=seen,
                                      score=max(existing["score"] or 0, det.score))
                out.append({**self.db.get_defect(existing["id"]), "merged": True})
                continue

            mask = [[round(float(x), 5), round(float(y), 5)] for x, y in det.polygon] if det.polygon else None
            did = self.db.add_defect(
                vehicle_id=vid, shot_id=shot_id, label=det.label, score=round(float(det.score), 3),
                severity=sev, panel_id=zone.panel_id, side=zone.side, panel=zone.panel,
                band=zone.band, description=zone.description,
                box=[round(float(x), 5) for x in det.box], mask=mask, zone=zone.to_dict(), size_mm=size,
                seen_in=[view], detector=det.detector or self.detector.name, status="pending",
            )
            tag = f"#{did} {det.label} ({sev})"
            crop_rel = self._rel(vid, "defects", f"{did}_crop.jpg")
            over_rel = self._rel(vid, "defects", f"{did}_overview.jpg")
            self._write(crop_rel, encode_jpg(crop_defect(img, det.box), 95))
            self._write(over_rel, encode_jpg(annotated_overview(img, det.box, tag), 88))
            self.db.update_defect(did, crop_path=crop_rel, overview_path=over_rel)
            out.append({**self.db.get_defect(did), "merged": False})
        return out

    def _find_duplicate(self, vid: int, label: str, zone: zones.ZoneResult) -> Optional[dict]:
        """Same defect seen from a *different* walkaround view -> merge, don't double-log.

        Two nearby marks in the same view stay separate entries."""
        for d in self.db.list_defects(vid):
            if d["label"] != label or d["panel_id"] != zone.panel_id or d["side"] != zone.side:
                continue
            if zone.view in (d.get("seen_in") or []):
                continue
            z = d["zone"] or {}
            if (abs(z.get("along", 0.5) - zone.along) < 0.25
                    and abs(z.get("vertical", 0.5) - zone.vertical) < 0.30):
                return d
        return None
