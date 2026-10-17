import unittest
import asyncpg
from datetime import datetime, timezone, timedelta
from app.config import settings
from app.services.workflow_engine import WorkflowEngine

class TestSmartReopenUndo(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(settings.asyncpg_dsn)
        self.org_id = await self.conn.fetchval("SELECT organization_id FROM organizations LIMIT 1")
        self.agent_id = await self.conn.fetchval(
            """
            SELECT u.user_id FROM users u 
            JOIN user_roles ur ON u.user_id = ur.user_id 
            JOIN roles r ON ur.role_id = r.role_id 
            WHERE r.role_code IN ('SALES_AGENT', 'SYS_ADMIN') AND u.status = 'ACTIVE' 
            LIMIT 1
            """
        ) or "user-51"
        self.branch_id = await self.conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", self.agent_id) or "branch-3"
        self.unit_id = await self.conn.fetchval("SELECT unit_id FROM units LIMIT 1")
        self.city_id = await self.conn.fetchval("SELECT city_id FROM cities LIMIT 1")
        self.pt_id = await self.conn.fetchval("SELECT property_type_id FROM property_types LIMIT 1")

    async def asyncTearDown(self):
        await self.conn.close()

    async def test_reopen_first_contact_no_answer(self):
        """
        Test completing first contact with NO_ANSWER (which spawns a follow-up task),
        then smart reopening it to cancel downstream tasks and reset to PENDING.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-reopen-01"
            cust_id = "test-cust-reopen-01"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Reopen', 'Customer', '+966500998877', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, branch_id, status, priority, inquiry_type, assigned_user_id, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'ASSIGNED', 'NORMAL', 'BUY', $5, NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.branch_id, self.agent_id
            )

            # Spawn First Contact task
            task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_FIRST_CONTACT",
                lead_id=lead_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )
            task_id = task["task_id"]

            # Complete task with NO_ANSWER -> generates followup task with parent_task_id
            res_comp = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=task_id,
                user_id=self.agent_id,
                outcome="NO_ANSWER",
                notes="Client phone busy"
            )
            self.assertEqual(res_comp["status"], "COMPLETED")

            # Verify downstream followup task was spawned
            followup = await self.conn.fetchrow(
                "SELECT task_id, status, parent_task_id FROM tasks WHERE lead_id = $1 AND template_id = 'TASK_LEAD_FOLLOWUP'",
                lead_id
            )
            self.assertIsNotNone(followup)
            self.assertEqual(followup["parent_task_id"], task_id)

            # Reopen the first contact task!
            reopen_res = await WorkflowEngine.reopen_task(
                conn=self.conn,
                task_id=task_id,
                user_id=self.agent_id,
                reason="Customer called back immediately"
            )
            self.assertTrue(reopen_res["reopened"])
            self.assertEqual(reopen_res["status"], "PENDING")

            # Check database: original task is PENDING, completed_at is NULL
            orig = await self.conn.fetchrow("SELECT status, completed_at FROM tasks WHERE task_id = $1", task_id)
            self.assertEqual(orig["status"], "PENDING")
            self.assertIsNone(orig["completed_at"])

            # Check database: downstream followup task was removed
            remaining_followup = await self.conn.fetchrow(
                "SELECT task_id FROM tasks WHERE lead_id = $1 AND template_id = 'TASK_LEAD_FOLLOWUP'",
                lead_id
            )
            self.assertIsNone(remaining_followup)

            # Check audit activity ACT_TASK_REOPENED
            reopen_act = await self.conn.fetchrow(
                "SELECT template_id, outcome, description FROM activities WHERE task_id = $1 AND template_id = 'ACT_TASK_REOPENED'",
                task_id
            )
            self.assertIsNotNone(reopen_act)
            self.assertEqual(reopen_act["outcome"], "REOPENED")

        finally:
            await tr.rollback()

    async def test_reopen_qualification_and_opportunity_rollback(self):
        """
        Test completing qualification with QUALIFIED (creating an Opportunity and spawning viewing/matching),
        then smart reopening it to rollback the opportunity and reset to PENDING.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-reopen-02"
            cust_id = "test-cust-reopen-02"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Qual', 'Customer', '+966500998878', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, branch_id, status, priority, inquiry_type, assigned_user_id, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'CONTACTED', 'NORMAL', 'BUY', $5, NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.branch_id, self.agent_id
            )

            qual_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_QUALIFY",
                lead_id=lead_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )
            task_id = qual_task["task_id"]

            # Complete qualification
            res_qual = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=task_id,
                user_id=self.agent_id,
                outcome="QUALIFIED",
                notes="Qualified for luxury apartment",
                qualification_data={"budget_min": 1000000, "budget_max": 1500000}
            )
            self.assertEqual(res_qual["status"], "COMPLETED")

            # Verify Lead is QUALIFIED and Opportunity exists
            lead_row = await self.conn.fetchrow("SELECT status FROM leads WHERE lead_id = $1", lead_id)
            self.assertEqual(lead_row["status"], "QUALIFIED")

            opp_row = await self.conn.fetchrow("SELECT opportunity_id, stage FROM opportunities WHERE lead_id = $1", lead_id)
            self.assertIsNotNone(opp_row)
            self.assertEqual(opp_row["stage"], "QUALIFIED")

            # Smart Reopen qualification task
            reopen_res = await WorkflowEngine.reopen_task(
                conn=self.conn,
                task_id=task_id,
                user_id=self.agent_id,
                reason="Client financial pre-approval was revoked"
            )
            self.assertTrue(reopen_res["reopened"])

            # Verify task is back to PENDING
            t_after = await self.conn.fetchrow("SELECT status, completed_at FROM tasks WHERE task_id = $1", task_id)
            self.assertEqual(t_after["status"], "PENDING")
            self.assertIsNone(t_after["completed_at"])

            # Verify Lead reverted to CONTACTED
            lead_after = await self.conn.fetchrow("SELECT status FROM leads WHERE lead_id = $1", lead_id)
            self.assertEqual(lead_after["status"], "CONTACTED")

            # Verify unworked Opportunity was deleted
            opp_after = await self.conn.fetchrow("SELECT opportunity_id FROM opportunities WHERE lead_id = $1", lead_id)
            self.assertIsNone(opp_after)

            # Verify downstream tasks removed
            downstream = await self.conn.fetch(
                "SELECT task_id, template_id FROM tasks WHERE lead_id = $1 AND template_id != 'TASK_LEAD_QUALIFY'",
                lead_id
            )
            self.assertEqual(len(downstream), 0)

        finally:
            await tr.rollback()

    async def test_safety_block_when_downstream_task_already_completed(self):
        """
        Anti-Corruption Safety Rule:
        If a downstream task has ALREADY been completed, reopening the parent task
        MUST raise an error and halt execution to prevent wiping out real completed work.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-reopen-03"
            cust_id = "test-cust-reopen-03"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Safety', 'Customer', '+966500998879', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, branch_id, status, priority, inquiry_type, assigned_user_id, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'ASSIGNED', 'NORMAL', 'BUY', $5, NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.branch_id, self.agent_id
            )

            # 1. First Contact task
            first_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_FIRST_CONTACT",
                lead_id=lead_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )
            first_id = first_task["task_id"]

            # Complete first contact -> spawns TASK_LEAD_QUALIFY
            await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=first_id,
                user_id=self.agent_id,
                outcome="CONNECTED",
                notes="Connected"
            )

            qual_task = await self.conn.fetchrow(
                "SELECT task_id FROM tasks WHERE lead_id = $1 AND template_id = 'TASK_LEAD_QUALIFY'",
                lead_id
            )
            self.assertIsNotNone(qual_task)
            qual_id = qual_task["task_id"]

            # 2. Complete the downstream task (TASK_LEAD_QUALIFY)!
            await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=qual_id,
                user_id=self.agent_id,
                outcome="QUALIFIED",
                notes="Qualified"
            )

            # 3. Attempt to reopen the parent task (first_id) -> MUST RAISE ValueError with safety block!
            with self.assertRaises(ValueError) as ctx:
                await WorkflowEngine.reopen_task(
                    conn=self.conn,
                    task_id=first_id,
                    user_id=self.agent_id,
                    reason="Illegal undo attempt"
                )

            self.assertIn("لا يمكن التراجع تلقائياً لوجود مهمة تابعة", str(ctx.exception))

        finally:
            await tr.rollback()

    async def test_reopen_viewing_schedule_and_cancel_viewing(self):
        """
        Stage D Rollback:
        Completing TASK_VIEWING_SCHEDULE creates a scheduled viewing and spawns TASK_VIEWING_REPORT.
        Reopening TASK_VIEWING_SCHEDULE must delete/cancel the scheduled viewing and report task,
        and revert opportunity stage back to QUALIFIED.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-reopen-04"
            cust_id = "test-cust-reopen-04"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Viewing', 'Customer', '+966500998880', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, branch_id, status, priority, inquiry_type, assigned_user_id, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'QUALIFIED', 'NORMAL', 'BUY', $5, NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.branch_id, self.agent_id
            )

            # Create an opportunity in QUALIFIED stage
            opp_id = "test-opp-reopen-04"
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'QUALIFIED', NOW(), NOW())
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )

            # Spawn TASK_VIEWING_SCHEDULE
            sch_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_VIEWING_SCHEDULE",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )
            sch_task_id = sch_task["task_id"]

            # Complete schedule viewing
            start_dt = datetime.now(timezone.utc) + timedelta(days=2)
            end_dt = start_dt + timedelta(minutes=45)
            comp_res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=sch_task_id,
                user_id=self.agent_id,
                outcome="SCHEDULED",
                viewing_data={
                    "unit_id": self.unit_id,
                    "scheduled_start": start_dt.isoformat(),
                    "scheduled_end": end_dt.isoformat(),
                    "location_notes": "Meet at front gate"
                }
            )
            self.assertEqual(comp_res["status"], "COMPLETED")

            # Verify viewing was created and opp stage is VIEWING
            viewing = await self.conn.fetchrow(
                "SELECT viewing_id, status FROM viewings WHERE opportunity_id = $1 AND status = 'SCHEDULED'",
                opp_id
            )
            self.assertIsNotNone(viewing)

            opp_after_sch = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
            self.assertEqual(opp_after_sch["stage"], "VIEWING")

            # Verify TASK_VIEWING_REPORT was spawned
            report_task = await self.conn.fetchrow(
                "SELECT task_id FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_VIEWING_REPORT'",
                opp_id
            )
            self.assertIsNotNone(report_task)

            # Now smart reopen the viewing schedule task!
            reopen_res = await WorkflowEngine.reopen_task(
                conn=self.conn,
                task_id=sch_task_id,
                user_id=self.agent_id,
                reason="Landlord unavailable on that day"
            )
            self.assertTrue(reopen_res["reopened"])

            # Verify original task is PENDING again
            orig_task = await self.conn.fetchrow("SELECT status, completed_at FROM tasks WHERE task_id = $1", sch_task_id)
            self.assertEqual(orig_task["status"], "PENDING")
            self.assertIsNone(orig_task["completed_at"])

            # Verify report task was deleted
            report_after = await self.conn.fetchrow(
                "SELECT task_id FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_VIEWING_REPORT'",
                opp_id
            )
            self.assertIsNone(report_after)

            # Verify scheduled viewing was deleted/cleaned
            viewing_after = await self.conn.fetchrow(
                "SELECT viewing_id FROM viewings WHERE opportunity_id = $1 AND status = 'SCHEDULED'",
                opp_id
            )
            self.assertIsNone(viewing_after)

            # Verify opp stage reverted to QUALIFIED
            opp_after_reopen = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
            self.assertEqual(opp_after_reopen["stage"], "QUALIFIED")

        finally:
            await tr.rollback()

if __name__ == "__main__":
    unittest.main()
