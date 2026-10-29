#!/usr/bin/env python3
"""
Script: scripts/cleanup_initial_call_leads.py
Purpose: Safely inspect or clean up test/unprocessed leads whose initial contact task
         is still pending, along with their associated tasks, activities, and events.

SAFETY NOTICE:
  By default, this script runs in DRY-RUN (read-only) mode.
  No deletions or modifications are made unless the explicit '--confirm' flag is provided.
"""
import asyncio
import sys
from pathlib import Path

# Add src/backend to pythonpath
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "backend"))

import asyncpg
from app.config import settings


async def cleanup_initial_call_leads(action: str = "dry-run", confirmed: bool = False):
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    
    # Identify target leads that are in 'NEW' status and still require the initial call task
    target_query = """
        SELECT l.lead_id, l.customer_id, l.assigned_user_id, l.created_at
        FROM leads l
        WHERE l.status = 'NEW'
          AND EXISTS (
              SELECT 1 FROM tasks t
              WHERE t.lead_id = l.lead_id
                AND (t.template_id IN ('TASK_LEAD_FIRST_CONTACT', 'TASK_RENT_LEAD_FIRST_CONTACT', 'TASK_INVEST_LEAD_FIRST_CONTACT', 'TASK_LEAD_INITIAL_CALL')
                     OR t.title LIKE '%اتصال أولي%' OR t.title LIKE '%إتصال أولي%' OR t.title LIKE '%الاتصال الأولي%')
                AND t.status IN ('PENDING', 'OPEN')
          )
          AND NOT EXISTS (SELECT 1 FROM opportunities WHERE lead_id = l.lead_id)
          AND NOT EXISTS (SELECT 1 FROM documents WHERE lead_id = l.lead_id)
          AND NOT EXISTS (SELECT 1 FROM viewings WHERE lead_id = l.lead_id)
        ORDER BY l.created_at DESC
    """
    rows = await conn.fetch(target_query)
    target_lead_ids = [r["lead_id"] for r in rows]
    
    count = len(target_lead_ids)
    print(f"[CLEANUP GUARD] Identified {count} candidate lead(s) with pending initial contact task.")
    
    if count == 0:
        print("[CLEANUP GUARD] No matching leads found. Exiting safely.")
        await conn.close()
        return

    if action == "dry-run" or not confirmed:
        print("[DRY-RUN REPORT] No changes made to database. Found candidates:")
        for r in rows:
            print(f"  - Lead ID: {r['lead_id']} | Cust: {r['customer_id']} | Agent: {r['assigned_user_id']} | Created: {r['created_at']}")
        print("[SAFETY NOTICE] Script execution stopped. To execute changes, specify --confirm explicitly.")
        await conn.close()
        return

    async with conn.transaction():
        if action == "delete":
            t_del = await conn.execute("DELETE FROM tasks WHERE lead_id = ANY($1)", target_lead_ids)
            a_del = await conn.execute("DELETE FROM activities WHERE lead_id = ANY($1)", target_lead_ids)
            e_del = await conn.execute("DELETE FROM lead_events WHERE lead_id = ANY($1)", target_lead_ids)
            c_del = await conn.execute("DELETE FROM communications WHERE lead_id = ANY($1)", target_lead_ids)
            u_del = await conn.execute("DELETE FROM lead_units WHERE lead_id = ANY($1)", target_lead_ids)
            l_del = await conn.execute("DELETE FROM leads WHERE lead_id = ANY($1)", target_lead_ids)

            print(f"[CONFIRMED] Successfully purged {count} leads.")
            print(f"Details: {t_del}, {a_del}, {e_del}, {c_del}, {u_del}, {l_del}")

        elif action == "cancel":
            t_upd = await conn.execute(
                "UPDATE tasks SET status = 'CANCELLED', updated_at = NOW() WHERE lead_id = ANY($1) AND status IN ('PENDING', 'OPEN')",
                target_lead_ids
            )
            l_upd = await conn.execute(
                "UPDATE leads SET status = 'CANCELLED', updated_at = NOW() WHERE lead_id = ANY($1)",
                target_lead_ids
            )
            print(f"[CONFIRMED] Successfully cancelled {count} leads and their pending tasks.")
            print(f"Details: {l_upd}, {t_upd}")

    await conn.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    is_confirmed = "--confirm" in args
    clean_args = [a for a in args if a != "--confirm"]
    req_action = clean_args[0] if len(clean_args) > 0 else "dry-run"
    
    if not is_confirmed and req_action != "dry-run":
        print(f"[SAFETY GUARD] Action '{req_action}' requested without --confirm. Forcing dry-run mode.")
        req_action = "dry-run"
        
    asyncio.run(cleanup_initial_call_leads(action=req_action, confirmed=is_confirmed))
