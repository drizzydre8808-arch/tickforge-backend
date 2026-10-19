import cv2
import numpy as np
import pytest

from app import plate


def make_scene(text="AB12CDE"):
    img = np.full((720, 1280, 3), (90, 100, 95), np.uint8)
    cv2.rectangle(img, (300, 400), (980, 500), (40, 40, 40), 3)
    cv2.rectangle(img, (303, 403), (977, 497), (0, 220, 255), -1)
    cv2.putText(img, text, (330, 480), cv2.FONT_HERSHEY_DUPLEX, 3.1, (10, 10, 10), 6, cv2.LINE_AA)
    return img


def test_validation_and_repair():
    assert plate.is_valid_vrm("AB12CDE") and not plate.is_valid_vrm("HELLO")
    assert plate.fix_current_format("A812CDE") == "AB12CDE"
    assert plate.fix_current_format("ABI2CDE") == "AB12CDE"


def test_reads_synthetic_plate():
    pytest.importorskip("pytesseract")
    r = plate.read_plate(make_scene())
    assert r["best"] == "AB12CDE", r


def test_dvla_lookup_parses_and_errors():
    import io, json
    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): pass
    out = plate.dvla_lookup("ab12 cde", "k", opener=lambda req, timeout: R(json.dumps(
        {"registrationNumber": "AB12CDE", "make": "SEAT", "yearOfManufacture": 2019, "colour": "BLUE"}).encode()))
    assert out["make"] == "Seat" and out["year"] == 2019
    with pytest.raises(RuntimeError):
        plate.dvla_lookup("AB12CDE", None)
    with pytest.raises(ValueError):
        plate.dvla_lookup("NOPE", "k")
