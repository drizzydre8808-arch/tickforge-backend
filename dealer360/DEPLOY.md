# Dealer360 — standalone Android app

The app does everything on the tablet: vehicle records, photos, plate OCR (on-device), report + spin viewer, and PDF sharing. No server is needed.
Two things use the internet: **damage detection** (each photo is sent to Anthropic's Claude vision model) and the optional **DVLA** plate lookup.

## Build the APK (no local tooling)
1. Create a free account at expo.dev, then create an access token (Account settings -> Access tokens).
2. GitHub repo -> Settings -> Secrets -> Actions -> add `EXPO_TOKEN`.
3. Optional: put your keys in `mobile/eas.json` (`build.preview.env`) to pre-load them in the APK. They are readable inside the APK, so only do this for your own staff devices. Otherwise each device enters them once in Settings.
4. Actions tab -> "Dealer360 APK" -> Run workflow. When it finishes, open the EAS build link on the tablet and install the APK (allow "install unknown apps").

Or locally: `cd mobile && npm install && npx eas-cli@latest login && npx eas-cli@latest build -p android --profile preview`.

## First run
Settings -> paste the Anthropic API key (console.anthropic.com) -> Test AI connection -> Save. Add the DVLA key if you want plate lookup.

## Limits
- Detection needs internet. Captures taken offline (or on a GoPro's Wi-Fi) wait in the queue and are analysed when you retry.
- Stitched 360 photos aren't supported; use flat photos or video clips (4 frames sampled; marks must appear in 2+ frames to count, which filters glare).
- Boxes from the AI model are approximate; sizes are estimates. Always confirm findings.
- Data lives only on the device (no backup/sync). Uninstalling deletes it.
- GoPro endpoints are unverified. Package id is still `com.example.dealer360`: change it before a store release.
- Not run on a real device yet: test capture, plate scan, report and viewer on the tablet before relying on it.

`backend/` is the earlier server version and is no longer used by the app.
