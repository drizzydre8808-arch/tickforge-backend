from app.detection.base import iou
from app.detection.classical import ClassicalDetector
from app.synthetic import DEMO_DAMAGES, make_side_view


def test_finds_each_synthetic_defect_with_right_label():
    img, gts = make_side_view(damages=DEMO_DAMAGES)
    dets = ClassicalDetector().detect(img)
    for gt in gts:
        match = [d for d in dets if d.label == gt["kind"] and iou(d.box, gt["box"]) > 0.3]
        assert match, f"missed {gt['kind']} {gt['box']}; got {[(d.label, d.box) for d in dets]}"


def test_clean_car_gives_no_detections():
    for seed in (1, 2, 3):
        img, _ = make_side_view(damages=[], seed=seed)
        assert ClassicalDetector().detect(img) == []


def test_detections_are_plain_floats_and_normalised():
    img, _ = make_side_view(damages=DEMO_DAMAGES)
    for d in ClassicalDetector().detect(img):
        assert all(type(x) is float for x in d.box)
        assert 0 <= d.box[0] < d.box[2] <= 1 and 0 <= d.box[1] < d.box[3] <= 1
        assert 0 < d.score <= 1


def test_works_on_a_different_body_colour():
    img, gts = make_side_view(damages=DEMO_DAMAGES, body_bgr=(40, 40, 170), seed=5)   # red car
    dets = ClassicalDetector().detect(img)
    found = {g["kind"] for g in gts if any(d.label == g["kind"] and iou(d.box, g["box"]) > 0.3 for d in dets)}
    assert "scratch" in found and "dent" in found
