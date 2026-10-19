"""Export defects in the host spec's output schema (Defect_ID, Classification, ...)."""
from __future__ import annotations

CLASS_TO_SPEC = {
    "dent": "Dent", "chip": "Chip", "scratch": "Scratch",
    "paint_damage": "Paint Damage", "rust": "Paint Damage",
}


def _corners(box):
    x0, y0, x1, y1 = box
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def to_spec(d: dict) -> dict:
    """One defect row -> the spec's payload.

    Classification is one of Dent / Chip / Scratch / Paint Damage; labels outside
    those four (cracks, broken parts, ...) are passed through title-cased rather
    than forced into the wrong class. Segmentation_Mask is the detector's polygon
    when it gave one, otherwise the bounding box corners (format says which).
    """
    size = d.get("size_mm") or {}
    mask = d.get("mask")
    return {
        "Defect_ID": f"D{d['vehicle_id']}-{d['id']:04d}",
        "Classification": CLASS_TO_SPEC.get(d["label"], d["label"].replace("_", " ").title()),
        "Confidence_Score": round(float(d.get("score") or 0), 2),
        "Segmentation_Mask": {
            "format": "polygon_normalised" if mask else "bbox_corners_normalised",
            "image_shot_id": d["shot_id"],
            "points": mask if mask else _corners(d["box"]),
        },
        "Estimated_Physical_Dimensions": {
            "length_mm": size.get("length_mm"), "width_mm": size.get("width_mm"),
            "area_mm2": size.get("area_mm2"), "area_basis": size.get("area_basis"),
            "min_detectable_mm": size.get("min_detectable_mm"), "approximate": True,
        } if size else None,
        "Panel_Location": d.get("panel"),
        "Location_Detail": d.get("description"),
        "Severity": d.get("severity"),
        "Review_Status": d.get("status"),
        "Seen_In_Views": d.get("seen_in"),
        "Detector": d.get("detector"),
    }
