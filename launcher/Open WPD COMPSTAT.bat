@echo off
setlocal
rem Double-click this file. It finds the program from its own folder, %~dp0, and contains no drive letter.
rem The same file works at the top of the extracted zip, inside launcher\, and beside a program\ folder.
set "HERE=%~dp0"
set "START="
for %%S in ("%HERE%launcher\start.py" "%HERE%start.py" "%HERE%program\launcher\start.py") do if not defined START if exist "%%~S" set "START=%%~S"
if not defined START goto nostart

rem Python 3.12, 3.13, and 3.14 are supported. start.py names the version it found if it is another one.
set "PY="
py -3.14 -c "import sys" >nul 2>&1 && set "PY=py -3.14"
if not defined PY py -3.13 -c "import sys" >nul 2>&1 && set "PY=py -3.13"
if not defined PY py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
if not defined PY py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY goto nopython

%PY% "%START%" "%HERE%."
if errorlevel 1 goto fail
exit /b 0

:nostart
echo The WPD COMPSTAT program files were not found next to this file.
echo Extract the whole zip, then double-click Open WPD COMPSTAT.bat in the extracted folder.
pause
exit /b 1

:nopython
echo Python is not installed on this PC. WPD COMPSTAT needs Python 3.12, 3.13, or 3.14.
echo Install Python 3.14 from python.org, tick "Add python.exe to PATH", then open this file again.
pause
exit /b 1

:fail
echo.
echo The program did not start. Leave this window open and read the message above.
pause
exit /b 1
