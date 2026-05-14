# MxSim Racing OBS Overlay

Windows app that serves a **local OBS Browser Source** overlay from [MxSim Racing](https://mxsimracing.com/) league ranking data.

The desktop UI **loads the favicon and header image from [mxsimracing.com](https://mxsimracing.com/)** (homepage `og:image` + favicon link) into a per-user cache under `%APPDATA%\MxSim Racing OBS Overlay\branding_cache\`, refreshed about every **24 hours**. An internet connection is needed the first time (or after cache expiry).

**Current version:** 2.0.11 (see [`docs/CHANGELOG.txt`](docs/CHANGELOG.txt)).

## Repository layout

| Path | Purpose |
|------|---------|
| `src/` | Application source (`MxSimRacingOBSOverlay.py`) |
| `scripts/` | Build helpers (`fetch_branding_for_build.py`) |
| `docs/` | Shipped/readme text (EN/NL), changelog, release notes |
| `installer/` | Inno Setup script |
| `packaging/` | PyInstaller `.spec` |
| `build_cache/`, `build/`, `dist/`, `release/` | Build outputs (gitignored except what you generate locally) |

## Download (ready-to-run)

Pre-built **`.exe`** and **installer** are published on GitHub Releases (not in git history).

1. Open **Releases**: [latest](https://github.com/HeimelijkenB/mxsim-racing-obs-overlay/releases/latest).
2. Download **`MxSimRacingOBSOverlay.exe`** and/or **`MxSimRacingOBSOverlay-v2.0.11-Setup.exe`** (or the latest version's assets).

No Python is required for end users when using the Release binaries.

## Quick start (after install or portable exe)

1. Start `MxSimRacingOBSOverlay.exe`.
2. Enter a rider name (or part of it).
3. Keep the league URL as `https://mxsimracing.com/league` unless the site changes.
4. Click **Search / scrape**.
5. In OBS, add a **Browser Source** with URL `http://localhost:3000` (or the port you set).
6. Recommended size: **320 × 150**, FPS **10–15**.

More detail: [`docs/README_EN.txt`](docs/README_EN.txt) (English) and [`docs/README_NL.txt`](docs/README_NL.txt) (Dutch).

## Run from source (developers)

1. Install [Python for Windows](https://www.python.org/downloads/windows/) and tick **Add python.exe to PATH**.
2. From the repository root:

   ```bat
   RUN_FROM_SOURCE.bat
   ```

   Or manually: `pip install -r requirements.txt` then `python src\MxSimRacingOBSOverlay.py`.

## Build portable exe and installer

1. **Portable EXE:** run **`BUILD_PORTABLE_EXE.bat`**. It installs dependencies, runs **`scripts\fetch_branding_for_build.py`** to create **`build_cache\app.ico`**, then runs **`pyinstaller packaging\MxSimRacingOBSOverlay.spec`**.
2. **Installer:** install [Inno Setup 6](https://jrsoftware.org/isdl.php), then run **`BUILD_INSTALLER.bat`**.  
   Output: `release\MxSimRacingOBSOverlay-v2.0.11-Setup.exe` (version may change in future tags).  
   The installer uses **`build_cache\app.ico`** for the setup icon (Inno default wizard side images).

See [`docs/PUBLIC_RELEASE_INSTRUCTIONS.txt`](docs/PUBLIC_RELEASE_INSTRUCTIONS.txt) for a short release checklist.

## Contributing

Issues and pull requests are welcome. Keep changes focused; match existing style. By contributing, you agree your contributions are licensed under the same terms as this project (**MIT** — see `LICENSE`).

## License

- **Open source:** `LICENSE` (MIT).
- **Installer / package notice:** `LICENSE.txt` (short usage notice bundled with the app).

## Repository

Source: [github.com/HeimelijkenB/mxsim-racing-obs-overlay](https://github.com/HeimelijkenB/mxsim-racing-obs-overlay).

## Releases (maintainers)

Create a **Release** tagged `v2.0.11` (or the current version) and attach the built **`dist\MxSimRacingOBSOverlay.exe`** and **`release\MxSimRacingOBSOverlay-v2.0.11-Setup.exe`** after building locally.
