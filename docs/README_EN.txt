MxSim Racing OBS Overlay v2.0.12

A Windows app that creates a local OBS Browser Source overlay for the MxSim Racing league ranking page.

Quick start
1. Start MxSimRacingOBSOverlay.exe.
2. Enter a rider name or partial rider name.
3. Keep the scrape URL as https://mxsimracing.com/league unless the league page changes.
4. Click Search / scrape.
5. In OBS, add a Browser Source with URL: http://localhost:3000
6. Set the Browser Source size to 320 x 150 and FPS to 10 or 15.

Default settings
- Scrape interval: 3 minutes
- OBS refresh: every 5 seconds
- Local port: 3000
- Low-lag mode: the browser opens only during scraping and closes automatically.
- Window branding (favicon + header image) is downloaded from mxsimracing.com when online; cached about one day.

Troubleshooting
- If port 3000 is already in use, close older running copies of the app.
- If the rider is not found, try a shorter part of the rider name.
- The app automatically loads more ranking rows while searching.
- The overlay data is saved locally and served to OBS from a local JSON file for reliability.

Build
Run BUILD_PORTABLE_EXE.bat first. Then run BUILD_INSTALLER.bat to create the installer in the release folder.
