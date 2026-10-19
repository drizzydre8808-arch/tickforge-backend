"""Vehicle zone map.

Turns "a box at (x, y) in a photo taken from walkaround position V" into
"nearside front door, lower third, towards the rear edge", plus numeric
coordinates for logging and for the top-down diagram in the report.

Terminology is UK: *nearside* = left of the car (kerb side), *offside* = right
(driver side on a UK car). Views are named for the part of the car the camera
is looking at.

How it works
------------
Each walkaround view is split into one or two *segments*. A segment says
"this horizontal slice of the image shows this face of the car, running this
direction". The face then has a table of rectangles in its own (u, v) space
that name the panels. Tables are generic hatchback/saloon templates; real
bodies differ, and the three-quarter views are approximate because of
perspective. Treat the output as "which panel, roughly where", not survey data.

Faces and their axes
    nearside / offside : u = 0 at the front of the car, 1 at the rear;  v = 0 top, 1 bottom
    front / rear       : u = 0 at the offside edge, 1 at the nearside edge; v = 0 top, 1 bottom
    top                : u = 0 offside -> 1 nearside;  v = 0 front -> 1 rear
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

from .config import DEFAULT_FRAME_BOX

# panel_id -> (label, is_sided)
PANELS: dict[str, tuple[str, bool]] = {
    "bonnet": ("Bonnet", False),
    "grille": ("Grille", False),
    "windscreen": ("Windscreen", False),
    "roof": ("Roof", False),
    "rear_screen": ("Rear screen", False),
    "tailgate": ("Tailgate / boot lid", False),
    "front_bumper": ("Front bumper", True),
    "rear_bumper": ("Rear bumper", True),
    "headlight": ("Headlight", True),
    "taillight": ("Tail light", True),
    "a_pillar": ("A-pillar", True),
    "front_wing": ("Front wing", True),
    "front_door": ("Front door", True),
    "rear_door": ("Rear door", True),
    "front_door_window": ("Front door window", True),
    "rear_door_window": ("Rear door window", True),
    "rear_quarter": ("Rear quarter panel", True),
    "sill": ("Sill", True),
    "front_wheel": ("Front wheel & tyre", True),
    "rear_wheel": ("Rear wheel & tyre", True),
}

# (u0, u1, v0, v1, panel_id, side) ; side: "face" = the face's own side,
# otherwise "nearside" | "offside" | "centre".  First match wins, so put
# overlapping things (wheels) first.
_SIDE_TABLE = [
    (0.09, 0.27, 0.62, 1.00, "front_wheel", "face"),
    (0.73, 0.91, 0.62, 1.00, "rear_wheel", "face"),
    # upper band
    (0.00, 0.26, 0.00, 0.38, "bonnet", "centre"),
    (0.26, 0.38, 0.00, 0.38, "a_pillar", "face"),
    (0.38, 0.60, 0.00, 0.38, "front_door_window", "face"),
    (0.60, 0.78, 0.00, 0.38, "rear_door_window", "face"),
    (0.78, 0.94, 0.00, 0.38, "rear_quarter", "face"),
    (0.94, 1.00, 0.00, 0.38, "tailgate", "centre"),
    # middle band
    (0.00, 0.07, 0.38, 0.80, "front_bumper", "face"),
    (0.07, 0.28, 0.38, 0.80, "front_wing", "face"),
    (0.28, 0.52, 0.38, 0.80, "front_door", "face"),
    (0.52, 0.74, 0.38, 0.80, "rear_door", "face"),
    (0.74, 0.93, 0.38, 0.80, "rear_quarter", "face"),
    (0.93, 1.00, 0.38, 0.80, "rear_bumper", "face"),
    # lower band
    (0.00, 0.09, 0.80, 1.00, "front_bumper", "face"),
    (0.27, 0.73, 0.80, 1.00, "sill", "face"),
    (0.91, 1.00, 0.80, 1.00, "rear_bumper", "face"),
]

_FRONT_TABLE = [
    (0.00, 0.12, 0.00, 0.35, "a_pillar", "offside"),
    (0.88, 1.00, 0.00, 0.35, "a_pillar", "nearside"),
    (0.12, 0.88, 0.00, 0.35, "windscreen", "centre"),
    (0.00, 0.16, 0.35, 0.62, "front_wing", "offside"),
    (0.84, 1.00, 0.35, 0.62, "front_wing", "nearside"),
    (0.16, 0.36, 0.35, 0.62, "headlight", "offside"),
    (0.64, 0.84, 0.35, 0.62, "headlight", "nearside"),
    (0.36, 0.64, 0.47, 0.62, "grille", "centre"),
    (0.16, 0.84, 0.35, 0.47, "bonnet", "centre"),
    (0.00, 0.20, 0.62, 1.00, "front_bumper", "offside"),
    (0.80, 1.00, 0.62, 1.00, "front_bumper", "nearside"),
    (0.20, 0.80, 0.62, 1.00, "front_bumper", "centre"),
]

_REAR_TABLE = [
    (0.00, 0.12, 0.00, 0.35, "rear_quarter", "offside"),
    (0.88, 1.00, 0.00, 0.35, "rear_quarter", "nearside"),
    (0.12, 0.88, 0.00, 0.35, "rear_screen", "centre"),
    (0.00, 0.16, 0.35, 0.62, "rear_quarter", "offside"),
    (0.84, 1.00, 0.35, 0.62, "rear_quarter", "nearside"),
    (0.16, 0.30, 0.35, 0.62, "taillight", "offside"),
    (0.70, 0.84, 0.35, 0.62, "taillight", "nearside"),
    (0.30, 0.70, 0.35, 0.62, "tailgate", "centre"),
    (0.00, 0.20, 0.62, 1.00, "rear_bumper", "offside"),
    (0.80, 1.00, 0.62, 1.00, "rear_bumper", "nearside"),
    (0.20, 0.80, 0.62, 1.00, "rear_bumper", "centre"),
]

# top: u = lateral, v = front -> rear
_TOP_TABLE = [
    (0.0, 1.0, 0.00, 0.28, "bonnet", "centre"),
    (0.0, 1.0, 0.28, 0.40, "windscreen", "centre"),
    (0.0, 1.0, 0.40, 0.72, "roof", "centre"),
    (0.0, 1.0, 0.72, 0.82, "rear_screen", "centre"),
    (0.0, 1.0, 0.82, 1.00, "tailgate", "centre"),
]

FACE_TABLES = {
    "nearside": _SIDE_TABLE,
    "offside": _SIDE_TABLE,
    "front": _FRONT_TABLE,
    "rear": _REAR_TABLE,
    "top": _TOP_TABLE,
}


@dataclass(frozen=True)
class Segment:
    face: str
    x0: float
    x1: float
    reverse: bool = False


# Which slice of the (frame-normalised) image shows which face, and in which
# direction the face's u axis runs across the image. See the module docstring
# for the geometry; the 3/4 views assume ~40/60 foreshortening.
VIEWS: dict[str, list[Segment]] = {
    "front": [Segment("front", 0.0, 1.0, False)],            # image left = offside
    "rear": [Segment("rear", 0.0, 1.0, True)],               # image left = nearside
    "nearside": [Segment("nearside", 0.0, 1.0, False)],      # image left = front
    "offside": [Segment("offside", 0.0, 1.0, True)],         # image left = rear
    "front_nearside": [Segment("front", 0.0, 0.4, False), Segment("nearside", 0.4, 1.0, False)],
    "rear_nearside": [Segment("nearside", 0.0, 0.6, False), Segment("rear", 0.6, 1.0, True)],
    "front_offside": [Segment("offside", 0.0, 0.6, True), Segment("front", 0.6, 1.0, False)],
    "rear_offside": [Segment("rear", 0.0, 0.4, True), Segment("offside", 0.4, 1.0, True)],
    "roof": [Segment("top", 0.0, 1.0, False)],
}

# Order used for the walkaround spin viewer and the guided capture sequence.
WALKAROUND_ORDER = [
    "front", "front_nearside", "nearside", "rear_nearside",
    "rear", "rear_offside", "offside", "front_offside",
]


@dataclass
class ZoneResult:
    view: str
    face: str
    panel_id: str
    side: str            # nearside | offside | centre
    panel: str           # human label, e.g. "Nearside front door"
    band: str            # upper | mid | lower | top
    u: float             # box centre in face coords
    v: float
    along: float         # 0..1 within the panel (front->rear, or offside->nearside)
    vertical: float      # 0..1 within the panel (top->bottom, or front->rear on top face)
    also_touches: list[str] = field(default_factory=list)
    description: str = ""
    car_position: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _panel_label(panel_id: str, side: str) -> str:
    label, sided = PANELS[panel_id]
    if sided and side in ("nearside", "offside"):
        return f"{side.capitalize()} {label[0].lower()}{label[1:]}"
    if sided and side == "centre":
        return label
    return label


def _locate(view: str, x: float, y: float):
    """Frame-normalised point -> (face, u, v, rect) or None if the view is unknown."""
    segs = VIEWS.get(view)
    if not segs:
        raise KeyError(f"unknown view {view!r}")
    seg = segs[-1]
    for s in segs:
        if s.x0 <= x <= s.x1:
            seg = s
            break
    u = _clip((x - seg.x0) / (seg.x1 - seg.x0))
    if seg.reverse:
        u = 1.0 - u
    v = _clip(y)
    table = FACE_TABLES[seg.face]
    best, best_d = None, 1e9
    for rect in table:
        u0, u1, v0, v1 = rect[:4]
        if u0 <= u <= u1 and v0 <= v <= v1:
            best, best_d = rect, 0.0
            break
        du = max(u0 - u, 0.0, u - u1)
        dv = max(v0 - v, 0.0, v - v1)
        d = du * du + dv * dv
        if d < best_d:
            best, best_d = rect, d
    return seg.face, u, v, best


def _resolve_panel(face: str, rect) -> tuple[str, str]:
    panel_id, side = rect[4], rect[5]
    if side == "face":
        side = face
    return panel_id, side


def _band(v: float) -> str:
    return "upper" if v < 0.38 else ("mid" if v < 0.80 else "lower")


def _third(x: float, names: tuple[str, str, str]) -> str:
    return names[0] if x < 1 / 3 else (names[1] if x < 2 / 3 else names[2])


def _describe(label: str, face: str, along: float, vertical: float) -> str:
    if face == "top":
        vert = _third(vertical, ("front third", "middle", "rear third"))
        ends = ("offside edge", "nearside edge")
    else:
        vert = _third(vertical, ("upper third", "middle", "lower third"))
        ends = ("front edge", "rear edge") if face in ("nearside", "offside") else ("offside edge", "nearside edge")
    if along < 1 / 3:
        lat = f"towards the {ends[0]}"
    elif along > 2 / 3:
        lat = f"towards the {ends[1]}"
    else:
        lat = "in the centre"
    return f"{label}, {vert}, {lat} of the panel"


def resolve(view: str, box: tuple[float, float, float, float],
            frame_box: tuple[float, float, float, float] = DEFAULT_FRAME_BOX) -> Optional[ZoneResult]:
    """Map a normalised image box (x0, y0, x1, y1) to a vehicle zone.

    Returns None when the box centre falls outside the vehicle frame box
    (i.e. it's background, not the car).
    """
    fx0, fy0, fx1, fy1 = frame_box
    fw, fh = fx1 - fx0, fy1 - fy0
    x0, y0, x1, y1 = box
    cx, cy = ((x0 + x1) / 2 - fx0) / fw, ((y0 + y1) / 2 - fy0) / fh
    if not (-0.02 <= cx <= 1.02 and -0.02 <= cy <= 1.02):
        return None

    face, u, v, rect = _locate(view, _clip(cx), _clip(cy))
    panel_id, side = _resolve_panel(face, rect)
    label = _panel_label(panel_id, side)
    u0, u1, v0, v1 = rect[:4]
    along = _clip((u - u0) / (u1 - u0)) if u1 > u0 else 0.5
    vertical = _clip((v - v0) / (v1 - v0)) if v1 > v0 else 0.5

    # Other panels the box overlaps (7x7 sample grid inside the box).
    seen: dict[tuple[str, str], int] = {}
    n = 7
    for i in range(n):
        for j in range(n):
            px = ((x0 + (x1 - x0) * (i + 0.5) / n) - fx0) / fw
            py = ((y0 + (y1 - y0) * (j + 0.5) / n) - fy0) / fh
            f2, _, _, r2 = _locate(view, _clip(px), _clip(py))
            key = _resolve_panel(f2, r2)
            seen[key] = seen.get(key, 0) + 1
    primary = (panel_id, side)
    also = [
        _panel_label(pid, sd)
        for (pid, sd), cnt in sorted(seen.items(), key=lambda kv: -kv[1])
        if (pid, sd) != primary and cnt / (n * n) >= 0.15
    ]

    # Car-level position (only meaningful for side views; 3/4 views are approximate).
    car_position: dict = {}
    if face in ("nearside", "offside"):
        car_position = {
            "along_length_pct": round(u * 100),     # 0 = front bumper, 100 = rear bumper
            "height_pct": round((1 - v) * 100),     # 0 = ground, 100 = roofline
        }
    elif face in ("front", "rear"):
        car_position = {
            "across_width_pct_from_offside": round(u * 100),
            "height_pct": round((1 - v) * 100),
        }
    elif face == "top":
        car_position = {"along_length_pct": round(v * 100), "across_width_pct_from_offside": round(u * 100)}

    desc = _describe(label, face, along, vertical)
    if also:
        desc += "; also touches " + ", ".join(also)

    return ZoneResult(
        view=view, face=face, panel_id=panel_id, side=side, panel=label,
        band="top" if face == "top" else _band(v), u=round(u, 4), v=round(v, 4),
        along=round(along, 4), vertical=round(vertical, 4),
        also_touches=also, description=desc, car_position=car_position,
    )


# Top-down diagram anchors for the report: (panel_id, side) -> (x, y) in a 200x440
# viewBox, car facing up, nearside on the left.
ANCHORS: dict[tuple[str, str], tuple[int, int]] = {
    ("bonnet", "centre"): (100, 85), ("grille", "centre"): (100, 30),
    ("windscreen", "centre"): (100, 140), ("roof", "centre"): (100, 215),
    ("rear_screen", "centre"): (100, 300), ("tailgate", "centre"): (100, 355),
    ("front_bumper", "centre"): (100, 22), ("front_bumper", "nearside"): (55, 26),
    ("front_bumper", "offside"): (145, 26),
    ("rear_bumper", "centre"): (100, 418), ("rear_bumper", "nearside"): (55, 414),
    ("rear_bumper", "offside"): (145, 414),
    ("headlight", "nearside"): (62, 46), ("headlight", "offside"): (138, 46),
    ("taillight", "nearside"): (62, 398), ("taillight", "offside"): (138, 398),
    ("a_pillar", "nearside"): (48, 140), ("a_pillar", "offside"): (152, 140),
    ("front_wing", "nearside"): (40, 95), ("front_wing", "offside"): (160, 95),
    ("front_door", "nearside"): (34, 175), ("front_door", "offside"): (166, 175),
    ("rear_door", "nearside"): (34, 250), ("rear_door", "offside"): (166, 250),
    ("front_door_window", "nearside"): (52, 180), ("front_door_window", "offside"): (148, 180),
    ("rear_door_window", "nearside"): (52, 250), ("rear_door_window", "offside"): (148, 250),
    ("rear_quarter", "nearside"): (40, 330), ("rear_quarter", "offside"): (160, 330),
    ("rear_quarter", "centre"): (100, 330),
    ("sill", "nearside"): (24, 215), ("sill", "offside"): (176, 215),
    ("front_wheel", "nearside"): (16, 92), ("front_wheel", "offside"): (184, 92),
    ("rear_wheel", "nearside"): (16, 345), ("rear_wheel", "offside"): (184, 345),
}


def anchor_for(panel_id: str, side: str) -> tuple[int, int]:
    return ANCHORS.get((panel_id, side)) or ANCHORS.get((panel_id, "centre")) or (100, 220)
