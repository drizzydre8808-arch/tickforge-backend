import numpy as np

from app.imaging import annotated_overview, crop_defect, equirect_to_perspective, estimate_size_mm


def make_equirect(marker_lon_deg: float, w=2000, h=1000):
    eq = np.full((h, w, 3), 90, np.uint8)
    cx = int((marker_lon_deg / 360 + 0.5) * w)
    cy = h // 2
    eq[cy - 25:cy + 25, cx - 25:cx + 25] = (0, 0, 255)  # red square on the horizon
    return eq


def red_centroid_x(img):
    red = (img[..., 2] > 200) & (img[..., 0] < 60)
    xs = np.where(red.any(axis=0))[0]
    return None if len(xs) == 0 else float(xs.mean())


def test_perspective_centres_marker_at_matching_yaw():
    eq = make_equirect(90)
    flat = equirect_to_perspective(eq, yaw_deg=90, out_w=800, out_h=500)
    cx = red_centroid_x(flat)
    assert cx is not None and abs(cx - 400) < 8


def test_perspective_marker_absent_when_looking_away():
    eq = make_equirect(90)
    flat = equirect_to_perspective(eq, yaw_deg=-90, out_w=800, out_h=500)
    assert red_centroid_x(flat) is None


def test_perspective_wraps_across_seam():
    eq = make_equirect(180 - 1)  # near the seam
    flat = equirect_to_perspective(eq, yaw_deg=180, out_w=800, out_h=500)
    assert red_centroid_x(flat) is not None


def test_crop_and_overview_shapes():
    img = np.zeros((900, 1600, 3), np.uint8)
    crop = crop_defect(img, (0.40, 0.50, 0.44, 0.54))
    assert crop.shape[0] >= 192 and crop.shape[1] >= 192
    over = annotated_overview(img, (0.40, 0.50, 0.44, 0.54), "#1 dent")
    assert max(over.shape[:2]) <= 1600


def test_size_estimate_side_view_and_skips_three_quarter():
    fb = (0.04, 0.22, 0.96, 0.88)
    # box 10% of image width on a 4400 mm long car filling 92% of the image
    s = estimate_size_mm((0.40, 0.5, 0.50, 0.55), "nearside", 1600, 900, fb, 4400, 1800)
    assert 450 <= s["length_mm"] <= 520          # box is wider than tall, so length = box width
    assert s["min_detectable_mm"] == round(3 * s["mm_per_px"], 2)
    assert estimate_size_mm((0.4, 0.5, 0.5, 0.55), "front_nearside", 1600, 900, fb, 4400, 1800) is None
