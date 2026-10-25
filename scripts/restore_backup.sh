#!/usr/bin/env bash
# ==============================================================================
# RECRM - Standalone Database Restore Script
# استرجاع قاعدة البيانات من ملف النسخة الاحتياطية
# ==============================================================================

set -e

BACKUP_FILE="${1:-/home/nemro/all_databases_22102026_backup.sql}"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "[✗] Error: Backup file not found at: $BACKUP_FILE"
    exit 1
fi

echo "=================================================================="
echo "  Restoring PostgreSQL Database Cluster"
echo "  Source: $BACKUP_FILE"
echo "=================================================================="

sudo -u postgres psql -f "$BACKUP_FILE" postgres

# Ensure postgres password matches .env
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'fAlnemari@1392';" >/dev/null 2>&1 || true

echo ""
echo "=================================================================="
echo "  ✓ Database restore completed successfully!"
echo "  تم استرجاع قواعد البيانات بنجاح."
echo "=================================================================="

