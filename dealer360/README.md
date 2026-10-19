# Dealer360

Mobile app + server for dealers: capture a car with a phone, GoPro, Insta360, DJI or any camera that can export a photo/video; AI flags damage; every defect is logged with panel, position, size, a cropped photo and an overview. Outputs: drag-to-spin walkaround viewer (plus true 360 panoramas) and an HTML condition report.

## Run

Backend (Python 3.10+):
    cd backend && pip install -r requirements.txt
    uvicorn app.main:app --host 0.0.0.0 --port 8000
    python -m pytest -q

Mobile (Expo SDK 58):
    cd mobile && npm install && npx expo start
Camera/WebView/secure-store work in Expo Go for most features; use a development build (`npx expo run:android|ios`) for production. In the app: Settings → server address (e.g. http://192.168.1.10:8000) → Test connection.

Env vars: DEALER360_DATA (storage dir), DEALER360_API_KEY (require X-API-Key), DEALER360_DETECTOR = auto|classical|yolo|vlm, DEALER360_YOLO_WEIGHTS, DEALER360_VLM_MODEL, DEALER360_VLM_TILES (e.g. 2x2), ANTHROPIC_API_KEY (vlm mode).

## Camera support

| Camera | How |
|---|---|
| Phone | Guided 8-view capture with framing box |
| GoPro (HERO9+) | Control over its Wi-Fi, or import files. Endpoints in `mobile/src/lib/gopro.ts` are UNVERIFIED - check against the Open GoPro spec |
| Insta360 / DJI / any | Export stitched JPG/MP4 from the camera's app, then Import. Insta360's SDK is gated, so there is no live control |
| USB 360 / UVC | Not supported live (needs a native module). Import files instead |
Multiple cameras: import as many files as you like per vehicle; defects seen in several views are merged.

## Detection

- Spec in `backend/app/detection/prompts/inspection_spec.md` (Dent/Chip/Scratch/Paint Damage, JSON output). `GET /vehicles/{id}/defects/export` returns that schema.
- `vlm` mode sends tiles to a multimodal model with the spec. Images (plates, customers' cars) leave your server.
- `yolo` mode: ultralytics weights you train (e.g. on CarDD).
- `classical` is a heuristic PLACEHOLDER to prove the pipeline. Expect misses and false alarms; do not rely on it.
- Video clips: frames are sharpness-filtered and tracked; marks that stay fixed in the camera frame (glare) are rejected.

## Honest limits

- 0.1 mm scratches/chips are not detectable with these cameras at normal distance; every defect shows the smallest size detectable for its shot.
- 90%+ accuracy is not demonstrated; it needs a trained model and your own labelled test set.
- Panel/zone mapping uses a generic hatchback template; approximate in 3/4 views. Size mm needs a known car size or `mm_per_px`.
- Phone on a GoPro's Wi-Fi can't reach the server; captures queue and upload later.
- Production: HTTPS, per-dealer auth (only a single shared API key exists), image retention policy.

## Number plates (VRM)
New vehicle → Scan number plate (server-side Tesseract OCR, UK formats only; always confirm) → Look up (DVLA Vehicle Enquiry Service: make, year, colour, fuel, MOT, tax; not model or size). Needs `tesseract` installed on the server (`apt install tesseract-ocr`) and `DVLA_API_KEY` set.
