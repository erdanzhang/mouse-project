#!/bin/bash
# Opens a shell where the mouse-rig command works (mouse-rig cameras / check / report).
cd "$(dirname "$0")/rig" || exit 1
if [ ! -x .venv/bin/mouse-rig ]; then
  echo "[ERROR] Not installed yet. Double-click install_mac.command first."
  read -r -p "Press Enter to close"; exit 1
fi
export VIRTUAL_ENV="$PWD/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"
echo "mouse-rig is ready. Try: mouse-rig cameras   or   mouse-rig check"
exec "${SHELL:-/bin/bash}" -i
