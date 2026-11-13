# Build the Windows executables. Run on Windows from the repository root.
# This script does not run on the Linux environment used for development here.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt pyinstaller
.\.venv\Scripts\pyinstaller --noconfirm --distpath build\dist --workpath build\work packaging\wpd_compstat.spec
.\.venv\Scripts\pyinstaller --noconfirm --distpath build\dist --workpath build\work packaging\launcher.spec
Write-Host "Built build\dist\WPDCompstat.exe and build\dist\WPDCompstatLauncher.exe"
Write-Host "Copy WPDCompstat.exe to the installation Application folder and update the manifest hash."
Write-Host "Copy WPDCompstatLauncher.exe to %LOCALAPPDATA%\WPD-COMPSTAT\ with launcher\install_shortcut.py."
