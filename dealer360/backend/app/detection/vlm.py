"""Multimodal-LLM detector driven by the inspection spec in prompts/inspection_spec.md.

How it works: the photo is cut into overlapping tiles (so small marks are shown
to the model at higher effective resolution than one downscaled full frame),
each tile goes to the model with the spec as the system prompt, and the JSON
defects it returns are mapped back to full-image coordinates and de-duplicated.

Be realistic about what this gives you:
  * Good at "is this a scratch / dent / chip or just a reflection or dirt" judgement.
  * Weaker at pixel-accurate localisation, so boxes are approximate. Treat it as
    a second opinion next to the trained YOLO model, not a replacement.
  * Costs one API call per tile per image. Images leave your server (number
    plates and customer vehicles are visible), so check your data-protection terms.

Enable with:  DEALER360_DETECTOR=vlm  ANTHROPIC_API_KEY=...  [DEALER360_VLM_MODEL=...]
              [DEALER360_VLM_TILES=2x2]     pip install anthropic
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from .base import LABELS, RawDetection, nms

log = logging.getLogger("dealer360.vlm")
SPEC_PATH = Path(__file__).parent / "prompts" / "inspection_spec.md"

# Return-format line requested in the spec notes.
JSON_ONLY_LINE = ("Return your response strictly in valid JSON format matching the schema "
                  "defined in Output Specifications.")

CLASS_TO_LABEL = {
    "dent": "dent", "chip": "chip", "scratch": "scratch", "paint damage": "paint_damage",
    "paint_damage": "paint_damage", "paint imperfection": "paint_damage",
}


def _parse_tiles(spec: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d)\s*[x,]\s*(\d)\s*", spec or "")
    return (int(m.group(1)), int(m.group(2))) if m else (2, 2)


def extract_json(text: str):
    """Pull the first JSON object/array out of a model reply (tolerates code fences / chatter)."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    # try whichever bracket opens first, so a top-level list isn't mistaken for the object inside it
    pairs = sorted((("{", "}"), ("[", "]")), key=lambda p: t.find(p[0]) if p[0] in t else len(t) + 1)
    for opener, closer in pairs:
        a, b = t.find(opener), t.rfind(closer)
        if a != -1 and b > a:
            try:
                return json.loads(t[a:b + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON found in model reply")


def _valid_box(b) -> Optional[tuple[float, float, float, float]]:
    try:
        x0, y0, x1, y1 = (float(v) for v in b)
    except (TypeError, ValueError):
        return None
    x0, x1 = sorted((min(max(x0, 0.0), 1.0), min(max(x1, 0.0), 1.0)))
    y0, y1 = sorted((min(max(y0, 0.0), 1.0), min(max(y1, 0.0), 1.0)))
    if x1 - x0 < 1e-4 or y1 - y0 < 1e-4:
        return None
    return (x0, y0, x1, y1)


def parse_defects(reply: str) -> list[dict]:
    data = extract_json(reply)
    if isinstance(data, dict):
        for k in ("defects", "Defects", "results", "Defect_List"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
        else:
            data = [data] if "Classification" in data else []
    return [d for d in data if isinstance(d, dict)]


class VlmDetector:
    name = "llm-vision"

    def __init__(self, model: Optional[str] = None, tiles: Optional[tuple[int, int]] = None,
                 overlap: float = 0.12, max_tokens: int = 4096, tile_max_side: int = 1568,
                 complete: Optional[Callable[[bytes, str], str]] = None, min_score: float = 0.35):
        self.model = model or os.environ.get("DEALER360_VLM_MODEL", "claude-sonnet-5-5")
        self.tiles = tiles or _parse_tiles(os.environ.get("DEALER360_VLM_TILES", "2x2"))
        self.overlap = overlap
        self.max_tokens = max_tokens
        self.tile_max_side = tile_max_side
        self.min_score = min_score
        self.system = SPEC_PATH.read_text(encoding="utf-8")
        self._complete = complete or self._anthropic_complete
        self._client = None

    # -- model call ---------------------------------------------------------------
    def _anthropic_complete(self, jpeg: bytes, user_text: str) -> str:  # pragma: no cover - needs network
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:
                raise RuntimeError("pip install anthropic") from e
            self._client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY
        msg = self._client.messages.create(
            model=self.model, max_tokens=self.max_tokens, system=self.system,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.b64encode(jpeg).decode()}},
                {"type": "text", "text": user_text},
            ]}],
        )
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    # -- tiling -------------------------------------------------------------------
    def _tile_rects(self) -> list[tuple[float, float, float, float]]:
        rows, cols = self.tiles
        rects = []
        for r in range(rows):
            for c in range(cols):
                x0, x1 = c / cols, (c + 1) / cols
                y0, y1 = r / rows, (r + 1) / rows
                ox, oy = self.overlap / cols, self.overlap / rows
                rects.append((max(0.0, x0 - ox), max(0.0, y0 - oy), min(1.0, x1 + ox), min(1.0, y1 + oy)))
        return rects

    def detect(self, image_bgr: np.ndarray) -> list[RawDetection]:
        h, w = image_bgr.shape[:2]
        out: list[RawDetection] = []
        for (tx0, ty0, tx1, ty1) in self._tile_rects():
            tile = image_bgr[int(ty0 * h):int(ty1 * h), int(tx0 * w):int(tx1 * w)]
            k = min(1.0, self.tile_max_side / max(tile.shape[:2]))
            if k < 1:
                tile = cv2.resize(tile, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", tile, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not ok:
                continue
            try:
                reply = self._complete(buf.tobytes(), JSON_ONLY_LINE)
                items = parse_defects(reply)
            except Exception as e:  # noqa: BLE001 - one bad tile shouldn't kill the whole photo
                log.warning("VLM tile failed: %s", e)
                continue
            for it in items:
                box = _valid_box(it.get("Bounding_Box") or it.get("bounding_box") or it.get("bbox"))
                if box is None:
                    continue
                cls = str(it.get("Classification", "")).strip().lower()
                label = CLASS_TO_LABEL.get(cls, cls if cls in LABELS else "other")
                try:
                    score = float(it.get("Confidence_Score", 0.5))
                except (TypeError, ValueError):
                    score = 0.5
                if score < self.min_score:
                    continue
                full = (tx0 + box[0] * (tx1 - tx0), ty0 + box[1] * (ty1 - ty0),
                        tx0 + box[2] * (tx1 - tx0), ty0 + box[3] * (ty1 - ty0))
                poly = None
                mask = it.get("Segmentation_Mask")
                if isinstance(mask, dict):
                    mask = mask.get("points") or mask.get("polygon")
                if isinstance(mask, list) and len(mask) >= 3:
                    try:
                        poly = [(tx0 + float(p[0]) * (tx1 - tx0), ty0 + float(p[1]) * (ty1 - ty0)) for p in mask][:64]
                    except (TypeError, ValueError, IndexError):
                        poly = None
                out.append(RawDetection(label, min(1.0, max(0.0, score)), tuple(float(v) for v in full),
                                        self.name, polygon=poly))
        return nms(out, 0.4)
