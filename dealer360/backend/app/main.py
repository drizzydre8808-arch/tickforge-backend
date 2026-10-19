"""Dealer360 API.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import json
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from . import config, plate, zones
from .db import Database
from .detection import Detector, get_detector
from .pipeline import Pipeline
from .report import build_report, make_embedder
from .spec import to_spec
from .viewer import render_viewer

MAX_UPLOAD_BYTES = 80 * 1024 * 1024    # 360 photos from an Insta360 X4 are ~15-30 MB as JPEG
MAX_VIDEO_BYTES = 250 * 1024 * 1024   # short clips only: export 3-5 s at 1080p-4K, not raw 5.7K
STATUSES = {"pending", "confirmed", "rejected"}


class VehicleIn(BaseModel):
    reg: Optional[str] = Field(None, max_length=16)
    vin: Optional[str] = Field(None, max_length=32)
    make: Optional[str] = Field(None, max_length=64)
    model: Optional[str] = Field(None, max_length=64)
    year: Optional[int] = Field(None, ge=1900, le=2100)
    length_mm: Optional[int] = Field(None, ge=1500, le=7000)
    width_mm: Optional[int] = Field(None, ge=1000, le=3000)
    notes: Optional[str] = Field(None, max_length=2000)


class DefectPatch(BaseModel):
    status: Optional[str] = None
    severity: Optional[str] = None
    label: Optional[str] = None
    note: Optional[str] = Field(None, max_length=2000)


def create_app(data_dir: Optional[Path] = None, detector: Optional[Detector] = None) -> FastAPI:
    data_dir = Path(data_dir or config.DATA_DIR)
    media_dir = data_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    db = Database(data_dir / "dealer360.db")
    pipe = Pipeline(db, media_dir, detector or get_detector())

    app = FastAPI(title="Dealer360", version="0.1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    # -- auth (single shared key; replace with per-dealer auth before real use) ---------
    def auth(request: Request, key: Optional[str] = Query(None)) -> Optional[str]:
        if not config.API_KEY:
            return None
        supplied = request.headers.get("x-api-key") or key or ""
        if not secrets.compare_digest(supplied, config.API_KEY):
            raise HTTPException(401, "missing or invalid API key")
        return supplied

    def media_url(rel: str, key: Optional[str]) -> str:
        return f"/media/{rel}" + (f"?key={key}" if key else "")

    def decorate(d: dict, key: Optional[str]) -> dict:
        d = dict(d)
        d["crop_url"] = media_url(d["crop_path"], key) if d.get("crop_path") else None
        d["overview_url"] = media_url(d["overview_path"], key) if d.get("overview_path") else None
        return d

    def json_field(raw: Optional[str], name: str) -> Optional[dict]:
        if not raw:
            return None
        try:
            val = json.loads(raw)
        except ValueError:
            raise HTTPException(422, f"{name} must be valid JSON")
        if not isinstance(val, dict):
            raise HTTPException(422, f"{name} must be a JSON object")
        return val

    def need_vehicle(vid: int) -> dict:
        v = db.get_vehicle(vid)
        if not v:
            raise HTTPException(404, "vehicle not found")
        return v

    # -- meta ----------------------------------------------------------------------
    @app.get("/health")
    def health():
        return {"ok": True, "detector": pipe.detector.name}

    @app.get("/capture-profile", dependencies=[Depends(auth)])
    def capture_profile():
        """What the app needs to drive guided capture."""
        return {
            "views": zones.WALKAROUND_ORDER,
            "frame_box": config.DEFAULT_FRAME_BOX,
            "video": {"clip_seconds": [3, 5], "target_fps": 4, "note": "one steady clip per view; hold the framing guide"},
            "lens_hint": {"best": "record in Linear / dewarped FOV mode",
                          "else": {"model": "equidistant", "fov_deg": "camera horizontal FOV"}},
            "detector": pipe.detector.name,
            "equirect_presets": {
                "single_side": {"description": "360 camera on a tripod beside the car, facing it", "yaw_views": "view-at-yaw-0 only"},
                "corner_pair": {"description": "Two 360 cameras at opposite corners",
                                "yaw_views_example": {"front": 0, "nearside": 90}},
            },
        }

    # -- number plates -----------------------------------------------------------------
    @app.post("/plate/read", dependencies=[Depends(auth)])
    async def plate_read(file: UploadFile = File(...)):
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(await file.read(), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(400, "Not a readable image")
        return plate.read_plate(img)

    @app.get("/plate/lookup/{vrm}", dependencies=[Depends(auth)])
    def plate_lookup(vrm: str):
        try:
            return plate.dvla_lookup(vrm, config.DVLA_API_KEY)
        except ValueError as e:
            raise HTTPException(422, str(e))
        except LookupError as e:
            raise HTTPException(404, str(e))
        except RuntimeError as e:
            raise HTTPException(503, str(e))

    # -- vehicles --------------------------------------------------------------------
    @app.post("/vehicles", status_code=201, dependencies=[Depends(auth)])
    def create_vehicle(v: VehicleIn):
        vid = db.add_vehicle(**v.model_dump())
        return db.get_vehicle(vid)

    @app.get("/vehicles", dependencies=[Depends(auth)])
    def list_vehicles():
        return db.list_vehicles()

    @app.get("/vehicles/{vid}", dependencies=[Depends(auth)])
    def get_vehicle(vid: int):
        return need_vehicle(vid)

    @app.delete("/vehicles/{vid}", status_code=204, dependencies=[Depends(auth)])
    def delete_vehicle(vid: int):
        need_vehicle(vid)
        db.delete_vehicle(vid)
        shutil.rmtree(media_dir / str(vid), ignore_errors=True)

    # -- capture ---------------------------------------------------------------------
    @app.post("/vehicles/{vid}/shots", status_code=201)
    async def upload_shot(
        vid: int,
        file: UploadFile = File(...),
        view: Optional[str] = Form(None),
        kind: str = Form("photo"),
        source_camera: Optional[str] = Form(None),
        yaw_views: Optional[str] = Form(None, description='JSON, e.g. {"nearside": 0, "front": -90}'),
        mm_per_px: Optional[float] = Form(None, gt=0, description="Known scale at the car surface, if the app can work it out"),
        lens: Optional[str] = Form(None, description='JSON, e.g. {"model":"equidistant","fov_deg":120}'),
        key: Optional[str] = Depends(auth),
    ):
        vehicle = need_vehicle(vid)
        data = await file.read()
        if not data:
            raise HTTPException(400, "empty file")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "file too large")
        yv = None
        if yaw_views:
            try:
                yv = {str(k): float(x) for k, x in json.loads(yaw_views).items()}
            except (ValueError, AttributeError, TypeError):
                raise HTTPException(422, "yaw_views must be a JSON object of view -> yaw degrees")
        try:
            res = pipe.ingest(vehicle, data, view, kind, source_camera, yv, mm_per_px,
                              json_field(lens, 'lens'))
        except ValueError as e:
            raise HTTPException(422, str(e))
        res["defects"] = [decorate(d, key) for d in res["defects"]]
        return res

    @app.post("/vehicles/{vid}/videos", status_code=201)
    async def upload_video(
        vid: int,
        file: UploadFile = File(...),
        view: str = Form(...),
        source_camera: Optional[str] = Form(None),
        mm_per_px: Optional[float] = Form(None, gt=0),
        lens: Optional[str] = Form(None),
        key: Optional[str] = Depends(auth),
    ):
        """A short, steady clip of ONE walkaround view. Frames are sharpened-filtered, analysed, and
        only defects that stay locked to the bodywork across frames are logged (glare is dropped)."""
        vehicle = need_vehicle(vid)
        data = await file.read()
        if not data:
            raise HTTPException(400, "empty file")
        if len(data) > MAX_VIDEO_BYTES:
            raise HTTPException(413, "video too large; send a 3-5 second clip")
        try:
            res = pipe.ingest_video(vehicle, data, view, source_camera, json_field(lens, "lens"), mm_per_px)
        except ValueError as e:
            raise HTTPException(422, str(e))
        res["defects"] = [decorate(d, key) for d in res["defects"]]
        return res

    @app.get("/vehicles/{vid}/shots", dependencies=[Depends(auth)])
    def list_shots(vid: int, key: Optional[str] = Query(None)):
        need_vehicle(vid)
        return [{**s, "url": media_url(s["path"], key)} for s in db.list_shots(vid)]

    # -- defects ---------------------------------------------------------------------
    @app.get("/vehicles/{vid}/defects")
    def list_defects(vid: int, include_rejected: bool = False, key: Optional[str] = Depends(auth)):
        need_vehicle(vid)
        return [decorate(d, key) for d in db.list_defects(vid, include_rejected)]

    @app.get("/vehicles/{vid}/defects/export", dependencies=[Depends(auth)])
    def export_defects(vid: int, include_rejected: bool = False):
        """Defects in the inspection spec's schema: Defect_ID, Classification, Confidence_Score,
        Segmentation_Mask, Estimated_Physical_Dimensions, Panel_Location."""
        need_vehicle(vid)
        return {"vehicle_id": vid, "defects": [to_spec(d) for d in db.list_defects(vid, include_rejected)]}

    @app.patch("/defects/{did}")
    def patch_defect(did: int, p: DefectPatch, key: Optional[str] = Depends(auth)):
        d = db.get_defect(did)
        if not d:
            raise HTTPException(404, "defect not found")
        fields = p.model_dump(exclude_unset=True)
        if "status" in fields and fields["status"] not in STATUSES:
            raise HTTPException(422, f"status must be one of {sorted(STATUSES)}")
        if "severity" in fields and fields["severity"] not in ("minor", "moderate", "severe"):
            raise HTTPException(422, "severity must be minor, moderate or severe")
        db.update_defect(did, **fields)
        return decorate(db.get_defect(did), key)

    # -- outputs ---------------------------------------------------------------------
    @app.get("/vehicles/{vid}/report", response_class=HTMLResponse)
    def report(vid: int, embed: bool = False, key: Optional[str] = Depends(auth)):
        vehicle = need_vehicle(vid)
        defects = db.list_defects(vid)
        shots = db.list_shots(vid)
        url = make_embedder(media_dir) if embed else (lambda rel: media_url(rel, key))
        html = build_report(vehicle, defects, shots, datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC"), url)
        return HTMLResponse(html)

    @app.get("/vehicles/{vid}/viewer", response_class=HTMLResponse)
    def viewer(vid: int, key: Optional[str] = Depends(auth)):
        need_vehicle(vid)
        return HTMLResponse(render_viewer(vid, key))

    @app.get("/vehicles/{vid}/viewer-data")
    def viewer_data(vid: int, key: Optional[str] = Depends(auth)):
        vehicle = need_vehicle(vid)
        shots = db.list_shots(vid)
        latest: dict[str, dict] = {}
        for s in shots:
            if s["kind"] in ("photo", "derived") and s.get("view"):
                latest[s["view"]] = s
        order = zones.WALKAROUND_ORDER + [v for v in latest if v not in zones.WALKAROUND_ORDER]
        frames = [{"view": v, "shot_id": latest[v]["id"], "url": media_url(latest[v]["path"], key)}
                  for v in order if v in latest]
        pans = [{"label": f"{s.get('source_camera') or '360'} #{s['id']}", "url": media_url(s["path"], key)}
                for s in shots if s["kind"] == "equirect"]
        defects = [decorate(d, key) for d in db.list_defects(vid) if d["status"] != "rejected"]
        title = " ".join(str(x) for x in [vehicle.get("reg"), vehicle.get("make"), vehicle.get("model")] if x) \
            or f"Vehicle #{vid}"
        return {"title": title, "frames": frames, "panoramas": pans, "defects": defects}

    @app.get("/media/{path:path}")
    def media(path: str, key: Optional[str] = Depends(auth)):
        target = (media_dir / path).resolve()
        if media_dir.resolve() not in target.parents or not target.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(target)

    return app


app = create_app()
