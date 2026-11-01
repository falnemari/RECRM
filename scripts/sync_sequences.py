import asyncio
import asyncpg
import re
from app.config import settings

async def main():
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    seqs = await conn.fetch("""
        SELECT sequence_name FROM information_schema.sequences 
        WHERE sequence_schema = 'public' ORDER BY sequence_name;
    """)
    for s in seqs:
        seq_name = s['sequence_name']
        match = re.match(r'seq_(.+)_id', seq_name)
        if not match:
            continue
        table_name = match.group(1)
        
        exists = await conn.fetchval(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = $1",
            table_name
        )
        if not exists:
            continue
            
        pk_col = await conn.fetchval(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name = $1
            LIMIT 1;
            """,
            table_name
        )
        
        if not pk_col:
            continue
            
        try:
            query = f"""
                SELECT MAX(SUBSTRING({pk_col} FROM '[0-9]+')::bigint)
                FROM {table_name}
                WHERE {pk_col} ~ '[0-9]+';
            """
            max_val = await conn.fetchval(query)
            if max_val:
                new_val = max_val + 50
                await conn.execute(f"SELECT setval('{seq_name}', {new_val})")
                print(f"Synced {seq_name} -> {new_val} (current max was: {max_val})")
            else:
                await conn.execute(f"SELECT setval('{seq_name}', 100)")
        except Exception as e:
            print(f"Error syncing {seq_name}: {e}")
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())

