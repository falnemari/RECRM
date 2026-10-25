#!/usr/bin/env bash
# Wrapper to run python migration with .venv
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/../.venv/bin/python" "$SCRIPT_DIR/migrate_agent_compensation_runner.py" "$@"

