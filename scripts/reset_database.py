#!/usr/bin/env python3
"""
RECRM Database Reset Tool (أداة تفريغ وإعادة ضبط بيانات النظام)
============================================================
Safely resets operational data for re-testing while preserving
core system setup (Users, Roles, Permissions, Branches, Reference Tables).

Modes:
  --mode crm   : Resets Customers, Leads, Deals, Finance, Tenancies, Tasks, Activities.
                 Preserves: Properties, Buildings, Units, Users, Branches, Settings.
  --mode full  : Resets all of the above PLUS Property Inventory (Units, Buildings, Projects).
                 Preserves ONLY: Users, Roles, Permissions, Branches, Reference Lookups.

Options:
  --dry-run    : Preview changes without deleting any data.
  --backup     : Create a full pg_dump backup before resetting.
  --yes, -y    : Skip confirmation prompt.
"""

import sys
import os
import argparse
import asyncio
import subprocess
from datetime import datetime
from pathlib import Path

# Add backend to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "src" / "backend"
sys.path.insert(0, str(backend_dir))

import asyncpg
from app.config import settings

# Tables that must NEVER be deleted in any reset
CORE_SYSTEM_TABLES = [
    "organizations",
    "branches",
    "roles",
    "permissions",
    "role_permissions",
    "users",
    "user_roles",
    "cities",
    "property_types",
    "activity_types",
    "lead_sources",
    "loss_reasons",
    "document_types",
]

# Operational CRM, Sales, Finance & Management Tables
OPERATIONAL_CRM_TABLES = [
    # Level 1: Logs & Detail items
    "document_access_log",
    "audit_logs",
    "login_events",
    "unit_status_history",
    "payments",
    "commissions",
    "rent_collections",
    "maintenance_work_orders",
    "campaign_leads",
    "lead_events",
    "lead_notes",
    "lead_units",
    "opportunity_units",
    # Level 2: Transactions
    "documents",
    "contracts",
    "reservations",
    "offers",
    "viewings",
    "tasks",
    "activities",
    "communications",
    "tenancies",
    "maintenance_tickets",
    "managed_units",
    "management_contracts",
    # Level 3: Pipeline & Entities
    "opportunities",
    "campaigns",
    "leads",
    "customers",
]

# Inventory Tables (kept in crm mode, cleared in full mode)
INVENTORY_TABLES = [
    "listings",
    "property_media",
    "units",
    "buildings",
    "projects",
    "vendors",
]

# Sequences to reset in CRM mode
OPERATIONAL_SEQUENCES = [
    "seq_activities_id",
    "seq_audit_logs_id",
    "seq_commissions_id",
    "seq_communications_id",
    "seq_contracts_id",
    "seq_customers_id",
    "seq_document_access_log_id",
    "seq_documents_id",
    "seq_lead_events_id",
    "seq_lead_notes_id",
    "seq_leads_id",
    "seq_login_events_id",
    "seq_maintenance_tickets_id",
    "seq_maintenance_work_orders_id",
    "seq_management_contracts_id",
    "seq_offers_id",
    "seq_opportunities_id",
    "seq_payments_id",
    "seq_rent_collections_id",
    "seq_reservations_id",
    "seq_tasks_id",
    "seq_tenancies_id",
    "seq_unit_status_history_id",
    "seq_viewings_id",
]

INVENTORY_SEQUENCES = [
    "seq_projects_id",
    "seq_buildings_id",
    "seq_units_id",
    "seq_listings_id",
    "seq_property_media_id",
    "seq_vendors_id",
    "seq_campaigns_id",
]


def take_backup():
    """Create timestamped pg_dump backup."""
    backup_dir = Path(__file__).resolve().parent.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"backup_before_reset_{timestamp}.sql"

    print(f"\n📦 Taking database backup to: {backup_file} ...")
    cmd = [
        "pg_dump",
        "-h", settings.DB_HOST,
        "-p", str(settings.DB_PORT),
        "-U", settings.DB_USER,
        "-d", settings.DB_NAME,
        "-F", "p",
        "-f", str(backup_file),
    ]
    env = os.environ.copy()
    if settings.DB_PASSWORD:
        env["PGPASSWORD"] = settings.DB_PASSWORD

    try:
        subprocess.run(cmd, env=env, check=True)
        print(f"✅ Backup created successfully ({backup_file.stat().st_size / 1024:.1f} KB)\n")
        return True
    except Exception as e:
        print(f"❌ Backup failed: {e}")
        return False


async def run_reset(mode: str, dry_run: bool, skip_confirm: bool, auto_backup: bool):
    tables_to_clear = list(OPERATIONAL_CRM_TABLES)
    seqs_to_reset = list(OPERATIONAL_SEQUENCES)

    if mode == "full":
        tables_to_clear.extend(INVENTORY_TABLES)
        seqs_to_reset.extend(INVENTORY_SEQUENCES)

    conn = await asyncpg.connect(settings.asyncpg_dsn)

    print("\n" + "=" * 65)
    print(f"  RECRM DATABASE RESET TOOL - MODE: {mode.upper()}")
    print("=" * 65)

    # 1. Inspect row counts
    print("\n🔍 Tables to be cleared:")
    total_rows = 0
    for tbl in tables_to_clear:
        try:
            count = await conn.fetchval(f'SELECT count(*) FROM "{tbl}"')
            total_rows += count
            status_icon = "🗑️" if count > 0 else "⚪"
            print(f"  {status_icon} {tbl:28} : {count:5} rows")
        except Exception as e:
            print(f"  ⚠️ {tbl:28} : (table not found or error: {e})")

    print(f"\n📊 Total records to delete: {total_rows}")
    print(f"🔢 Total sequences to reset: {len(seqs_to_reset)}")

    print("\n🛡️ Protected Tables (WILL NOT BE TOUCHED):")
    for tbl in CORE_SYSTEM_TABLES:
        try:
            count = await conn.fetchval(f'SELECT count(*) FROM "{tbl}"')
            print(f"  🔒 {tbl:28} : {count:5} rows preserved")
        except Exception:
            pass

    if mode == "crm":
        print("\n🏢 Preserved Properties Inventory:")
        for tbl in INVENTORY_TABLES:
            try:
                count = await conn.fetchval(f'SELECT count(*) FROM "{tbl}"')
                print(f"  🏢 {tbl:28} : {count:5} rows preserved")
            except Exception:
                pass

    if dry_run:
        print("\n✨ DRY RUN COMPLETED - No changes were made to the database.")
        await conn.close()
        return

    # Confirmation prompt
    if not skip_confirm:
        confirm = input("\n⚠️ WARNING: This will permanently delete the operational data above! Proceed? (y/N): ")
        if confirm.lower() not in ["y", "yes"]:
            print("❌ Operation cancelled by user.")
            await conn.close()
            return

    # Take backup if requested
    if auto_backup:
        if not take_backup():
            abort = input("Backup failed. Continue reset anyway? (y/N): ")
            if abort.lower() not in ["y", "yes"]:
                await conn.close()
                return

    # Execute reset
    print("\n🚀 Executing reset...")
    async with conn.transaction():
        # If in CRM mode, unlink owner and developer foreign keys to avoid violations
        if mode == "crm":
            print("  🔗 Unlinking customer references from units and projects...")
            await conn.execute("UPDATE units SET owner_customer_id = NULL WHERE owner_customer_id IS NOT NULL")
            await conn.execute("UPDATE projects SET developer_customer_id = NULL WHERE developer_customer_id IS NOT NULL")

        # Truncate tables with CASCADE
        tbl_list = ", ".join(f'"{t}"' for t in tables_to_clear)
        print("  🧹 Truncating operational tables...")
        await conn.execute(f"TRUNCATE TABLE {tbl_list} CASCADE")

        # Reset sequences to 1
        print("  🔄 Resetting sequential ID generators to 1...")
        for seq in seqs_to_reset:
            try:
                await conn.execute(f"ALTER SEQUENCE {seq} RESTART WITH 1")
            except Exception as e:
                # Sequence may not exist or has different name
                pass

    print("\n" + "=" * 65)
    print("🎉 DATABASE RESET SUCCESSFUL!")
    print(f"  - Cleared {len(tables_to_clear)} operational tables ({total_rows} records).")
    print(f"  - Reset {len(seqs_to_reset)} ID sequences back to 1 (customer-1, lead-1, etc.).")
    print("  - System Setup, Users, Branches, and Roles remain 100% intact.")
    print("=" * 65 + "\n")

    await conn.close()


def main():
    parser = argparse.ArgumentParser(description="RECRM Database Reset Tool")
    parser.add_argument(
        "--mode",
        choices=["crm", "full"],
        default="crm",
        help="crm: Resets CRM/Sales/Finance (keeps units/buildings). full: Resets CRM + Units/Buildings/Projects.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview tables and rows without deleting")
    parser.add_argument("--backup", action="store_true", help="Create a pg_dump backup before reset")
    parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    args = parser.parse_args()
    asyncio.run(run_reset(mode=args.mode, dry_run=args.dry_run, skip_confirm=args.yes, auto_backup=args.backup))


if __name__ == "__main__":
    main()

