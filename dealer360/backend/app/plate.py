"""UK number plate (VRM) reading and DVLA lookup.

Reading: find plate-shaped regions (wide, high-contrast rectangles), OCR them with
Tesseract restricted to A-Z/0-9, and keep only strings that fit a UK format. Always
show the result to the dealer to confirm; OCR on dirty/angled plates is not reliable.
Lookup: DVLA Vehicle Enquiry Service (needs DVLA_API_KEY). It returns make, colour,
year, fuel, MOT and tax status, but not model or dimensions.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Optional

import cv2
import numpy as np

# Current (AB12 CDE), prefix (A123 BCD), suffix (ABC 123D), dateless-ish short forms
UK_PATTERNS = [
    re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z]{3}$"),
    re.compile(r"^[A-Z][0-9]{1,3}[A-Z]{3}$"),
    re.compile(r"^[A-Z]{3}[0-9]{1,3}[A-Z]$"),
    re.compile(r"^[A-Z]{1,3}[0-9]{1,4}$"),
    re.compile(r"^[0-9]{1,4}[A-Z]{1,3}$"),
]
_TO_DIGIT = str.maketrans("OIZSBGQ", "0125860")
_TO_ALPHA = str.maketrans("0125860", "OIZSBGQ")


def normalise(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def is_valid_vrm(s: str) -> bool:
    return any(p.match(s) for p in UK_PATTERNS)


def fix_current_format(s: str) -> str:
    """For 7-char strings, apply the AB12CDE letter/digit positions to repair O/0, I/1 etc."""
    if len(s) != 7:
        return s
    out = []
    for i, ch in enumerate(s):
        out.append(ch.translate(_TO_DIGIT) if i in (2, 3) else ch.translate(_TO_ALPHA))
    return "".join(out)


def _regions(img: np.ndarray) -> list[np.ndarray]:
    h, w = img.shape[:2]
    k = 1280 / max(h, w)
    small = cv2.resize(img, None, fx=k, fy=k) if k < 1 else img
    s = small.shape[1] / w
    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    g = cv2.bilateralFilter(g, 9, 60, 60)
    edges = cv2.Canny(g, 60, 180)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5)))
    cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:12]:
        x, y, bw, bh = cv2.boundingRect(c)
        if bh < 12 or bw < 60 or not (2.0 <= bw / bh <= 8.5):
            continue
        pad = int(bh * 0.15)
        x0, y0 = max(0, x - pad), max(0, y - pad)
        out.append(img[int(y0 / s):int((y + bh + pad) / s), int(x0 / s):int((x + bw + pad) / s)])
    return out


def _ocr(crop: np.ndarray) -> list[str]:
    import pytesseract

    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    if g.shape[0] < 80:
        g = cv2.resize(g, None, fx=80 / g.shape[0], fy=80 / g.shape[0], interpolation=cv2.INTER_CUBIC)
    outs = []
    for variant in (g, cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
                    255 - cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]):
        txt = pytesseract.image_to_string(
            variant, config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
        n = normalise(txt)
        if n:
            outs.append(n)
    return outs


def read_plate(img: np.ndarray) -> dict:
    """Returns {"best": str|None, "candidates": [{"vrm","valid","votes"}]}."""
    votes: dict[str, int] = {}
    try:
        crops = _regions(img) or [img]
        for crop in crops:
            for n in _ocr(crop):
                for cand in {n, fix_current_format(n)}:
                    if 2 <= len(cand) <= 8:
                        votes[cand] = votes.get(cand, 0) + 1
    except Exception as e:  # tesseract missing etc.
        return {"best": None, "candidates": [], "error": str(e)}
    cands = [{"vrm": v, "valid": is_valid_vrm(v), "votes": n} for v, n in votes.items()]
    cands.sort(key=lambda c: (c["valid"], c["votes"], len(c["vrm"]) == 7), reverse=True)
    best = cands[0]["vrm"] if cands and cands[0]["valid"] else None
    return {"best": best, "candidates": cands[:5]}


def dvla_lookup(vrm: str, api_key: Optional[str], opener=urllib.request.urlopen) -> dict:
    if not api_key:
        raise RuntimeError("DVLA_API_KEY is not set on the server")
    vrm = normalise(vrm)
    if not is_valid_vrm(vrm):
        raise ValueError("not a valid UK registration")
    req = urllib.request.Request(
        "https://driver-vehicle-licensing.api.gov.uk/vehicle-enquiry/v1/vehicles",
        data=json.dumps({"registrationNumber": vrm}).encode(),
        headers={"x-api-key": api_key, "Content-Type": "application/json"}, method="POST")
    try:
        with opener(req, timeout=10) as r:
            d = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise LookupError("DVLA has no record of that registration") from e
        raise RuntimeError(f"DVLA error {e.code}") from e
    return {
        "reg": d.get("registrationNumber", vrm), "make": (d.get("make") or "").title() or None,
        "year": d.get("yearOfManufacture"), "colour": (d.get("colour") or "").title() or None,
        "fuel": d.get("fuelType"), "mot_status": d.get("motStatus"), "mot_expiry": d.get("motExpiryDate"),
        "tax_status": d.get("taxStatus"), "tax_due": d.get("taxDueDate"),
    }
