#!/bin/bash
cd "$(dirname "$0")/rig" || exit 1
if [ ! -x .venv/bin/mouse-rig ]; then
  echo "[ERROR] Not installed yet. Double-click install_mac.command first."
  read -r -p "Press Enter to close"; exit 1
fi
echo "Keep this window open while you record. Press Ctrl+C to stop the recorder."
echo
exec .venv/bin/mouse-rig serve "$@"
