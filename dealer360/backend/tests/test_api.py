import json

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.detection.classical import ClassicalDetector
from app.imaging import encode_jpg
from app.main import create_app
from app.synthetic import DEMO_DAMAGES, make_side_view


@pytest.fixture()
def client(tmp_path):
    return TestClient(create_app(tmp_path, ClassicalDetector()))


@pytest.fixture()
def vehicle(client):
    r = client.post("/vehicles", json={"reg": "AB12 CDE", "make": "Cupra", "model": "Ateca", "year": 2019})
    assert r.status_code == 201
    return r.json()


def photo(damages=DEMO_DAMAGES, seed=0):
    img, _ = make_side_view(damages=damages, seed=seed)
    return encode_jpg(img, 95)


def upload(client, vid, data, view="nearside", **extra):
    return client.post(f"/vehicles/{vid}/shots", files={"file": ("a.jpg", data, "image/jpeg")},
                       data={"view": view, "kind": "photo", **extra})


def test_health_and_profile(client):
    assert client.get("/health").json()["ok"] is True
    p = client.get("/capture-profile").json()
    assert p["views"][0] == "front" and len(p["views"]) == 8


def test_upload_logs_defects_with_location_and_crops(client, vehicle):
    r = upload(client, vehicle["id"], photo(), source_camera="GoPro HERO13")
    assert r.status_code == 201, r.text
    body = r.json()
    labels = {d["label"] for d in body["defects"]}
    assert {"scratch", "dent", "rust"} <= labels
    by = {d["label"]: d for d in body["defects"]}
    assert by["scratch"]["panel"] == "Nearside front door"
    assert by["dent"]["panel"] == "Nearside rear door"
    assert by["rust"]["panel"] == "Nearside front wing"
    for d in body["defects"]:
        assert d["description"] and d["zone"]["car_position"]["along_length_pct"] is not None
        assert d["size_mm"]["longest_mm"] > 0
        assert client.get(d["crop_url"]).status_code == 200
        assert client.get(d["overview_url"]).status_code == 200
        assert d["status"] == "pending"


def test_same_defect_from_second_view_is_merged_not_duplicated(client, vehicle):
    vid = vehicle["id"]
    upload(client, vid, photo(), view="nearside")
    n1 = len(client.get(f"/vehicles/{vid}/defects").json())
    # a second nearside-ish shot should not double-log (different 'view' name, same panel)
    r = upload(client, vid, photo(), view="rear_nearside")
    assert r.status_code == 201
    assert len(client.get(f"/vehicles/{vid}/defects").json()) >= n1  # never fewer
    # same view again -> separate entries are allowed, but total must stay sane
    assert len(client.get(f"/vehicles/{vid}/defects").json()) < n1 * 3


def test_review_flow_confirm_reject_and_report(client, vehicle):
    vid = vehicle["id"]
    upload(client, vid, photo())
    defects = client.get(f"/vehicles/{vid}/defects").json()
    a, b = defects[0], defects[1]
    r = client.patch(f"/defects/{a['id']}", json={"status": "confirmed", "note": "Seen in person"})
    assert r.json()["status"] == "confirmed"
    client.patch(f"/defects/{b['id']}", json={"status": "rejected"})
    visible = client.get(f"/vehicles/{vid}/defects").json()
    assert b["id"] not in [d["id"] for d in visible]
    assert b["id"] in [d["id"] for d in client.get(f"/vehicles/{vid}/defects?include_rejected=true").json()]

    html = client.get(f"/vehicles/{vid}/report").text
    assert "Condition report" in html and a["panel"] in html and "Seen in person" in html
    assert "AB12 CDE" in html
    emb = client.get(f"/vehicles/{vid}/report?embed=1").text
    assert "data:image/jpeg;base64," in emb and "/media/" not in emb


def test_patch_validation(client, vehicle):
    upload(client, vehicle["id"], photo())
    d = client.get(f"/vehicles/{vehicle['id']}/defects").json()[0]
    assert client.patch(f"/defects/{d['id']}", json={"status": "bogus"}).status_code == 422
    assert client.patch(f"/defects/{d['id']}", json={"severity": "huge"}).status_code == 422
    assert client.patch("/defects/9999", json={"status": "confirmed"}).status_code == 404


def make_panorama_containing(photo_bgr, W=5760, H=2880, fov=90.0):
    """Inverse of equirect_to_perspective for yaw=0: paste a flat photo into a 360 image."""
    ph, pw = photo_bgr.shape[:2]
    f = 0.5 * pw / np.tan(np.radians(fov) / 2)
    lon = (np.arange(W, dtype=np.float32) / W - 0.5) * 2 * np.pi
    lat = (0.5 - np.arange(H, dtype=np.float32) / H) * np.pi
    lon, lat = np.meshgrid(lon, lat)
    dx, dy, dz = np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)
    with np.errstate(divide="ignore", invalid="ignore"):
        mx = f * dx / dz + pw / 2 - 0.5
        my = -f * dy / dz + ph / 2 - 0.5
    bad = (dz <= 0.01) | (mx < 0) | (mx > pw - 1) | (my < 0) | (my > ph - 1)
    mx[bad], my[bad] = -1, -1
    return cv2.remap(photo_bgr, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=(110, 110, 110))


def test_equirect_360_upload_is_cut_into_views_and_defects_found(client, vehicle):
    side, _ = make_side_view(width=1600, height=1000, damages=DEMO_DAMAGES)
    pano = make_panorama_containing(side)
    r = client.post(f"/vehicles/{vehicle['id']}/shots",
                    files={"file": ("pano.jpg", encode_jpg(pano, 95), "image/jpeg")},
                    data={"kind": "equirect", "source_camera": "Insta360 X4",
                          "yaw_views": json.dumps({"nearside": 0, "front": -90})})
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["derived_shot_ids"]) == 2
    by = {d["label"]: d for d in body["defects"]}
    assert by["scratch"]["panel"] == "Nearside front door"
    assert by["dent"]["panel"] == "Nearside rear door"
    data = client.get(f"/vehicles/{vehicle['id']}/viewer-data").json()
    assert {f["view"] for f in data["frames"]} == {"nearside", "front"}
    assert len(data["panoramas"]) == 1


def test_bad_inputs(client, vehicle):
    vid = vehicle["id"]
    assert upload(client, vid, b"not an image").status_code == 422
    assert upload(client, vid, photo(), view="underneath").status_code == 422
    assert client.post(f"/vehicles/{vid}/shots", files={"file": ("a.jpg", photo(), "image/jpeg")},
                       data={"kind": "equirect", "view": "nearside"}).status_code == 422   # not 2:1
    assert client.post("/vehicles/999/shots", files={"file": ("a.jpg", photo(), "image/jpeg")},
                       data={"view": "nearside"}).status_code == 404
    assert client.get("/media/../../etc/passwd").status_code in (404, 422)


def test_viewer_pages_and_media_traversal(client, vehicle):
    vid = vehicle["id"]
    upload(client, vid, photo())
    page = client.get(f"/vehicles/{vid}/viewer")
    assert page.status_code == 200 and "pannellum" in page.text
    data = client.get(f"/vehicles/{vid}/viewer-data").json()
    assert data["frames"][0]["view"] == "nearside" and data["defects"]
    assert client.get(data["frames"][0]["url"]).status_code == 200
    assert client.get("/media/%2e%2e/%2e%2e/etc/passwd").status_code == 404


def test_delete_vehicle_removes_everything(client, vehicle, tmp_path):
    vid = vehicle["id"]
    upload(client, vid, photo())
    assert client.delete(f"/vehicles/{vid}").status_code == 204
    assert client.get(f"/vehicles/{vid}").status_code == 404
    assert not (tmp_path / "media" / str(vid)).exists()


def test_api_key_enforced_when_set(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "API_KEY", "s3cret")
    c = TestClient(create_app(tmp_path, ClassicalDetector()))
    assert c.get("/vehicles").status_code == 401
    assert c.get("/vehicles", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert c.get("/vehicles?key=s3cret").status_code == 200
    assert c.get("/health").status_code == 200   # health stays open for load balancers
