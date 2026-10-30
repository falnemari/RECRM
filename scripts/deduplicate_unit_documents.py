#!/usr/bin/env python3
"""
deduplicate_unit_documents.py
Cleans up duplicate documents for units in the documents table,
retaining the canonical/latest verified document for each (unit_id, document_type_id) pair.
"""

import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv(".env")

async def deduplicate_documents():
    conn = await asyncpg.connect(
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "fAlnemari@1392"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "re_db"),
    )

    print("--- Starting Document Deduplication Analysis ---")
    initial_total = await conn.fetchval("SELECT count(*) FROM documents")
    print(f"Total documents before deduplication: {initial_total}")

    # Find duplicates on (unit_id, document_type_id)
    dup_groups = await conn.fetch("""
        SELECT unit_id, document_type_id, count(*), 
               array_agg(document_id ORDER BY created_at DESC, document_id DESC) as doc_ids
        FROM documents
        WHERE unit_id IS NOT NULL
        GROUP BY unit_id, document_type_id
        HAVING count(*) > 1
        ORDER BY count(*) DESC
    """)

    print(f"Found {len(dup_groups)} duplicate groups across units.")

    all_ids_to_delete = []
    summary_report = []

    for group in dup_groups:
        unit_id = group["unit_id"]
        doc_type_id = group["document_type_id"]
        total = group["count"]
        doc_ids = group["doc_ids"]

        kept_id = doc_ids[0]
        to_delete = doc_ids[1:]
        all_ids_to_delete.extend(to_delete)

        dt_info = await conn.fetchrow("SELECT code, name FROM document_types WHERE document_type_id = $1", doc_type_id)
        dt_code = dt_info["code"] if dt_info else doc_type_id
        dt_name = dt_info["name"] if dt_info else ""

        summary_report.append({
            "unit_id": unit_id,
            "doc_type_code": dt_code,
            "doc_type_name": dt_name,
            "total_before": total,
            "kept_document_id": kept_id,
            "deleted_count": len(to_delete)
        })

    print(f"\nTotal duplicate document records marked for deletion: {len(all_ids_to_delete)}")

    if all_ids_to_delete:
        async with conn.transaction():
            # Delete referencing document_access_log entries first
            del_logs = await conn.execute(
                "DELETE FROM document_access_log WHERE document_id = ANY($1)",
                all_ids_to_delete
            )
            print(f"Cleaned up referencing access logs: {del_logs}")

            # Delete redundant duplicate document records
            del_docs = await conn.execute(
                "DELETE FROM documents WHERE document_id = ANY($1)",
                all_ids_to_delete
            )
            print(f"Cleaned up redundant documents: {del_docs}")

    final_total = await conn.fetchval("SELECT count(*) FROM documents")
    print(f"\nTotal documents after deduplication: {final_total}")
    print(f"Successfully eliminated {initial_total - final_total} duplicate records.\n")

    print("=== DEDUPLICATION BREAKDOWN ===")
    for s in summary_report:
        print(f"  • الوحدة: {s['unit_id']} | النوع: {s['doc_type_name']} ({s['doc_type_code']}) | الإجمالي السابق: {s['total_before']} -> تم الإبقاء على: {s['kept_document_id']} | تم حذف: {s['deleted_count']} مستند مكرر")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(deduplicate_documents())

