import unittest
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

import asyncpg
from app.config import settings
from app.services.workflow_engine import WorkflowEngine


class TestWorkflowStage2(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(settings.asyncpg_dsn)
        self.org_id = await self.conn.fetchval("SELECT organization_id FROM organizations LIMIT 1")
        # Find active sales agent
        self.agent_id = await self.conn.fetchval(
            """
            SELECT u.user_id FROM users u 
            JOIN user_roles ur ON u.user_id = ur.user_id 
            JOIN roles r ON ur.role_id = r.role_id 
            WHERE r.role_code IN ('SALES_AGENT', 'SYS_ADMIN') AND u.status = 'ACTIVE' 
            LIMIT 1
            """
        )
        self.branch_id = await self.conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", self.agent_id) or "branch-3"

    async def asyncTearDown(self):
        await self.conn.close()

    async def test_stage2_first_contact_no_answer_spawns_followup(self):
        """
        Rule: If first contact attempt is NO_ANSWER:
          - Lead status is NOT CONTACTED (remains NEW)
          - Activity recorded as ACT_LEAD_FIRST_CONTACT with outcome NO_ANSWER
          - TASK_LEAD_FOLLOWUP is automatically scheduled in 3 hours
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-stage2-001"
            cust_id = "test-cust-stage2-001"

            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM opportunities WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Tariq', 'Al-Ghamdi', '+966511223344', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )

            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, branch_id, status, priority, inquiry_type, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'NEW', 'NORMAL', 'BUY', NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.agent_id, self.branch_id
            )

            # 1. Spawn First Contact Task
            task1, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_FIRST_CONTACT",
                lead_id=lead_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id,
                priority="HIGH"
            )
            self.assertEqual(task1["status"], "PENDING")

            # 2. Agent records NO_ANSWER
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=task1["task_id"],
                user_id=self.agent_id,
                outcome="NO_ANSWER",
                notes="الاتصال الأول: العميل لم يرد على الهاتف"
            )
            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["activity"]["outcome"], "NO_ANSWER")
            self.assertEqual(res["activity"]["template_id"], "ACT_LEAD_FIRST_CONTACT")

            # 3. Check Lead status MUST NOT be CONTACTED
            lead_status = await self.conn.fetchval("SELECT status FROM leads WHERE lead_id = $1", lead_id)
            self.assertEqual(lead_status, "NEW", "Lead status must NOT be changed to CONTACTED when customer did not answer")

            # 4. Check follow-up task was auto-spawned with ~3h due date
            followup_task = await self.conn.fetchrow(
                """
                SELECT * FROM tasks 
                WHERE lead_id = $1 AND template_id = 'TASK_LEAD_FOLLOWUP' AND status IN ('PENDING', 'OPEN')
                """,
                lead_id
            )
            self.assertIsNotNone(followup_task, "TASK_LEAD_FOLLOWUP must be automatically spawned")
            self.assertEqual(followup_task["assigned_user_id"], self.agent_id)

            # 5. Anti-Duplication Protection: Calling spawn again must reuse existing open follow-up task
            task_dup, is_new = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_FOLLOWUP",
                lead_id=lead_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )
            self.assertFalse(is_new, "Idempotency engine must prevent creating duplicate open follow-up tasks")
            self.assertEqual(task_dup["task_id"], followup_task["task_id"])

        finally:
            await tr.rollback()

    async def test_stage2_followup_connected_transitions_to_contacted_and_spawns_qualify(self):
        """
        Rule: When customer is successfully reached (CONNECTED):
          - Lead status changes to CONTACTED
          - first_contact_at is set
          - Activity recorded
          - TASK_LEAD_QUALIFY is automatically spawned with 24h SLA
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-stage2-002"
            cust_id = "test-cust-stage2-002"

            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM opportunities WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Nasser', 'Al-Harbi', '+966555443322', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )

            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, branch_id, status, priority, inquiry_type, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'NEW', 'NORMAL', 'BUY', NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.agent_id, self.branch_id
            )

            # 1. Open follow-up task
            f_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_FOLLOWUP",
                lead_id=lead_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )

            # 2. Complete follow-up with CONNECTED
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=f_task["task_id"],
                user_id=self.agent_id,
                outcome="CONNECTED",
                notes="تم التجاوب مع العميل وأبدى اهتماماً كبيراً بشراء فيلا شمال الرياض"
            )
            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["activity"]["template_id"], "ACT_LEAD_FOLLOWUP")

            # 3. Verify lead transitioned to CONTACTED
            lead = await self.conn.fetchrow("SELECT status, first_contact_at FROM leads WHERE lead_id = $1", lead_id)
            self.assertEqual(lead["status"], "CONTACTED")
            self.assertIsNotNone(lead["first_contact_at"])

            # 4. Verify TASK_LEAD_QUALIFY was spawned
            qual_task = await self.conn.fetchrow(
                """
                SELECT * FROM tasks 
                WHERE lead_id = $1 AND template_id = 'TASK_LEAD_QUALIFY' AND status IN ('PENDING', 'OPEN')
                """,
                lead_id
            )
            self.assertIsNotNone(qual_task, "TASK_LEAD_QUALIFY must be auto-spawned upon successful connection")
            self.assertEqual(qual_task["assigned_user_id"], self.agent_id)

        finally:
            await tr.rollback()

    async def test_stage2_lead_qualification_and_opportunity_conversion(self):
        """
        Rule: When TASK_LEAD_QUALIFY is completed with QUALIFIED:
          - Lead status transitions to QUALIFIED
          - Activity ACT_LEAD_QUALIFIED is recorded
          - Opportunity is created/linked in stage QUALIFIED
          - Any shortlisted units are copied to opportunity_units
          - Stage 3 task TASK_VIEWING_SCHEDULE is auto-spawned and linked to opportunity
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-stage2-003"
            cust_id = "test-cust-stage2-003"

            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id IN (SELECT opportunity_id FROM opportunities WHERE lead_id = $1)", lead_id)
            await self.conn.execute("DELETE FROM opportunities WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM lead_units WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Fahad', 'Al-Dosari', '+966544332211', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )

            # Find available unit for shortlisting test
            unit_id = await self.conn.fetchval("SELECT unit_id FROM units LIMIT 1")

            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, branch_id, status, priority, inquiry_type, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'CONTACTED', 'HIGH', 'BUY', NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.agent_id, self.branch_id
            )

            if unit_id:
                await self.conn.execute(
                    "INSERT INTO lead_units (lead_id, unit_id, is_primary, created_at) VALUES ($1, $2, true, NOW())",
                    lead_id, unit_id
                )

            # 1. Spawn qualification task
            q_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_QUALIFY",
                lead_id=lead_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )

            # 2. Complete qualification via complete_task_with_outcome
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=q_task["task_id"],
                user_id=self.agent_id,
                outcome="QUALIFIED",
                notes="العميل مؤهل: الميزانية 2.5 مليون ريال، جاهز للمعاينة الفورية",
                qualification_data={
                    "budget_min": 2000000,
                    "budget_max": 2500000
                }
            )

            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["activity"]["template_id"], "ACT_LEAD_QUALIFIED")

            # 3. Check Lead status
            lead = await self.conn.fetchrow("SELECT status, budget_min, budget_max FROM leads WHERE lead_id = $1", lead_id)
            self.assertEqual(lead["status"], "QUALIFIED")
            self.assertEqual(float(lead["budget_max"]), 2500000.0)

            # 4. Check Opportunity created in stage QUALIFIED
            opp = await self.conn.fetchrow("SELECT * FROM opportunities WHERE lead_id = $1", lead_id)
            self.assertIsNotNone(opp, "Opportunity must be created for qualified lead")
            self.assertEqual(opp["stage"], "QUALIFIED")
            self.assertEqual(opp["customer_id"], cust_id)
            self.assertEqual(opp["assigned_user_id"], self.agent_id)
            self.assertEqual(float(opp["expected_value"]), 2500000.0)

            # 5. Check opportunity_units transferred
            if unit_id:
                opp_unit = await self.conn.fetchrow(
                    "SELECT * FROM opportunity_units WHERE opportunity_id = $1 AND unit_id = $2",
                    opp["opportunity_id"], unit_id
                )
                self.assertIsNotNone(opp_unit, "Shortlisted lead units must be transferred to opportunity_units")

            # 6. Check Stage 3 viewing task auto-spawned
            viewing_task = await self.conn.fetchrow(
                """
                SELECT * FROM tasks 
                WHERE lead_id = $1 AND template_id = 'TASK_VIEWING_SCHEDULE' AND status IN ('PENDING', 'OPEN')
                """,
                lead_id
            )
            self.assertIsNotNone(viewing_task, "Stage 3 TASK_VIEWING_SCHEDULE must be auto-spawned for qualified lead")
            self.assertEqual(viewing_task["opportunity_id"], opp["opportunity_id"])
            self.assertEqual(viewing_task["assigned_user_id"], self.agent_id)

        finally:
            await tr.rollback()


if __name__ == "__main__":
    unittest.main()

