# -*- mode: python ; coding: utf-8 -*-
import os

from PyInstaller.utils.hooks import collect_all

spec_dir = os.path.dirname(os.path.abspath(SPEC))
repo_root = os.path.dirname(spec_dir)

datas = []
binaries = []
hiddenimports = [
    "selenium.webdriver.chrome.webdriver",
    "selenium.webdriver.edge.webdriver",
    "selenium.webdriver.common.selenium_manager",
    "bs4",
    "PIL.Image",
    "PIL.ImageTk",
    "PIL._imagingtk",
    "PIL._webp",
]
tmp_ret = collect_all("selenium")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]
try:
    tmp_pil = collect_all("PIL")
    datas += tmp_pil[0]
    binaries += tmp_pil[1]
    hiddenimports += tmp_pil[2]
except Exception:
    pass

script_path = os.path.join(repo_root, "src", "MxSimRacingOBSOverlay.py")
ico_path = os.path.join(repo_root, "build_cache", "app.ico")
icon_arg = [ico_path] if os.path.isfile(ico_path) else []

a = Analysis(
    [script_path],
    pathex=[repo_root, os.path.join(repo_root, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

_exe_extra = {}
if icon_arg:
    _exe_extra["icon"] = icon_arg

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MxSimRacingOBSOverlay",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    **_exe_extra,
)
