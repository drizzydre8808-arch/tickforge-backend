"""Runtime configuration. Everything can be overridden with environment variables."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Where the SQLite DB and all media (originals, crops, overviews) live.
DATA_DIR = Path(os.environ.get("DEALER360_DATA", BASE_DIR / "data"))

# Optional shared API key. If set, every request needs it as an `X-API-Key`
# header or a `?key=` query parameter (the latter is for WebViews / <img> tags).
# This is a stop-gap: replace with per-dealer accounts before real use.
API_KEY = os.environ.get("DEALER360_API_KEY") or None

# Path to trained YOLO weights (ultralytics). If unset, the classical
# heuristic detector is used, which is a low-accuracy fallback only.
YOLO_WEIGHTS = os.environ.get("DEALER360_YOLO_WEIGHTS") or None
YOLO_CONF = float(os.environ.get("DEALER360_YOLO_CONF", "0.30"))

# Where the vehicle sits inside a guided-capture photo, as normalised
# (x0, y0, x1, y1). The mobile app draws this outline on the camera preview
# and asks the dealer to fit the car inside it. Zone and size estimates
# assume the car fills this box.
DEFAULT_FRAME_BOX = (0.04, 0.22, 0.96, 0.88)

# Default vehicle size used for mm estimates when the vehicle record has none.
DEFAULT_LENGTH_MM = 4400
DEFAULT_WIDTH_MM = 1800

# DVLA Vehicle Enquiry Service key (free from the DVLA developer portal). Optional.
DVLA_API_KEY = os.environ.get("DVLA_API_KEY") or None
