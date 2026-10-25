#!/usr/bin/env bash
# ==============================================================================
# RE CRM - Fast & Reliable Application Launcher
# مكتب معاذ خضر النمري للخدمات العقارية
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PORT=8000
SERVER_URL="http://localhost:${PORT}"
DASHBOARD_URL="${SERVER_URL}/ui/index.html"
LOG_FILE="${SCRIPT_DIR}/server.log"
PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"

# 1. Locate and validate Python Virtual Environment
if [ ! -x "$PYTHON_BIN" ]; then
    echo "=========================================================="
    echo "  [✗] Error: Python environment not found or broken at:"
    echo "      $PYTHON_BIN"
    echo "=========================================================="
    echo "  It looks like this project was transferred to a new laptop."
    echo "  Please run the one-time setup script to configure your environment:"
    echo ""
    echo "      sudo bash setup_new_laptop.sh"
    echo ""
    echo "  This will install prerequisites, configure PostgreSQL,"
    echo "  and set up a fresh Python virtual environment."
    echo "=========================================================="
    exit 1
fi

# Function to check if server is currently running
is_server_running() {
    curl -s --max-time 1 "${SERVER_URL}/health" >/dev/null 2>&1
}

# Function to stop the server
stop_server() {
    echo "Stopping RECRM server on port ${PORT}..."
    PIDS=$(pgrep -f "src/backend/run.py" || true)
    if [ -n "$PIDS" ]; then
        kill -15 $PIDS 2>/dev/null || true
        sleep 1
        kill -9 $PIDS 2>/dev/null || true
        echo "✓ Server stopped successfully."
    else
        if command -v fuser >/dev/null 2>&1; then
            fuser -k ${PORT}/tcp 2>/dev/null || true
        fi
        echo "✓ No running RECRM server found on port ${PORT}."
    fi
}

# Function to check status
check_status() {
    echo "=========================================================="
    echo "  RECRM System Status Check"
    echo "=========================================================="
    if systemctl is-active --quiet postgresql@18-main 2>/dev/null || systemctl is-active --quiet postgresql 2>/dev/null; then
        echo "  [✓] PostgreSQL Database : RUNNING (port 5432)"
    else
        echo "  [✗] PostgreSQL Database : NOT RUNNING (run: sudo systemctl start postgresql)"
    fi

    if [ -x "$PYTHON_BIN" ]; then
        PY_VER=$("$PYTHON_BIN" --version 2>&1 || echo "active")
        echo "  [✓] Python Environment   : READY ($PY_VER)"
    else
        echo "  [✗] Python Environment   : NOT READY (run: sudo bash setup_new_laptop.sh)"
    fi

    if is_server_running; then
        echo "  [✓] RECRM FastAPI Server : RUNNING (${SERVER_URL})"
        echo "  [✓] Dashboard UI         : ${DASHBOARD_URL}"
    else
        echo "  [✗] RECRM FastAPI Server : STOPPED"
    fi
    echo "=========================================================="
}

# Parse Command Line Arguments
MODE="foreground"
OPEN_BROWSER=true

for arg in "$@"; do
    case "$arg" in
        --stop|-s)
            stop_server
            exit 0
            ;;
        --status)
            check_status
            exit 0
            ;;
        --restart|-r)
            stop_server
            sleep 1
            ;;
        --daemon|-d|--background|-b)
            MODE="daemon"
            ;;
        --no-open)
            OPEN_BROWSER=false
            ;;
        --open)
            OPEN_BROWSER=true
            ;;
        --help|-h)
            echo "Usage: ./start_server.sh [options]"
            echo "Options:"
            echo "  (no args)       Start server in foreground (default, opens browser)"
            echo "  --daemon, -d    Start server in background (daemon mode)"
            echo "  --stop, -s      Stop running server"
            echo "  --restart, -r   Restart server"
            echo "  --status        Check health of PostgreSQL & RECRM"
            echo "  --no-open       Do not open browser automatically"
            exit 0
            ;;
    esac
done

# 2. Check if already running
if is_server_running; then
    echo "=========================================================="
    echo "  RECRM server is ALREADY running at ${SERVER_URL}"
    echo "=========================================================="
    echo "  Opening Dashboard: ${DASHBOARD_URL}"
    echo "  (To restart instead, run: ./start_server.sh --restart)"
    echo "=========================================================="
    if [ "$OPEN_BROWSER" = true ] && command -v xdg-open >/dev/null 2>&1; then
        xdg-open "${DASHBOARD_URL}" >/dev/null 2>&1 &
    fi
    exit 0
fi

# 3. Check PostgreSQL
if ! systemctl is-active --quiet postgresql@18-main 2>/dev/null && ! systemctl is-active --quiet postgresql 2>/dev/null; then
    echo "[!] Warning: PostgreSQL appears inactive. Attempting to start..."
    sudo systemctl start postgresql 2>/dev/null || true
fi

# 4. Display Launch Banner
echo ""
echo "=========================================================="
echo "  مكتب معاذ خضر النمري للخدمات العقارية"
echo "  Starting RECRM Platform (FastAPI + PostgreSQL)..."
echo "=========================================================="
echo "  Dashboard URL: ${DASHBOARD_URL}"
echo "=========================================================="
echo ""

export PYTHONPATH=src/backend

open_browser_when_ready() {
    if [ "$OPEN_BROWSER" = true ] && command -v xdg-open >/dev/null 2>&1; then
        (
            for i in {1..20}; do
                if is_server_running; then
                    sleep 0.5
                    xdg-open "${DASHBOARD_URL}" >/dev/null 2>&1 &
                    break
                fi
                sleep 0.5
            done
        ) &
    fi
}

open_browser_when_ready

if [ "$MODE" = "daemon" ]; then
    nohup "$PYTHON_BIN" src/backend/run.py > "$LOG_FILE" 2>&1 &
    PID=$!
    echo "✓ Server started in background with PID: $PID"
    echo "✓ Logs: $LOG_FILE"
    echo "✓ To stop later, run: ./start_server.sh --stop"
    echo ""
    echo "Waiting for server to initialize..."
    for i in {1..15}; do
        if is_server_running; then
            echo "✓ RECRM is ready and operational!"
            echo "✓ Dashboard: ${DASHBOARD_URL}"
            exit 0
        fi
        sleep 0.5
    done
    echo "[!] Server started, check $LOG_FILE if needed."
else
    echo "Press Ctrl+C to stop the server at any time."
    echo ""
    exec "$PYTHON_BIN" src/backend/run.py
fi
