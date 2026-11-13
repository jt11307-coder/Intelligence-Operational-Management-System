@echo off
setlocal
rem This file lives on the thumb drive. %~dp0 is that drive, whatever letter Windows assigned.
cd /d "%~dp0"
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "APP=%ROOT%\program"
set "PYTHONPATH=%APP%\src"
set "PYEXE="

if exist "%APP%\.venv\Scripts\python.exe" set "PYEXE=%APP%\.venv\Scripts\python.exe"
if defined PYEXE goto run

where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  where python >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Python 3.12 is not installed on this PC.
  echo Install Python 3.12 from python.org, then open this file again from the thumb drive.
  echo Do not copy the program onto the Desktop.
  pause
  exit /b 1
)

echo Creating the program environment on this drive...
%PY% -m venv "%APP%\.venv"
if errorlevel 1 goto fail
set "PYEXE=%APP%\.venv\Scripts\python.exe"
if exist "%APP%\wheels\" (
  "%PYEXE%" -m pip install --no-index --find-links "%APP%\wheels" -r "%APP%\requirements.txt"
) else (
  "%PYEXE%" -m pip install -r "%APP%\requirements.txt"
)
if errorlevel 1 goto fail

:run
"%PYEXE%" -m wpd_compstat --root "%ROOT%"
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
echo The program did not start. Leave this window open and read the message above.
pause
exit /b 1
