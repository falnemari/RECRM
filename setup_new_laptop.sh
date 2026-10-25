#!/usr/bin/env bash
# ==============================================================================
# RECRM - New Laptop Setup & Environment Initialization
# إعداد وتهيئة بيئة العمل لجهاز الكمبيوتر الجديد
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================================="
echo "  RECRM New Laptop Automated Setup"
echo "  مكتب معاذ خضر النمري للخدمات العقارية"
echo "=================================================================="

# 1. Require root / sudo
if [ "$EUID" -ne 0 ]; then
    echo ""
    echo "  [✗] Error: This script requires root privileges to configure PostgreSQL"
    echo "      and install required system packages."
    echo ""
    echo "  Please execute with sudo:"
    echo "      sudo bash setup_new_laptop.sh"
    echo ""
    exit 1
fi

REAL_USER="${SUDO_USER:-$USER}"
REAL_GROUP="$(id -gn "$REAL_USER")"

echo "  Current User: $REAL_USER"
echo "  Project Path: $SCRIPT_DIR"
echo "=================================================================="

# 2. Install System Packages
echo ""
echo "[1/6] Installing necessary system packages (Python, venv, build tools, PostgreSQL)..."
apt-get update -y
apt-get install -y \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev \
    build-essential \
    postgresql \
    postgresql-contrib \
    libpq-dev \
    curl \
    pgagent 2>/dev/null || true

# 3. Ensure PostgreSQL Service is active
echo ""
echo "[2/6] Verifying PostgreSQL service..."
systemctl enable postgresql
systemctl start postgresql

# Read .env configuration
DB_USER=$(grep -E "^DB_USER=" "${SCRIPT_DIR}/.env" 2>/dev/null | cut -d= -f2 | tr -d ' "\r' || true)
DB_PASSWORD=$(grep -E "^DB_PASSWORD=" "${SCRIPT_DIR}/.env" 2>/dev/null | cut -d= -f2 | tr -d ' "\r' || true)
DB_NAME=$(grep -E "^DB_NAME=" "${SCRIPT_DIR}/.env" 2>/dev/null | cut -d= -f2 | tr -d ' "\r' || true)
DB_PORT=$(grep -E "^DB_PORT=" "${SCRIPT_DIR}/.env" 2>/dev/null | cut -d= -f2 | tr -d ' "\r' || true)

[ -z "$DB_USER" ] && DB_USER="postgres"
[ -z "$DB_PASSWORD" ] && DB_PASSWORD="fAlnemari@1392"
[ -z "$DB_NAME" ] && DB_NAME="re_db"
[ -z "$DB_PORT" ] && DB_PORT="5432"

# 4. Configure PostgreSQL User & Databases
echo ""
echo "[3/6] Configuring PostgreSQL credentials & databases..."
sudo -u postgres psql -c "ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';" >/dev/null 2>&1 || true

for db in "redb" "re_db"; do
    if ! sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw "$db"; then
        echo "  [+] Creating database '${db}'..."
        sudo -u postgres psql -c "CREATE DATABASE ${db} OWNER ${DB_USER};" >/dev/null
    else
        echo "  [✓] Database '${db}' already exists."
    fi
done

# 5. Restore Database Schema and Seed Data
echo ""
echo "[4/6] Restoring database backup..."
FULL_CLUSTER_BACKUP="/home/nemro/all_databases_22102026_backup.sql"
SQL_BACKUP="${SCRIPT_DIR}/redb_backup_before_id_migration.sql"

if [ -f "$FULL_CLUSTER_BACKUP" ]; then
    echo "  [+] Found full cluster backup: $FULL_CLUSTER_BACKUP"
    echo "  [+] Restoring all databases (re_db, redb) and cluster roles..."
    sudo -u postgres psql -f "$FULL_CLUSTER_BACKUP" postgres > /dev/null 2>&1 || sudo -u postgres psql -f "$FULL_CLUSTER_BACKUP" postgres
    # Ensure password matches .env
    sudo -u postgres psql -c "ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';" >/dev/null 2>&1 || true
    echo "  [✓] Full database cluster successfully restored from $FULL_CLUSTER_BACKUP."
elif [ -f "$SQL_BACKUP" ]; then
    for db in "redb" "re_db"; do
        TABLE_COUNT=$(sudo -u postgres psql -d "$db" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null || echo "0")
        if [ "$TABLE_COUNT" -lt "5" ]; then
            echo "  [+] Restoring initial schema & seed data into '${db}'..."
            sudo -u postgres psql -d "$db" -f "$SQL_BACKUP" > /dev/null 2>&1
            echo "  [✓] Restoration completed for '${db}'."
        else
            echo "  [✓] Database '${db}' already has ${TABLE_COUNT} tables. Skipping baseline restore."
        fi
    done
else
    echo "  [!] Warning: Neither $FULL_CLUSTER_BACKUP nor $SQL_BACKUP found."
fi

# 6. Rebuild Python Virtual Environment (.venv)
echo ""
echo "[5/6] Building clean Python virtual environment (.venv)..."
rm -rf "${SCRIPT_DIR}/.venv"
sudo -u "$REAL_USER" python3 -m venv "${SCRIPT_DIR}/.venv"

echo "  [+] Upgrading pip and build tools..."
sudo -u "$REAL_USER" "${SCRIPT_DIR}/.venv/bin/pip" install --upgrade pip setuptools wheel --quiet

echo "  [+] Installing backend dependencies..."
sudo -u "$REAL_USER" "${SCRIPT_DIR}/.venv/bin/pip" install -r "${SCRIPT_DIR}/src/backend/requirements.txt" pytest pytest-asyncio --quiet

# Fix permissions
chown -R "${REAL_USER}:${REAL_GROUP}" "${SCRIPT_DIR}/.venv"

# 7. Apply Migrations and Seeds
echo ""
echo "[6/6] Applying database migrations and seeds..."
export PYTHONPATH="${SCRIPT_DIR}/src/backend"

# Run migrate_ids on both databases
for db in "re_db" "redb"; do
    echo "  [+] Running ID migration on '${db}'..."
    sudo -u "$REAL_USER" DB_NAME="$db" PYTHONPATH="${SCRIPT_DIR}/src/backend" \
        "${SCRIPT_DIR}/.venv/bin/python" "${SCRIPT_DIR}/scripts/migrate_ids.py" || true
done

echo "  [+] Running workflow table migrations..."
sudo -u "$REAL_USER" PYTHONPATH="${SCRIPT_DIR}/src/backend" \
    "${SCRIPT_DIR}/.venv/bin/python" "${SCRIPT_DIR}/scripts/migrate_workflow_tables.py" || true

for db in "re_db" "redb"; do
    echo "  [+] Seeding investment workflow templates on '${db}'..."
    sudo -u "$REAL_USER" DB_NAME="$db" PYTHONPATH="${SCRIPT_DIR}/src/backend" \
        "${SCRIPT_DIR}/.venv/bin/python" "${SCRIPT_DIR}/scripts/seed_investment_templates.py" || true
done

# Verification
echo ""
echo "=================================================================="
echo "  Verification & Health Check"
echo "=================================================================="
sudo -u "$REAL_USER" "${SCRIPT_DIR}/.venv/bin/python" -c "
import fastapi, uvicorn, asyncpg, sqlalchemy, pydantic
print('  [✓] Python dependencies loaded successfully')
"

TABLE_COUNT=$(PGPASSWORD="${DB_PASSWORD}" psql -h localhost -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null || echo "0")
if [ "$TABLE_COUNT" -gt "0" ]; then
    echo "  [✓] PostgreSQL connection verified (Database: '${DB_NAME}', Tables: ${TABLE_COUNT})"
else
    echo "  [!] Warning: Could not verify PostgreSQL connection on localhost:${DB_PORT}"
fi

echo "=================================================================="
echo "  ✓ Setup complete! System is ready to run."
echo "  تم إعداد النظام بنجاح وجاهز للتشغيل."
echo ""
echo "  To launch RECRM:"
echo "      ./start_server.sh"
echo "=================================================================="

