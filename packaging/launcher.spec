# -*- mode: python ; coding: utf-8 -*-
# Small local launcher. It does not contain the database or a key.

from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("wpd_compstat.launcher") + [
    "wpd_compstat.constants",
    "wpd_compstat.launcher.scan",
    "wpd_compstat.launcher.cli",
]

a = Analysis(
    ["../launcher/bootstrap.py"],
    pathex=["../src"],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "PySide6", "matplotlib", "pandas", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WPDCompstatLauncher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
