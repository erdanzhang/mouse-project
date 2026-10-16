@echo off
rem Opens a command window where the mouse-rig command works. Examples:
rem   mouse-rig cameras        list the cameras and their serial numbers
rem   mouse-rig check          check the newest recording (frames per camera per clip)
rem   mouse-rig report         show what this computer can do
cd /d "%~dp0rig"
if not exist ".venv\Scripts\activate.bat" goto notinstalled
cmd /k "call .venv\Scripts\activate.bat && echo mouse-rig is ready. Try: mouse-rig cameras   or   mouse-rig check"
exit /b 0

:notinstalled
echo [ERROR] Not installed yet. Double-click install_windows.bat first.
pause
exit /b 1
