#!/bin/bash
# mouse-project install on macOS (also works on Linux: bash install_mac.command)
cd "$(dirname "$0")/rig" || exit 1
echo "=== mouse-project: install on macOS ==="
PY=""
for c in python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[ERROR] Python 3 was not found. Install it from https://www.python.org/downloads/macos/"
  read -r -p "Press Enter to close"; exit 1
fi
if ! "$PY" -c 'import sys; assert sys.version_info >= (3, 9)'; then
  echo "[ERROR] $PY is older than 3.9. Install Python 3.11 or 3.12."
  read -r -p "Press Enter to close"; exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "Creating the Python environment in rig/.venv ..."
  "$PY" -m venv .venv || { echo "[ERROR] could not create rig/.venv"; read -r -p "Press Enter"; exit 1; }
fi
echo "Installing packages - this takes 1 to 3 minutes ..."
.venv/bin/python -m pip install --upgrade pip
if ! .venv/bin/python -m pip install -e ".[dev]"; then
  echo "[ERROR] Package install failed. Check the internet connection and run this file again."
  read -r -p "Press Enter to close"; exit 1
fi
if [ ! -f config/recorder.local.yaml ]; then
  cp config/recorder.yaml config/recorder.local.yaml
  echo "Created rig/config/recorder.local.yaml - edit this file for this computer."
fi
echo; echo "=== Check ==="
.venv/bin/mouse-rig report
echo
echo "Install finished."
echo "Next: double-click start_demo_mac.command to test without cameras,"
echo "      or start_recorder_mac.command to use the real cameras."
read -r -p "Press Enter to close"
