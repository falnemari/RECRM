import asyncio
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent / "src" / "backend"
sys.path.insert(0, str(backend_dir))

import asyncpg
from app.config import settings

async def main():
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    
    # 1. Primary keys
    pks = await conn.fetch("""
        SELECT tc.table_name, kcu.column_name, c.data_type
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu 
            ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.columns c
            ON c.table_name = tc.table_name AND c.column_name = kcu.column_name AND c.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public'
        ORDER BY tc.table_name, kcu.ordinal_position;
    """)
    print("=== PRIMARY KEYS ===")
    pk_map = {}
    for r in pks:
        t, col, dtype = r['table_name'], r['column_name'], r['data_type']
        pk_map.setdefault(t, []).append((col, dtype))
        print(f"  {t:30} | {col:25} | {dtype}")

    # 2. Foreign keys
    fks = await conn.fetch("""
        SELECT
            tc.table_name AS src_table,
            kcu.column_name AS src_col,
            ccu.table_name AS tgt_table,
            ccu.column_name AS tgt_col,
            rc.update_rule,
            rc.delete_rule,
            tc.constraint_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.referential_constraints AS rc
            ON tc.constraint_name = rc.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
        ORDER BY tc.table_name, kcu.column_name;
    """)
    print(f"\n=== FOREIGN KEYS ({len(fks)}) ===")
    for fk in fks:
        print(f"  {fk['src_table']:25}.{fk['src_col']:25} -> {fk['tgt_table']}.{fk['tgt_col']} ({fk['constraint_name']})")

    # 3. All UUID columns
    uuid_cols = await conn.fetch("""
        SELECT table_name, column_name 
        FROM information_schema.columns 
        WHERE table_schema = 'public' AND data_type = 'uuid'
        ORDER BY table_name, column_name;
    """)
    print(f"\n=== ALL UUID COLUMNS ({len(uuid_cols)}) ===")
    for c in uuid_cols:
        print(f"  {c['table_name']:28} | {c['column_name']}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())

