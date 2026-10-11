import asyncio
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent / "src" / "backend"
sys.path.insert(0, str(backend_dir))

import asyncpg
from app.config import settings

async def run_migration():
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    print("Connected to PostgreSQL redb successfully.")

    async with conn.transaction():
        # 1. Inspect all foreign key constraints
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
        print(f"Found {len(fks)} foreign key constraints.")

        # 2. Inspect all primary keys
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
        
        # Group PKs by table
        pk_by_table = {}
        for r in pks:
            pk_by_table.setdefault(r['table_name'], []).append(r['column_name'])

        # 3. Find all UUID columns in public schema
        uuid_cols = await conn.fetch("""
            SELECT table_name, column_name 
            FROM information_schema.columns 
            WHERE table_schema = 'public' AND data_type = 'uuid'
            ORDER BY table_name, column_name;
        """)
        print(f"Found {len(uuid_cols)} UUID columns to convert.")

        # 4. Drop all foreign key constraints
        print("\n--- Dropping Foreign Key Constraints ---")
        for fk in fks:
            await conn.execute(f"ALTER TABLE \"{fk['src_table']}\" DROP CONSTRAINT \"{fk['constraint_name']}\";")
        print(f"Dropped {len(fks)} foreign key constraints.")

        # 5. Drop defaults on UUID columns (such as gen_random_uuid())
        print("\n--- Dropping default gen_random_uuid() constraints ---")
        for uc in uuid_cols:
            await conn.execute(f"ALTER TABLE \"{uc['table_name']}\" ALTER COLUMN \"{uc['column_name']}\" DROP DEFAULT;")

        # 6. Alter all UUID columns to VARCHAR(64)
        print("\n--- Altering UUID columns to VARCHAR(64) ---")
        for uc in uuid_cols:
            await conn.execute(f"ALTER TABLE \"{uc['table_name']}\" ALTER COLUMN \"{uc['column_name']}\" TYPE VARCHAR(64) USING \"{uc['column_name']}\"::text;")
        print("All UUID columns successfully altered to VARCHAR(64).")

        # 7. Generate mapping for all single-PK entity tables
        # Format: column_name without "id" + "-" + sequence no
        global_map = {} # old_uuid_str -> new_id_str
        max_seqs = {}   # table_name -> max_seq

        print("\n--- Generating new readable IDs ---")
        for table_name, pk_cols in pk_by_table.items():
            if len(pk_cols) == 1:
                pk_col = pk_cols[0]
                # Determine prefix: column_name without "id" (or "_id")
                if pk_col.endswith("_id"):
                    prefix = pk_col[:-3]
                elif pk_col.endswith("id"):
                    prefix = pk_col[:-2]
                else:
                    prefix = pk_col

                # Check if table has created_at
                has_created_at = await conn.fetchval("""
                    SELECT count(*) FROM information_schema.columns 
                    WHERE table_schema = 'public' AND table_name = $1 AND column_name = 'created_at';
                """, table_name)

                order_clause = "ORDER BY created_at ASC" if has_created_at > 0 else f"ORDER BY \"{pk_col}\" ASC"
                rows = await conn.fetch(f"SELECT \"{pk_col}\" FROM \"{table_name}\" {order_clause};")

                for idx, r in enumerate(rows, start=1):
                    old_id = str(r[pk_col])
                    new_id = f"{prefix}-{idx}"
                    global_map[old_id] = new_id

                max_seqs[table_name] = (prefix, pk_col, len(rows))
                print(f"  {table_name:25} ({pk_col}) -> {len(rows)} records mapped to '{prefix}-1' .. '{prefix}-{len(rows)}'")

        # 8. Update Primary Keys
        print("\n--- Updating Primary Key tables with new IDs ---")
        for table_name, (prefix, pk_col, count) in max_seqs.items():
            rows = await conn.fetch(f"SELECT \"{pk_col}\" FROM \"{table_name}\";")
            for r in rows:
                old_id = str(r[pk_col])
                if old_id in global_map:
                    new_id = global_map[old_id]
                    await conn.execute(
                        f"UPDATE \"{table_name}\" SET \"{pk_col}\" = $1 WHERE \"{pk_col}\" = $2;",
                        new_id, old_id
                    )

        # 9. Update Foreign Keys across all tables
        print("\n--- Updating Foreign Key columns with new IDs ---")
        for fk in fks:
            src_table = fk['src_table']
            src_col = fk['src_col']
            
            # Find distinct values currently in src_col
            rows = await conn.fetch(f"SELECT DISTINCT \"{src_col}\" FROM \"{src_table}\" WHERE \"{src_col}\" IS NOT NULL;")
            updated_count = 0
            for r in rows:
                old_val = str(r[src_col])
                if old_val in global_map:
                    new_val = global_map[old_val]
                    await conn.execute(
                        f"UPDATE \"{src_table}\" SET \"{src_col}\" = $1 WHERE \"{src_col}\" = $2;",
                        new_val, old_val
                    )
                    updated_count += 1
            if updated_count > 0:
                print(f"  Updated {src_table}.{src_col} ({updated_count} distinct FK values updated)")

        # 10. Update audit_logs.entity_id if matches
        audit_rows = await conn.fetch("SELECT DISTINCT entity_id FROM audit_logs WHERE entity_id IS NOT NULL;")
        audit_updated = 0
        for r in audit_rows:
            old_val = str(r['entity_id'])
            if old_val in global_map:
                new_val = global_map[old_val]
                await conn.execute("UPDATE audit_logs SET entity_id = $1 WHERE entity_id = $2;", new_val, old_val)
                audit_updated += 1
        if audit_updated > 0:
            print(f"  Updated audit_logs.entity_id ({audit_updated} entity references updated)")

        # 11. Recreate Foreign Key Constraints with ON UPDATE CASCADE
        print("\n--- Re-creating Foreign Key Constraints with ON UPDATE CASCADE ---")
        for fk in fks:
            src_table = fk['src_table']
            src_col = fk['src_col']
            tgt_table = fk['tgt_table']
            tgt_col = fk['tgt_col']
            c_name = fk['constraint_name']
            del_rule = fk['delete_rule']
            
            del_clause = f"ON DELETE {del_rule}" if del_rule and del_rule != "NO ACTION" else ""
            sql = f"""
                ALTER TABLE "{src_table}" 
                ADD CONSTRAINT "{c_name}" 
                FOREIGN KEY ("{src_col}") REFERENCES "{tgt_table}"("{tgt_col}")
                ON UPDATE CASCADE {del_clause};
            """
            await conn.execute(sql)
        print(f"Re-created all {len(fks)} foreign key constraints successfully!")

        # 12. Create PostgreSQL sequences and set column defaults for future inserts
        print("\n--- Creating Sequences and Setting Defaults for Auto-Increment IDs ---")
        for table_name, (prefix, pk_col, count) in max_seqs.items():
            seq_name = f"seq_{table_name}_id"
            start_val = count + 1
            await conn.execute(f"DROP SEQUENCE IF EXISTS \"{seq_name}\";")
            await conn.execute(f"CREATE SEQUENCE \"{seq_name}\" START WITH {start_val};")
            await conn.execute(f"""
                ALTER TABLE "{table_name}" 
                ALTER COLUMN "{pk_col}" 
                SET DEFAULT ('{prefix}-' || nextval('{seq_name}')::text);
            """)
            print(f"  {table_name}.{pk_col} -> default ('{prefix}-' || nextval('{seq_name}')) [starts at {start_val}]")

    print("\n✓ DATABASE TRANSACTION COMMITTED SUCCESSFULLY!")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(run_migration())

