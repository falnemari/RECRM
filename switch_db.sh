#!/usr/bin/env bash
# RECRM Database Switcher Shortcut
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
    echo "[!] Python virtualenv not found at $PYTHON_BIN. Please run: sudo bash setup_new_laptop.sh"
    exit 1
fi
"$PYTHON_BIN" "$SCRIPT_DIR/scripts/switch_db.py" "$@"

