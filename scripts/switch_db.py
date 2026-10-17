#!/usr/bin/env python3
"""
RECRM Database Switcher (أداة التبديل بين قواعد البيانات)
======================================================
Easily toggle between:
  - 'redb'  : Original Database (البيانات الأصلية المحفوظة)
  - 're_db' : Clean Testing Database (قاعدة الاختبار النظيفة مع جداول النظام فقط)
"""

import sys
import os
import re
import asyncio
from pathlib import Path

# Add backend to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "src" / "backend"
sys.path.insert(0, str(backend_dir))

import asyncpg
from app.config import settings

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
MAIN_FILE = backend_dir / "app" / "main.py"
ALLOWED_DBS = ["redb", "re_db"]


async def get_db_summary(dbname: str):
    """Fetch quick summary of records in a given database."""
    try:
        conn = await asyncpg.connect(
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=dbname,
        )
        users = await conn.fetchval("SELECT count(*) FROM users")
        branches = await conn.fetchval("SELECT count(*) FROM branches")
        customers = await conn.fetchval("SELECT count(*) FROM customers")
        leads = await conn.fetchval("SELECT count(*) FROM leads")
        units = await conn.fetchval("SELECT count(*) FROM units")
        opps = await conn.fetchval("SELECT count(*) FROM opportunities")
        await conn.close()
        return {
            "status": "connected",
            "users": users,
            "branches": branches,
            "customers": customers,
            "leads": leads,
            "units": units,
            "opportunities": opps,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_current_env_db() -> str:
    """Read current DB_NAME from .env file."""
    if not ENV_FILE.exists():
        return settings.DB_NAME
    content = ENV_FILE.read_text(encoding="utf-8")
    match = re.search(r"^DB_NAME\s*=\s*(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else settings.DB_NAME


def set_env_db(target_db: str):
    """Update DB_NAME in .env file and touch main.py to trigger reload."""
    if not ENV_FILE.exists():
        ENV_FILE.write_text(f"DB_NAME={target_db}\n", encoding="utf-8")
    else:
        content = ENV_FILE.read_text(encoding="utf-8")
        if re.search(r"^DB_NAME\s*=", content, re.MULTILINE):
            new_content = re.sub(r"^DB_NAME\s*=.*$", f"DB_NAME={target_db}", content, flags=re.MULTILINE)
        else:
            new_content = content.rstrip() + f"\nDB_NAME={target_db}\n"
        ENV_FILE.write_text(new_content, encoding="utf-8")

    # Touch main.py so uvicorn --reload detects the change and re-initializes DB pool
    if MAIN_FILE.exists():
        MAIN_FILE.touch()


async def main():
    current_db = get_current_env_db()

    # If no target DB argument passed, display status of both
    if len(sys.argv) < 2:
        print("\n" + "=" * 65)
        print("  RECRM DATABASE STATUS & SWITCHER")
        print("=" * 65)
        print(f"👉 Current Active Database in .env: [{current_db}]\n")

        for db in ALLOWED_DBS:
            indicator = "🟢 ACTIVE" if db == current_db else "⚪ STANDBY"
            info = await get_db_summary(db)
            print(f"Database: {db:10} [{indicator}]")
            if info["status"] == "connected":
                print(f"  - Users / Branches : {info['users']} users, {info['branches']} branches")
                print(f"  - Operational Data : {info['customers']} customers, {info['leads']} leads, {info['units']} units, {info['opportunities']} deals")
            else:
                print(f"  - Error connecting: {info.get('error')}")
            print("-" * 50)

        print("\nTo switch active database, run:")
        print("  python scripts/switch_db.py re_db   # (Switch to fresh testing DB)")
        print("  python scripts/switch_db.py redb    # (Switch to original DB)\n")
        return

    target_db = sys.argv[1].strip()
    if target_db not in ALLOWED_DBS:
        print(f"❌ Invalid database '{target_db}'. Allowed choices: {ALLOWED_DBS}")
        sys.exit(1)

    if target_db == current_db:
        print(f"ℹ️ Active database is already set to '{target_db}'.")
        return

    print(f"\n🔄 Switching active database from '{current_db}' to '{target_db}'...")
    set_env_db(target_db)

    # Verify connection to target DB
    info = await get_db_summary(target_db)
    print("\n" + "=" * 65)
    print(f"✅ SUCCESSFULLY SWITCHED TO: {target_db.upper()}")
    print("=" * 65)
    print(f"  - Users / Branches : {info['users']} users, {info['branches']} branches (Config preserved)")
    print(f"  - Operational Data : {info['customers']} customers, {info['leads']} leads, {info['units']} units, {info['opportunities']} deals")
    print("  - Backend reloaded automatically via uvicorn hot-reload.")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    asyncio.run(main())

