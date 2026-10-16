@echo off
setlocal
title mouse-project install
cd /d "%~dp0rig"
echo === mouse-project: install on Windows ===
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY goto nopython

%PY% -c "import sys; assert sys.version_info >= (3, 9) and sys.maxsize > 2**32" 2>nul
if errorlevel 1 goto badpython

if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python environment in rig\.venv ...
  %PY% -m venv .venv
  if errorlevel 1 goto venvfail
)

echo Installing packages - this takes 1 to 3 minutes ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -e ".[dev]"
if errorlevel 1 goto pipfail

if not exist "config\recorder.local.yaml" (
  copy "config\recorder.yaml" "config\recorder.local.yaml" >nul
  echo Created rig\config\recorder.local.yaml - edit this file for this computer.
)

echo.
echo === Check ===
".venv\Scripts\mouse-rig.exe" report
echo.
echo Install finished.
echo Next: double-click start_demo_windows.bat to test without cameras,
echo       or start_recorder_windows.bat to use the real cameras.
pause
exit /b 0

:nopython
echo [ERROR] Python was not found.
echo Install Python 3.11 or 3.12, 64-bit, from https://www.python.org/downloads/windows/
echo and tick "Add python.exe to PATH" on the first installer screen. Then run this file again.
pause
exit /b 1

:badpython
echo [ERROR] This Python is too old or is 32-bit. Install Python 3.11 or 3.12, 64-bit.
%PY% --version
pause
exit /b 1

:venvfail
echo [ERROR] Could not create rig\.venv. Delete the folder rig\.venv and run this file again.
pause
exit /b 1

:pipfail
echo [ERROR] Package install failed. Check the internet connection and run this file again.
pause
exit /b 1
