@echo off
setlocal
cd /d "%~dp0"
title Build MxSim Racing OBS Overlay v2.0.13

echo.
echo ===============================================
echo  MxSim Racing OBS Overlay v2.0.13 - EXE Builder
echo ===============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    set PY=py
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set PY=python
    ) else (
        echo Python was not found.
        echo Install Python from https://www.python.org/downloads/windows/
        echo IMPORTANT: tick "Add python.exe to PATH" during install.
        pause
        exit /b 1
    )
)

echo Using Python launcher: %PY%
echo.
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt

echo.
echo Fetching site favicon for EXE / installer icon...
if not exist "build_cache" mkdir build_cache
%PY% scripts\fetch_branding_for_build.py
if errorlevel 1 (
    echo WARNING: Could not create build_cache\app.ico - PyInstaller may use default icon.
)

echo.
echo Cleaning old build files...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul

echo.
echo Building Windows EXE (PyInstaller spec)...
%PY% -m PyInstaller --noconfirm packaging\MxSimRacingOBSOverlay.spec

if not exist "dist\MxSimRacingOBSOverlay.exe" (
    echo.
    echo Build failed. Check the error above.
    pause
    exit /b 1
)

echo.
echo ===============================================
echo Portable EXE created:
echo dist\MxSimRacingOBSOverlay.exe
echo ===============================================
echo.
pause
