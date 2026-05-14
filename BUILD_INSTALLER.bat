@echo off
setlocal
cd /d "%~dp0"
title Build Installer - MxSim Racing OBS Overlay v2.0.11

echo.
echo ===============================================
echo  MxSim Racing OBS Overlay v2.0.11 - Installer Builder
echo ===============================================
echo.

if not exist "dist\MxSimRacingOBSOverlay.exe" (
    echo Portable EXE not found. Building it first...
    call BUILD_PORTABLE_EXE.bat
)

if not exist "dist\MxSimRacingOBSOverlay.exe" (
    echo EXE still not found. Cannot build installer.
    pause
    exit /b 1
)

where py >nul 2>nul
if %errorlevel%==0 (set PY=py) else (set PY=python)
if not exist "build_cache\app.ico" (
    echo Generating build_cache\app.ico for Inno Setup...
    if not exist "build_cache" mkdir build_cache
    %PY% scripts\fetch_branding_for_build.py
)

set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if "%ISCC%"=="" (
    echo Inno Setup 6 was not found.
    echo.
    echo Install Inno Setup 6 from:
    echo https://jrsoftware.org/isdl.php
    echo.
    echo After installing it, run BUILD_INSTALLER.bat again.
    echo The portable EXE is already available in dist\.
    pause
    exit /b 1
)

echo Using Inno Setup:
echo %ISCC%
echo.
"%ISCC%" "installer\MxSimRacingOBSOverlay_v2_0_11.iss"
if errorlevel 1 (
    echo.
    echo Installer build failed. Check the messages above.
    pause
    exit /b 1
)

if exist "release\MxSimRacingOBSOverlay-v2.0.11-Setup.exe" (
    echo.
    echo ===============================================
    echo Installer created:
    echo release\MxSimRacingOBSOverlay-v2.0.11-Setup.exe
    echo ===============================================
) else (
    echo.
    echo Installer build may have failed. Check the messages above.
)

echo.
pause
