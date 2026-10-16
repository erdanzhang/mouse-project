@echo off
title mouse-project recorder
cd /d "%~dp0rig"
if not exist ".venv\Scripts\mouse-rig.exe" goto notinstalled
echo Keep this window open while you record. Close it or press Ctrl+C to stop the recorder.
echo.
".venv\Scripts\mouse-rig.exe" serve %*
pause
exit /b 0

:notinstalled
echo [ERROR] Not installed yet. Double-click install_windows.bat first.
pause
exit /b 1
