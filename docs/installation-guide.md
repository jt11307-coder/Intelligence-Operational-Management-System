# Installation instructions

## Quick start from the GitHub zip

1. Download https://github.com/jt11307-coder/Intelligence-Operational-Management-System/archive/refs/heads/wpd-compstat.zip
2. Delete any older extracted copy of that zip. Do not delete `E:\WPD COMPSTAT`, which holds the data.
3. Right-click the zip, choose Extract All, and extract it to `E:\`.
4. Open the extracted folder and double-click `Open WPD COMPSTAT.bat` at its top level.

The first start needs Python 3.12 from python.org and an internet connection. It creates the program environment in `.venv` inside the extracted folder and takes several minutes. Later starts open directly.

The opener finds the program from its own location, so the extracted folder names and the drive letter do not matter. The database, reports, and backups are kept in `WPD COMPSTAT` at the top of the same drive, for example `E:\WPD COMPSTAT`, outside the extracted folder. Deleting the extracted folder for an update keeps the data. If the top of the drive cannot be written, the data folder is created beside the extracted folder and the opener prints its location.

The same opener also works from inside `launcher\`, from `E:\WPD COMPSTAT\`, and in the drive layout below. A `launcher\program\.venv` folder left by an earlier opener is not used and can be deleted.

## Drive layout

The program lives on the thumb drive, in a folder named `WPD COMPSTAT`. It does not get installed onto the Windows Desktop. A desktop shortcut is optional and only starts the copy that stays on the drive.

On this laptop the Lexar drive is `E:`. The folder belongs at `E:\WPD COMPSTAT`. If Windows assigns a different letter later, open `Open WPD COMPSTAT.bat` from the folder on the drive. That file uses its own location and does not contain a drive letter.

## Folder layout

The portable copy prepared on this machine is `/agent/WPD COMPSTAT`. Copy that entire folder to the Lexar drive. Do not copy it to the Desktop.

```text
WPD COMPSTAT/
  Open WPD COMPSTAT.bat double-click this on the thumb drive
  program/              Python source used until a Windows executable is built
  Application/          program files, or the source entry until Windows packaging
  Launcher/             bootstrap copied onto the drive
  Database/             encrypted database and key store
  Source PDFs/          sealed call-log PDFs
  Imports/              traffic workbooks copied in by an import
  Reports/              PDF, workbook, and CSV output
  Presentations/        PowerPoint output
  Maps/                 offline map artifacts
  Backups/              encrypted database backups
  Audit/                reserved for audit exports
  Configuration/        local settings that are not secrets
  Documentation/        copies of these manuals
  Working/              decrypted database while the program is open
  Logs/                 local logs
  WPD-COMPSTAT-INSTALL.json
```

`Working` is deleted when the session closes. Do not copy `Working` onto another computer as a backup. Use an encrypted backup from `Backups`.

## Create an installation from this source tree

On a machine with Python 3.11 or newer:

The package is imported from `src/`. Set `PYTHONPATH=src` in this tree. It is not installed into the virtual environment by `requirements.txt`.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
PYTHONPATH=src .venv/bin/python - <<'PY'
from pathlib import Path
from wpd_compstat.install import initialize_installation
initialize_installation(
    Path("/media/COMPSTAT/WPD COMPSTAT"),
    docs_dir=Path("docs"),
    launcher_dir=Path("launcher"),
)
PY
```

Replace `/media/COMPSTAT` with the external drive's mount point. The folder name `WPD COMPSTAT` is required.

That command writes `Application/ENTRY`, a manifest whose `packaging_status` is `source`, and the folder tree. It does not create a user and it does not load incidents.

Start the program:

```bash
PYTHONPATH=src WPD_COMPSTAT_ALLOW_SOURCE=1 .venv/bin/python -m wpd_compstat --root "/media/COMPSTAT/WPD COMPSTAT"
```

`WPD_COMPSTAT_ALLOW_SOURCE=1` is only for this source entry. A verified Windows build does not need it. The launcher refuses a `source` manifest unless that switch is set, so a desktop shortcut cannot silently start an unpackaged tree.

Create the administrator in the first dialog. Store the optional recovery passphrase outside the drive if the department requires recovery.

## Windows packaging

`packaging/build_windows.ps1` is the build. Run it on Windows from a copy of this tree:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

It creates a virtual environment, installs `requirements.txt` and PyInstaller, and builds:

- `build\dist\WPDCompstat.exe`
- `build\dist\WPDCompstatLauncher.exe`

This Linux workspace cannot produce those files. `packaging/check_windows_build.py` reports that and exits 2. Do not copy a Linux binary into `Application` and describe it as the Windows program.

After a real Windows build:

1. Copy `WPDCompstat.exe` to `WPD COMPSTAT\Application\`.
2. Set the manifest `application_relative_path` to that file, `packaging_status` to `windows_executable`, and `application_sha256` to the file's SHA-256.
3. Copy `WPDCompstatLauncher.exe` with `launcher\install_shortcut.py`. That script places the launcher in `%LOCALAPPDATA%\WPD-COMPSTAT\` and writes `WPD COMPSTAT.bat` and `WPD COMPSTAT.vbs` on the desktop. Those files expand `%LOCALAPPDATA%`. They do not contain a drive letter.
4. If the shortcut is lost, run `launcher\repair_shortcut.py` while the drive is connected. If the drive is absent, the repair stops and does not write a letter such as `E:\`.

## Moving the drive

The manifest travels with the folder. A letter change from E: to G: still resolves because the scan looks for `WPD COMPSTAT\WPD-COMPSTAT-INSTALL.json` on each connected drive. Two connected installations print both installation ids and wait for a choice. A missing drive prints that the drive is not connected and returns code 2.

If `Application/ENTRY` or the Windows executable is edited, the hash check fails and the launcher does not start that copy.

## What stays on the PC

Only the small launcher under `%LOCALAPPDATA%\WPD-COMPSTAT`. The database, PDFs, reports, and keys stay on the external drive. Unplugging the drive removes the data from the computer. The local launcher cannot open a database by itself.

## Offline rule

Install Python packages while the build machine is allowed to reach a package index. After installation, the running program does not need a network. Do not add API keys. The program has no cloud credential.
