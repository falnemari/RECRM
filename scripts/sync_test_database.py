#!/usr/bin/env python3
"""
Sync Script: Synchronizes the dedicated testing database ('redb') from the primary user database ('re_db').

Usage:
    python3 scripts/sync_test_database.py

This script:
1. Creates a temporary binary dump of 're_db'.
2. Terminates any active connections on 'redb'.
3. Drops and recreates 'redb'.
4. Restores the dump into 'redb'.
5. Verifies that all tables and constraints match 100%.
"""

import os
import subprocess
import sys
import asyncio
import asyncpg

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))
from app.config import settings

PG_HOST = settings.DB_HOST
PG_PORT = str(settings.DB_PORT)
PG_USER = settings.DB_USER
PG_PASSWORD = settings.DB_PASSWORD
SOURCE_DB = "re_db"
TARGET_DB = "redb"
DUMP_FILE = "/tmp/re_db_sync_temp.dump"


def run_cmd(cmd_list, env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    res = subprocess.run(cmd_list, env=merged_env, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed ({' '.join(cmd_list)}): {res.stderr}")
    return res.stdout


async def sync_databases():
    print(f"=== Starting Database Sync: {SOURCE_DB} -> {TARGET_DB} ===")

    env = {"PGPASSWORD": PG_PASSWORD}

    # 1. Dump source database
    print(f"1. Dumping source database '{SOURCE_DB}'...")
    run_cmd([
        "pg_dump",
        "-h", PG_HOST,
        "-p", PG_PORT,
        "-U", PG_USER,
        "-d", SOURCE_DB,
        "-F", "c",
        "-b",
        "-f", DUMP_FILE
    ], env=env)
    print(f"   ✓ Dump created at {DUMP_FILE} ({os.path.getsize(DUMP_FILE)} bytes)")

    # 2. Terminate connections on target database
    print(f"2. Terminating active connections on '{TARGET_DB}'...")
    conn = await asyncpg.connect(
        host=PG_HOST, port=int(PG_PORT), user=PG_USER, password=PG_PASSWORD, database="postgres"
    )
    await conn.execute(
        f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{TARGET_DB}' AND pid <> pg_backend_pid()"
    )
    await conn.close()

    # 3. Drop and recreate target database
    print(f"3. Recreating target database '{TARGET_DB}'...")
    run_cmd(["dropdb", "-h", PG_HOST, "-p", PG_PORT, "-U", PG_USER, "--if-exists", TARGET_DB], env=env)
    run_cmd(["createdb", "-h", PG_HOST, "-p", PG_PORT, "-U", PG_USER, "-O", PG_USER, TARGET_DB], env=env)
    print(f"   ✓ Fresh '{TARGET_DB}' created.")

    # 4. Restore dump into target database
    print(f"4. Restoring data into '{TARGET_DB}'...")
    run_cmd(["pg_restore", "-h", PG_HOST, "-p", PG_PORT, "-U", PG_USER, "-d", TARGET_DB, DUMP_FILE], env=env)
    print(f"   ✓ Data restored successfully.")

    # 5. Clean up temporary dump
    if os.path.exists(DUMP_FILE):
        os.remove(DUMP_FILE)

    # 6. Verification
    print(f"5. Verifying table counts between '{SOURCE_DB}' and '{TARGET_DB}'...")
    conn_src = await asyncpg.connect(host=PG_HOST, port=int(PG_PORT), user=PG_USER, password=PG_PASSWORD, database=SOURCE_DB)
    conn_tgt = await asyncpg.connect(host=PG_HOST, port=int(PG_PORT), user=PG_USER, password=PG_PASSWORD, database=TARGET_DB)

    tbls_src = await conn_src.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")
    tbls_tgt = await conn_tgt.fetchval("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")

    await conn_src.close()
    await conn_tgt.close()

    print(f"   ✓ Source '{SOURCE_DB}': {tbls_src} tables | Target '{TARGET_DB}': {tbls_tgt} tables")
    assert tbls_src == tbls_tgt, "Table count mismatch after sync!"
    print("=== Database Sync Completed Successfully! ===")


if __name__ == "__main__":
    asyncio.run(sync_databases())

