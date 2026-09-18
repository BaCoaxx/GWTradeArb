# -*- mode: python ; coding: utf-8 -*-
"""Native onedir spec for Linux x64 and Windows x64.

Run this spec on the OS you are packaging. Do not cross-compile or relabel
a Linux build as Windows (or the reverse).
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

SPECDIR = Path(SPECPATH).resolve()
ROOT = SPECDIR.parent

hiddenimports = collect_submodules("gwtradearb")
hiddenimports += [
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "shiboken6",
]

a = Analysis(
    [str(SPECDIR / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(SPECDIR / "pyi_rth_gwtradearb.py")],
    excludes=["pytest", "tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GWTradeArb",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="GWTradeArb",
)
