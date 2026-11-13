"""Desktop shortcut files that point at the local launcher, not at a drive letter."""

from __future__ import annotations

import os
from pathlib import Path

LOCAL_LAUNCHER_NAME = "WPDCompstatLauncher.exe"
SHORTCUT_NAME = "WPD COMPSTAT.bat"
VBS_NAME = "WPD COMPSTAT.vbs"


def bat_contents() -> str:
    return (
        "@echo off\r\n"
        'set "LAUNCHER=%LOCALAPPDATA%\\WPD-COMPSTAT\\WPDCompstatLauncher.exe"\r\n'
        'if not exist "%LAUNCHER%" (\r\n'
        "  echo The local WPD COMPSTAT launcher is not installed.\r\n"
        "  echo Connect the installation drive and run the shortcut installer from the packaged application.\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        '"%LAUNCHER%"\r\n'
    )


def vbs_contents() -> str:
    return (
        'Set shell = CreateObject("Wscript.Shell")\r\n'
        'launcher = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\\WPD-COMPSTAT\\WPDCompstatLauncher.exe"\r\n'
        'If shell.FileExists(launcher) Then\r\n'
        "  shell.Run Chr(34) & launcher & Chr(34), 1, False\r\n"
        "Else\r\n"
        '  MsgBox "The WPD COMPSTAT drive launcher is not installed on this computer.", 48, "WPD COMPSTAT"\r\n'
        "End If\r\n"
    )


def write_desktop_shortcuts(desktop_dir: Path) -> list[Path]:
    desktop_dir.mkdir(parents=True, exist_ok=True)
    bat = desktop_dir / SHORTCUT_NAME
    vbs = desktop_dir / VBS_NAME
    bat.write_text(bat_contents(), encoding="utf-8")
    vbs.write_text(vbs_contents(), encoding="utf-8")
    return [bat, vbs]


def local_launcher_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if root:
        return Path(root) / "WPD-COMPSTAT"
    return Path.home() / ".local" / "share" / "WPD-COMPSTAT"


def shortcut_text_has_drive_letter(text: str) -> bool:
    import re

    return re.search(r"[A-Za-z]:\\", text) is not None
