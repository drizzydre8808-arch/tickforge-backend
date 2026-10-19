# Dealer360
Car-dealer damage inspection. backend/ = FastAPI + OpenCV (tests: `cd backend && python -m pytest -q`). mobile/ = Expo SDK 58 / Expo Router (checks: `npx tsc --noEmit`, `npx expo lint`). See README.md.
Goal now: build an Android APK (`cd mobile && npx eas-cli@latest build -p android --profile preview`) and get the backend running where the tablet can reach it. Needs `tesseract-ocr` and DVLA_API_KEY on the server. GoPro endpoints in mobile/src/lib/gopro.ts are unverified.
