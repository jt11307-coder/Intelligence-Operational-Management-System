# -*- mode: python ; coding: utf-8 -*-
# Executed by PyInstaller on Windows. Analysis, PYZ, and EXE are provided by PyInstaller.
# No drive letter and no encryption key are embedded.

from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("wpd_compstat")

a = Analysis(
    ["../src/wpd_compstat/__main__.py"],
    pathex=["../src"],
    binaries=[],
    datas=[
        ("../src/wpd_compstat/db/001_initial.sql", "wpd_compstat/db"),
        ("../src/wpd_compstat/db/002_report_runs.sql", "wpd_compstat/db"),
        ("../docs", "docs"),
    ],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WPDCompstat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
