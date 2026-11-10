import unittest
from datetime import datetime, timezone
import asyncpg
from app.config import settings
from app.database import get_next_id
from app.services.workflow_engine import WorkflowEngine


class TestTaskParentResolutionAndNoDuplicateUpdates(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(settings.asyncpg_dsn)
        self.created_task_ids = []
        self.created_opp_ids = []
        self.created_lead_ids = []
        self.created_cust_ids = []
        self.created_act_ids = []
        self.created_viewing_ids = []
        self.avail_unit_id = await self.conn.fetchval("SELECT unit_id FROM units WHERE status = 'AVAILABLE' LIMIT 1")

    async def asyncTearDown(self):
        if self.created_act_ids:
            await self.conn.execute("DELETE FROM activities WHERE activity_id = ANY($1::text[])", self.created_act_ids)
        if self.created_task_ids:
            await self.conn.execute("DELETE FROM tasks WHERE task_id = ANY($1::text[])", self.created_task_ids)
        if self.created_viewing_ids:
            await self.conn.execute("DELETE FROM viewings WHERE viewing_id = ANY($1::text[])", self.created_viewing_ids)
        if self.created_opp_ids:
            await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = ANY($1::text[])", self.created_opp_ids)
            await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = ANY($1::text[])", self.created_opp_ids)
            await self.conn.execute("DELETE FROM activities WHERE opportunity_id = ANY($1::text[])", self.created_opp_ids)
            await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = ANY($1::text[])", self.created_opp_ids)
        if self.created_lead_ids:
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = ANY($1::text[])", self.created_lead_ids)
            await self.conn.execute("DELETE FROM activities WHERE lead_id = ANY($1::text[])", self.created_lead_ids)
            await self.conn.execute("DELETE FROM communications WHERE lead_id = ANY($1::text[])", self.created_lead_ids)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = ANY($1::text[])", self.created_lead_ids)
        if self.created_cust_ids:
            await self.conn.execute("DELETE FROM communications WHERE customer_id = ANY($1::text[])", self.created_cust_ids)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = ANY($1::text[])", self.created_cust_ids)
        await self.conn.close()

    async def test_present_properties_auto_resolves_parent_task(self):
        """
        Verify that when present_opportunity_properties is called with parent_task_id=None,
        it automatically resolves the open TASK_OPPORTUNITY_MATCH_PROPERTIES,
        links the activity to this task_id, and sets parent_task_id on the spawned TASK_VIEWING_SCHEDULE.
        """
        now = datetime.now(timezone.utc)
        cust_id = await get_next_id(self.conn, "customers", "cust")
        self.created_cust_ids.append(cust_id)
        await self.conn.execute(
            "INSERT INTO customers (customer_id, organization_id, first_name, last_name, mobile, email, customer_type) VALUES ($1, 'organization-1', 'اختبار', 'الربط', '0599999991', 'test_parent@crm.com', 'BUYER')",
            cust_id
        )

        lead_id = await get_next_id(self.conn, "leads", "lead")
        self.created_lead_ids.append(lead_id)
        await self.conn.execute(
            "INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at) VALUES ($1, 'organization-1', $2, 'user-51', 'QUALIFIED', 'HIGH', 'BUY', $3, $3)",
            lead_id, cust_id, now
        )

        opp_id = await get_next_id(self.conn, "opportunities", "opp")
        self.created_opp_ids.append(opp_id)
        await self.conn.execute(
            "INSERT INTO opportunities (opportunity_id, lead_id, customer_id, stage, expected_value, created_at, updated_at) VALUES ($1, $2, $3, 'QUALIFIED', 1000000, $4, $4)",
            opp_id, lead_id, cust_id, now
        )

        # Spawn Stage C matching task
        match_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_OPPORTUNITY_MATCH_PROPERTIES",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=cust_id,
            assigned_user_id="user-51",
            priority="HIGH"
        )
        matching_task_id = match_task["task_id"]
        self.created_task_ids.append(matching_task_id)

        # Call present_opportunity_properties WITHOUT passing parent_task_id (e.g. from present-units endpoint)
        res = await WorkflowEngine.present_opportunity_properties(
            conn=self.conn,
            user_id="user-51",
            opportunity_id=opp_id,
            unit_ids=[self.avail_unit_id],
            parent_task_id=None
        )

        # 1. Verify matching task is COMPLETED
        match_row = await self.conn.fetchrow("SELECT status, completed_at FROM tasks WHERE task_id = $1", matching_task_id)
        self.assertEqual(match_row["status"], "COMPLETED")
        self.assertIsNotNone(match_row["completed_at"])

        # 2. Verify activity is linked to matching_task_id
        act_id = res["activity"]["activity_id"]
        self.created_act_ids.append(act_id)
        act_row = await self.conn.fetchrow("SELECT task_id, status FROM activities WHERE activity_id = $1", act_id)
        self.assertEqual(act_row["task_id"], matching_task_id)
        self.assertEqual(act_row["status"], "COMPLETED")

        # 3. Verify spawned viewing task has parent_task_id = matching_task_id
        view_task_id = res["viewing_task"]["task_id"]
        self.created_task_ids.append(view_task_id)
        view_row = await self.conn.fetchrow("SELECT parent_task_id, template_id, status FROM tasks WHERE task_id = $1", view_task_id)
        self.assertEqual(view_row["parent_task_id"], matching_task_id)
        self.assertEqual(view_row["template_id"], "TASK_VIEWING_SCHEDULE")
        self.assertEqual(view_row["status"], "PENDING")

    async def test_viewing_schedule_no_duplicate_completed_updates(self):
        """
        Verify that completing TASK_VIEWING_SCHEDULE via complete_task_with_outcome
        does NOT produce duplicate UPDATE audit logs for the task.
        """
        now = datetime.now(timezone.utc)
        cust_id = await get_next_id(self.conn, "customers", "cust")
        self.created_cust_ids.append(cust_id)
        await self.conn.execute(
            "INSERT INTO customers (customer_id, organization_id, first_name, last_name, mobile, email, customer_type) VALUES ($1, 'organization-1', 'اختبار', 'التكرار', '0599999992', 'test_dup@crm.com', 'BUYER')",
            cust_id
        )

        lead_id = await get_next_id(self.conn, "leads", "lead")
        self.created_lead_ids.append(lead_id)
        await self.conn.execute(
            "INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at) VALUES ($1, 'organization-1', $2, 'user-51', 'QUALIFIED', 'HIGH', 'BUY', $3, $3)",
            lead_id, cust_id, now
        )

        opp_id = await get_next_id(self.conn, "opportunities", "opp")
        self.created_opp_ids.append(opp_id)
        await self.conn.execute(
            "INSERT INTO opportunities (opportunity_id, lead_id, customer_id, stage, expected_value, created_at, updated_at) VALUES ($1, $2, $3, 'QUALIFIED', 1000000, $4, $4)",
            opp_id, lead_id, cust_id, now
        )

        view_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_VIEWING_SCHEDULE",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=cust_id,
            assigned_user_id="user-51",
            priority="HIGH"
        )
        task_id = view_task["task_id"]
        self.created_task_ids.append(task_id)

        # Clear audit logs for this specific task before completing
        await self.conn.execute(
            "DELETE FROM database_audit_logs WHERE table_name = 'tasks' AND (new_data->>'task_id' = $1 OR old_data->>'task_id' = $1)",
            task_id
        )

        # Complete the task
        res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=task_id,
            user_id="user-51",
            outcome="SCHEDULED",
            viewing_data={
                "unit_id": self.avail_unit_id,
                "scheduled_start": datetime.now(timezone.utc).isoformat()
            }
        )
        self.assertEqual(res["status"], "COMPLETED")
        if res.get("viewing_id"):
            self.created_viewing_ids.append(res["viewing_id"])
        if res.get("activity") and res["activity"].get("activity_id"):
            self.created_act_ids.append(res["activity"]["activity_id"])
        if res.get("business_transition") and res["business_transition"].get("report_task"):
            self.created_task_ids.append(res["business_transition"]["report_task"]["task_id"])

        # Query audit logs for updates on this task
        audit_rows = await self.conn.fetch(
            "SELECT audit_id, operation, old_data->>'status' as old_st, new_data->>'status' as new_st FROM database_audit_logs WHERE table_name = 'tasks' AND (new_data->>'task_id' = $1 OR old_data->>'task_id' = $1) AND operation = 'UPDATE' ORDER BY audit_id ASC",
            task_id
        )

        # There should be EXACTLY ONE update (PENDING -> COMPLETED), NO duplicate (COMPLETED -> COMPLETED)
        self.assertEqual(
            len(audit_rows), 1,
            f"Expected 1 update audit log, but found {len(audit_rows)}: {[dict(r) for r in audit_rows]}"
        )
        self.assertEqual(audit_rows[0]["old_st"], "PENDING")
        self.assertEqual(audit_rows[0]["new_st"], "COMPLETED")

    async def test_lead_assignment_links_activity_and_spawns_parent_task(self):
        """
        Verify that completing TASK_LEAD_ASSIGN:
        1. Links ACT_LEAD_ASSIGNED activity to task_id (the assign task).
        2. Sets parent_task_id on TASK_LEAD_FIRST_CONTACT (pointing to the assign task).
        """
        now = datetime.now(timezone.utc)
        cust_id = await get_next_id(self.conn, "customers", "cust")
        self.created_cust_ids.append(cust_id)
        await self.conn.execute(
            "INSERT INTO customers (customer_id, organization_id, first_name, last_name, mobile, email, customer_type) VALUES ($1, 'organization-1', 'اختبار', 'التعيين', '0599999993', 'test_assign@crm.com', 'BUYER')",
            cust_id
        )

        lead_id = await get_next_id(self.conn, "leads", "lead")
        self.created_lead_ids.append(lead_id)
        await self.conn.execute(
            "INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at) VALUES ($1, 'organization-1', $2, 'user-5', 'NEW', 'HIGH', 'BUY', $3, $3)",
            lead_id, cust_id, now
        )

        assign_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_LEAD_ASSIGN",
            lead_id=lead_id,
            customer_id=cust_id,
            assigned_user_id="user-5",
            priority="HIGH"
        )
        assign_task_id = assign_task["task_id"]
        self.created_task_ids.append(assign_task_id)

        # Complete TASK_LEAD_ASSIGN assigning lead to user-43
        res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=assign_task_id,
            user_id="user-5",
            outcome="ASSIGNED",
            viewing_data={"assigned_user_id": "user-43"}
        )
        self.assertEqual(res["status"], "COMPLETED")

        # 1. Verify assign task is COMPLETED
        t_row = await self.conn.fetchrow("SELECT status, completed_at FROM tasks WHERE task_id = $1", assign_task_id)
        self.assertEqual(t_row["status"], "COMPLETED")

        # 2. Verify ACT_LEAD_ASSIGNED activity has task_id = assign_task_id
        act = res.get("activity")
        self.assertIsNotNone(act)
        self.created_act_ids.append(act["activity_id"])
        act_row = await self.conn.fetchrow("SELECT task_id, status FROM activities WHERE activity_id = $1", act["activity_id"])
        self.assertEqual(act_row["task_id"], assign_task_id)

        # 3. Verify TASK_LEAD_FIRST_CONTACT has parent_task_id = assign_task_id
        next_t = res.get("next_task")
        self.assertIsNotNone(next_t)
        self.created_task_ids.append(next_t["task_id"])
        next_row = await self.conn.fetchrow("SELECT parent_task_id, template_id, assigned_user_id FROM tasks WHERE task_id = $1", next_t["task_id"])
        self.assertEqual(next_row["parent_task_id"], assign_task_id)
        self.assertIn(next_row["template_id"], ("TASK_LEAD_FIRST_CONTACT", "TASK_SALES_LEAD_CONTACT_QUALIFY"))
        self.assertEqual(next_row["assigned_user_id"], "user-43")
