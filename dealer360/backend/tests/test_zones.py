import pytest

from app import zones
from app.config import DEFAULT_FRAME_BOX

FX0, FY0, FX1, FY1 = DEFAULT_FRAME_BOX


def box_at(u, v, size=0.01):
    """Normalised image box centred on frame coords (u, v)."""
    cx = FX0 + u * (FX1 - FX0)
    cy = FY0 + v * (FY1 - FY0)
    return (cx - size, cy - size, cx + size, cy + size)


def test_nearside_front_door_lower_rear():
    z = zones.resolve("nearside", box_at(0.50, 0.70))
    assert z.panel == "Nearside front door"
    assert z.face == "nearside"
    assert z.band == "mid"
    assert "rear edge" in z.description          # u=0.50 is the back of the door (0.28-0.52)
    assert z.car_position["along_length_pct"] == 50


def test_offside_view_is_mirrored():
    # In an offside photo the front of the car is on the RIGHT of the image,
    # so image u=0.5 is still the middle of the car, and u=0.9 is the front wing.
    z = zones.resolve("offside", box_at(0.82, 0.55))
    assert z.panel == "Offside front wing"
    assert zones.resolve("nearside", box_at(0.18, 0.55)).panel == "Nearside front wing"


def test_wheels_take_priority_over_sill_and_wing():
    assert zones.resolve("nearside", box_at(0.18, 0.85)).panel == "Nearside front wheel & tyre"
    assert zones.resolve("offside", box_at(0.18, 0.85)).panel == "Offside rear wheel & tyre"


def test_front_view_left_is_offside():
    assert zones.resolve("front", box_at(0.05, 0.45)).panel == "Offside front wing"
    assert zones.resolve("front", box_at(0.95, 0.45)).panel == "Nearside front wing"
    assert zones.resolve("front", box_at(0.50, 0.80)).panel == "Front bumper"


def test_rear_view_left_is_nearside():
    z = zones.resolve("rear", box_at(0.22, 0.45))
    assert z.panel == "Nearside tail light"
    assert zones.resolve("rear", box_at(0.78, 0.45)).panel == "Offside tail light"


def test_three_quarter_view_switches_face():
    # front_nearside: left 40% = front face, right 60% = nearside
    assert zones.resolve("front_nearside", box_at(0.20, 0.80)).face == "front"
    z = zones.resolve("front_nearside", box_at(0.90, 0.55))
    assert z.face == "nearside" and "rear" in z.panel.lower()
    # rear_offside: right 60% = offside face
    assert zones.resolve("rear_offside", box_at(0.90, 0.55)).face == "offside"


def test_box_outside_vehicle_frame_is_ignored():
    assert zones.resolve("nearside", (0.0, 0.0, 0.02, 0.02)) is None
    assert zones.resolve("nearside", (0.97, 0.95, 0.99, 0.99)) is None


def test_also_touches_when_box_spans_panels():
    # big box straddling the front door / rear door gap
    z = zones.resolve("nearside", box_at(0.52, 0.60, size=0.04))
    assert z.also_touches, z


def test_unknown_view_raises():
    with pytest.raises(KeyError):
        zones.resolve("underneath", box_at(0.5, 0.5))


def test_every_view_resolves_everywhere():
    # no gaps in the tables: every point in every view maps to a real panel
    for view in zones.VIEWS:
        for i in range(11):
            for j in range(11):
                z = zones.resolve(view, box_at(i / 10, j / 10, size=0.002))
                assert z is not None and z.panel_id in zones.PANELS


def test_anchor_for_all_panels_exists():
    for pid, (_, sided) in zones.PANELS.items():
        for side in (("nearside", "offside") if sided else ("centre",)):
            x, y = zones.anchor_for(pid, side)
            assert 0 <= x <= 200 and 0 <= y <= 440
