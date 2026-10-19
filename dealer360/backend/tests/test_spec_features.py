import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.detection.base import iou
from app.detection.classical import ClassicalDetector
from app.detection.vlm import VlmDetector, extract_json, parse_defects
from app.imaging import encode_jpg
from app.lens import fisheye_to_rectilinear
from app.main import create_app
from app.quality import min_detectable_mm, select_sharp, sharpness
from app.spec import to_spec
from app.synthetic import DEMO_DAMAGES, make_side_view
from app.tracking import confirm_detections


# ---------------------------------------------------------------- quality / blur
def textured(seed=0, size=(900, 1600)):
    rng = np.random.default_rng(seed)
    return (rng.random((*size, 3)) * 255).astype(np.uint8)


def test_sharpness_ranks_blur_lower_and_select_sharp_drops_it():
    sharp = textured()
    blurry = cv2.GaussianBlur(sharp, (0, 0), 6)
    assert sharpness(sharp) > 5 * sharpness(blurry)
    frames = [sharp, blurry, sharp.copy(), sharp.copy(), cv2.GaussianBlur(sharp, (0, 0), 8)]
    keep = select_sharp(frames, keep=0.8, min_keep=2)
    assert 1 not in keep and 4 not in keep and keep == sorted(keep)


def test_min_detectable_is_about_three_pixels():
    assert min_detectable_mm(0.5) == 1.5
    # 0.1 mm marks need <= ~0.03 mm/px: far beyond a 360/action camera at normal distance
    assert min_detectable_mm(2.0) > 5


# ---------------------------------------------------------------- lens
def rect_to_fisheye(rect, fov_deg, out_fov_deg):
    """Test helper: forward-distort a rectilinear image so we can check the inverse."""
    h, w = rect.shape[:2]
    f_in = (w / 2) / np.radians(fov_deg / 2)
    f_rect = (w / 2) / np.tan(np.radians(out_fov_deg / 2))
    xs = np.arange(w, dtype=np.float32) - w / 2 + 0.5
    ys = np.arange(h, dtype=np.float32) - h / 2 + 0.5
    x, y = np.meshgrid(xs, ys)
    r = np.hypot(x, y)
    theta = r / f_in
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(r > 1e-6, f_rect * np.tan(theta) / r, f_rect / f_in)
    return cv2.remap(rect, (x * s + w / 2 - 0.5).astype(np.float32), (y * s + h / 2 - 0.5).astype(np.float32),
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)


def test_fisheye_round_trip_restores_straight_lines():
    rect = np.full((600, 900, 3), 255, np.uint8)
    for x in range(100, 900, 100):                       # a grid of straight lines
        cv2.line(rect, (x, 0), (x, 599), (0, 0, 0), 3)
    for y in range(100, 600, 100):
        cv2.line(rect, (0, y), (899, y), (0, 0, 0), 3)
    fish = rect_to_fisheye(rect, 120, 100)
    assert np.abs(fish.astype(int) - rect.astype(int)).mean() > 8        # distortion is real
    back = fisheye_to_rectilinear(fish, 120, 100)
    c = (slice(150, 450), slice(225, 675))                               # central region
    assert np.abs(back[c].astype(int) - rect[c].astype(int)).mean() < 22  # and mostly undone


def test_fisheye_rejects_bad_params():
    with pytest.raises(ValueError):
        fisheye_to_rectilinear(np.zeros((10, 10, 3), np.uint8), 5)


# ---------------------------------------------------------------- tracking
def shift(img, dx, dy):
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE)


@pytest.fixture(scope="module")
def pass_frames():
    """5 frames of a car as the operator drifts, with a glare streak fixed to the CAMERA, not the car."""
    base, gts = make_side_view(damages=DEMO_DAMAGES)
    shifts = [(0, 0), (34, 8), (-30, 4), (52, -8), (-46, 10)]
    frames = []
    for dx, dy in shifts:
        f = shift(base, dx, dy)
        cv2.line(f, (900, 640), (1010, 626), (235, 235, 245), 3, cv2.LINE_AA)   # same screen spot every frame
        frames.append(f)
    det = ClassicalDetector()
    return frames, [det.detect(f) for f in frames], gts


def test_tracking_keeps_real_defects_and_drops_camera_locked_glare(pass_frames):
    frames, dets, gts = pass_frames
    confirmed, rejected, info = confirm_detections(frames, dets, ref_idx=0, min_hits=3)
    assert info["registered"] >= 4, info
    kinds = [d.label for d in confirmed]
    gt = {g["kind"]: g["box"] for g in gts}
    for kind in ("scratch", "dent", "rust"):
        assert any(d.label == kind and iou(d.box, gt[kind]) > 0.25 for d in confirmed), (kind, kinds, rejected)
    # only ONE scratch survives (the real one); the glare streak was rejected as an unlocked track
    assert kinds.count("scratch") == 1
    assert any(r["label"] == "scratch" and r["hits"] < 3 for r in rejected)


def test_tracking_needs_enough_registered_frames():
    img = np.full((600, 900, 3), 128, np.uint8)      # featureless: cannot be registered
    confirmed, rejected, info = confirm_detections([img, img.copy(), img.copy()], [[], [], []])
    assert confirmed == [] and info["registered"] <= 1


# ---------------------------------------------------------------- VLM detector
FAKE_REPLY = """Here you go:
```json
{"defects": [
 {"Defect_ID": "A1", "Classification": "Scratch", "Confidence_Score": 0.9,
  "Bounding_Box": [0.10, 0.20, 0.30, 0.25], "Segmentation_Mask": [[0.1,0.2],[0.3,0.2],[0.3,0.25]]},
 {"Defect_ID": "A2", "Classification": "Paint Damage", "Confidence_Score": 0.1, "Bounding_Box": [0.5,0.5,0.6,0.6]},
 {"Defect_ID": "A3", "Classification": "Chip", "Confidence_Score": 0.8, "Bounding_Box": [0.9, 0.9, 0.2, 0.2]},
 {"Defect_ID": "A4", "Classification": "Dent", "Confidence_Score": 0.7, "Bounding_Box": "nonsense"}
]}
```"""


def test_extract_json_handles_fences_and_chatter():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! [{"a": 1}] hope that helps') == [{"a": 1}]
    with pytest.raises(ValueError):
        extract_json("no json here")
    assert parse_defects('{"defects": []}') == []


def test_vlm_detector_tiles_maps_coordinates_and_filters():
    calls = []

    def fake(jpeg, text):
        calls.append(text)
        return FAKE_REPLY

    det = VlmDetector(tiles=(1, 2), overlap=0.0, complete=fake)
    img = np.zeros((600, 1000, 3), np.uint8)
    out = det.detect(img)
    assert len(calls) == 2 and "strictly in valid JSON" in calls[0]
    # per tile: A1 kept, A2 low confidence dropped, A3 (swapped corners) normalised, A4 invalid dropped
    labels = sorted(d.label for d in out)
    assert labels.count("scratch") == 2 and "chip" in labels and "paint_damage" not in labels
    left = [d for d in out if d.label == "scratch" and d.box[2] <= 0.5]
    right = [d for d in out if d.label == "scratch" and d.box[0] >= 0.5]
    assert left and right                                   # one per tile, mapped into full-image coords
    assert abs(right[0].box[0] - (0.5 + 0.10 * 0.5)) < 1e-6
    assert right[0].polygon and len(right[0].polygon) == 3


def test_vlm_tile_failure_does_not_kill_the_photo():
    n = {"i": 0}

    def flaky(jpeg, text):
        n["i"] += 1
        if n["i"] == 1:
            raise RuntimeError("API down")
        return FAKE_REPLY

    out = VlmDetector(tiles=(1, 2), overlap=0.0, complete=flaky).detect(np.zeros((600, 1000, 3), np.uint8))
    assert any(d.label == "scratch" for d in out)


def test_spec_prompt_contains_user_spec_and_host_fields():
    det = VlmDetector(complete=lambda *_: "{}")
    assert "OUTPUT PAYLOAD SPECIFICATIONS" in det.system and "Bounding_Box" in det.system


# ---------------------------------------------------------------- spec export + API
@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(tmp_path, ClassicalDetector()))


@pytest.fixture()
def vid(client):
    return client.post("/vehicles", json={"reg": "ZZ99 ZZZ"}).json()["id"]


def test_export_matches_spec_schema_and_enum(client, vid):
    img, _ = make_side_view(damages=DEMO_DAMAGES)
    r = client.post(f"/vehicles/{vid}/shots", files={"file": ("a.jpg", encode_jpg(img, 95), "image/jpeg")},
                    data={"view": "nearside", "kind": "photo"})
    assert r.status_code == 201
    out = client.get(f"/vehicles/{vid}/defects/export").json()["defects"]
    assert len(out) >= 3
    for d in out:
        assert set(["Defect_ID", "Classification", "Confidence_Score", "Segmentation_Mask",
                    "Estimated_Physical_Dimensions", "Panel_Location"]) <= set(d)
        assert d["Classification"] in {"Dent", "Chip", "Scratch", "Paint Damage"}
        assert 0.0 <= d["Confidence_Score"] <= 1.0
        dims = d["Estimated_Physical_Dimensions"]
        assert dims["length_mm"] >= dims["width_mm"] > 0 and dims["area_mm2"] >= 0
        assert d["Segmentation_Mask"]["format"] == "polygon_normalised"      # classical gives outlines
        assert len(d["Segmentation_Mask"]["points"]) >= 3
    classes = {d["Classification"] for d in out}
    assert {"Dent", "Scratch"} <= classes
    # rust maps onto Paint Damage rather than inventing a fifth class
    assert to_spec({"id": 1, "vehicle_id": 1, "shot_id": 1, "label": "rust", "box": [0, 0, 1, 1]})["Classification"] == "Paint Damage"
    assert to_spec({"id": 1, "vehicle_id": 1, "shot_id": 1, "label": "crack", "box": [0, 0, 1, 1]})["Segmentation_Mask"]["format"] \
        == "bbox_corners_normalised"


def test_mm_per_px_override_and_quality_reported(client, vid):
    img, _ = make_side_view(damages=DEMO_DAMAGES)
    r = client.post(f"/vehicles/{vid}/shots", files={"file": ("a.jpg", encode_jpg(img, 95), "image/jpeg")},
                    data={"view": "front_nearside", "kind": "photo", "mm_per_px": "0.4"})
    assert r.status_code == 201, r.text
    d = r.json()["defects"]
    assert d and all(x["size_mm"]["scale_source"] == "client" and x["size_mm"]["mm_per_px"] == 0.4 for x in d)
    shots = client.get(f"/vehicles/{vid}/shots").json()
    q = shots[0]["quality"]
    assert q["sharpness"] > 0 and q["min_detectable_mm"] == 1.2


def test_three_quarter_view_without_scale_has_no_size_guess(client, vid):
    img, _ = make_side_view(damages=DEMO_DAMAGES)
    r = client.post(f"/vehicles/{vid}/shots", files={"file": ("a.jpg", encode_jpg(img, 95), "image/jpeg")},
                    data={"view": "front_nearside", "kind": "photo"})
    assert all(x["size_mm"] is None for x in r.json()["defects"])


def test_lens_profile_creates_corrected_derived_shot(client, vid):
    img, _ = make_side_view(damages=DEMO_DAMAGES)
    r = client.post(f"/vehicles/{vid}/shots", files={"file": ("a.jpg", encode_jpg(img, 95), "image/jpeg")},
                    data={"view": "nearside", "kind": "photo",
                          "lens": json.dumps({"model": "equidistant", "fov_deg": 120})})
    assert r.status_code == 201, r.text
    assert len(r.json()["derived_shot_ids"]) == 1
    bad = client.post(f"/vehicles/{vid}/shots", files={"file": ("a.jpg", encode_jpg(img, 95), "image/jpeg")},
                      data={"view": "nearside", "lens": json.dumps({"model": "equidistant"})})
    assert bad.status_code == 422
    bad2 = client.post(f"/vehicles/{vid}/shots", files={"file": ("a.jpg", encode_jpg(img, 95), "image/jpeg")},
                       data={"view": "nearside", "lens": "not json"})
    assert bad2.status_code == 422


def make_clip(path, frames, fps=4):
    h, w = frames[0].shape[:2]
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    for f in frames:
        vw.write(f)
    vw.release()


def test_video_upload_keeps_locked_defects_and_reports_glare(client, vid, pass_frames, tmp_path):
    frames, _, _ = pass_frames
    clip = tmp_path / "pass.avi"
    make_clip(clip, frames * 2)                    # 10 frames at 4 fps
    r = client.post(f"/vehicles/{vid}/videos", files={"file": ("pass.avi", clip.read_bytes(), "video/x-msvideo")},
                    data={"view": "nearside", "source_camera": "Insta360 X4"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["tracking"]["frames_extracted"] == 10
    labels = [d["label"] for d in body["defects"]]
    assert "dent" in labels and labels.count("scratch") == 1
    assert body["tracking"]["rejected_as_glare_or_noise"]
    assert all(d["detector"] == "tracked" for d in body["defects"])


def test_video_rejects_garbage_and_bad_view(client, vid):
    assert client.post(f"/vehicles/{vid}/videos", files={"file": ("x.mp4", b"not a video", "video/mp4")},
                       data={"view": "nearside"}).status_code == 422
    assert client.post(f"/vehicles/{vid}/videos", files={"file": ("x.mp4", b"x", "video/mp4")},
                       data={"view": "underneath"}).status_code == 422
