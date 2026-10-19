# First deployment

## 1. Backend (any VPS with Docker)
    cp .env.example .env     # set DEALER360_API_KEY and DVLA_API_KEY
    docker compose up -d --build
    curl http://SERVER_IP:8000/docs
Data (photos, DB) persists in the `dealer360-data` volume. Put HTTPS in front (Caddy/nginx/Cloudflare Tunnel) for anything beyond a trial.
The Docker image includes tesseract, so plate OCR works (test_plate fails locally without it).

## 2. Android APK
    cd mobile && npm install
    npx eas-cli@latest login
    npx eas-cli@latest build -p android --profile preview
Download the APK from the build URL and install on the tablet.
Before a store release change `com.example.dealer360` in mobile/app.json to your own package id.

## 3. Connect
In the app: Settings -> server address (`http://SERVER_IP:8000` or your HTTPS URL), API key, Test connection.

## Known limits
Detector `classical` is a placeholder; train YOLO weights or use `vlm` for real detection. GoPro endpoints unverified. Single shared API key.

## Zero-setup install (recommended)
The APK can ship pre-configured so users just install and open it:
1. Deploy the backend once (Render: New -> Blueprint -> this repo's `dealer360/render.yaml`, or Docker above). Note its URL and API key.
2. Put them in `mobile/eas.json` -> `build.preview.env` (`EXPO_PUBLIC_API_URL`, `EXPO_PUBLIC_API_KEY`). The key is readable inside the APK, so only distribute it to your own staff.
3. Add an `EXPO_TOKEN` repo secret, then run the "Dealer360 APK" GitHub Action; download the APK from the EAS build link.
Settings in the app still override the baked-in values.
