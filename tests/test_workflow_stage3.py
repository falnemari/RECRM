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


class TestWorkflowStage3(unittest.IsolatedAsyncioTestCase):

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
        # Find test unit
        self.unit_id = await self.conn.fetchval("SELECT unit_id FROM units LIMIT 1")

    async def asyncTearDown(self):
        await self.conn.close()

    async def test_stage3_schedule_property_viewing(self):
        """
        Rule: When scheduling a property viewing (TASK_VIEWING_SCHEDULE completed with viewing details):
          - Record inserted in 'viewings' table with status 'SCHEDULED'
          - Opportunity stage advanced to 'VIEWING'
          - Unit linked in 'opportunity_units' as primary
          - Activity ACT_VIEWING_SCHEDULED recorded
          - Outbound WhatsApp confirmation COMM_VIEWING_CONFIRMATION logged
          - Follow-up inspection report task TASK_VIEWING_REPORT auto-spawned with 2h SLA after visit
          - TASK_VIEWING_SCHEDULE marked COMPLETED
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-stage3-001"
            cust_id = "test-cust-stage3-001"
            opp_id = "test-opp-stage3-001"

            # Cleanup
            await self.conn.execute("DELETE FROM communications WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM viewings WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Sultan', 'Al-Otaibi', '+966599887766', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )

            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, branch_id, status, priority, inquiry_type, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'QUALIFIED', 'HIGH', 'BUY', NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.agent_id, self.branch_id
            )

            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'QUALIFIED', 1850000, NOW(), NOW())
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )

            # 1. Spawn Stage 3 TASK_VIEWING_SCHEDULE task
            sched_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_VIEWING_SCHEDULE",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id,
                priority="HIGH"
            )
            self.assertEqual(sched_task["status"], "PENDING")

            # 2. Schedule viewing through complete_task_with_outcome
            visit_time = datetime.now(timezone.utc) + timedelta(days=1, hours=2)
            viewing_data = {
                "unit_id": self.unit_id,
                "scheduled_start": visit_time.isoformat(),
                "viewing_duration_minutes": 45,
                "location_notes": "لقاء أمام بوابة المشروع الرئيسية والحارس معه المفاتيح"
            }

            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=sched_task["task_id"],
                user_id=self.agent_id,
                outcome="SCHEDULED",
                notes="تم التنسيق مع العميل لزيارة الوحدة ميدانياً غداً عصراً",
                viewing_data=viewing_data
            )

            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["new_stage"], "VIEWING")
            viewing_id = res["viewing_id"]
            self.assertIsNotNone(viewing_id)

            # 3. Check viewings table
            v_row = await self.conn.fetchrow("SELECT * FROM viewings WHERE viewing_id = $1", viewing_id)
            self.assertIsNotNone(v_row)
            self.assertEqual(v_row["status"], "SCHEDULED")
            self.assertEqual(v_row["opportunity_id"], opp_id)
            self.assertEqual(v_row["lead_id"], lead_id)
            self.assertEqual(v_row["unit_id"], self.unit_id)
            self.assertEqual(v_row["agent_user_id"], self.agent_id)
            self.assertIn("بوابة المشروع", v_row["notes"])

            # 4. Check opportunity stage updated to VIEWING
            opp = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
            self.assertEqual(opp["stage"], "VIEWING")

            # 5. Check opportunity_units has the viewed unit as primary
            opp_unit = await self.conn.fetchrow("SELECT is_primary FROM opportunity_units WHERE opportunity_id = $1 AND unit_id = $2", opp_id, self.unit_id)
            self.assertIsNotNone(opp_unit)
            self.assertTrue(opp_unit["is_primary"])

            # 6. Check Activity ACT_VIEWING_SCHEDULED
            act = await self.conn.fetchrow("SELECT * FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_VIEWING_SCHEDULED'", opp_id)
            self.assertIsNotNone(act)
            self.assertEqual(act["outcome"], "SCHEDULED")

            # 7. Check WhatsApp confirmation logged
            comm = await self.conn.fetchrow("SELECT * FROM communications WHERE customer_id = $1 AND template_id = 'COMM_VIEWING_CONFIRMATION'", cust_id)
            self.assertIsNotNone(comm)
            self.assertEqual(comm["channel"], "WHATSAPP")
            self.assertEqual(comm["direction"], "OUT")
            self.assertIn("تأكيد موعد المعاينة الميدانية", comm["subject"])

            # 8. Check auto-spawned TASK_VIEWING_REPORT
            rep_task = await self.conn.fetchrow(
                """
                SELECT * FROM tasks 
                WHERE opportunity_id = $1 AND template_id = 'TASK_VIEWING_REPORT' AND status IN ('PENDING', 'OPEN')
                """,
                opp_id
            )
            self.assertIsNotNone(rep_task, "TASK_VIEWING_REPORT must be automatically scheduled")
            self.assertEqual(rep_task["assigned_user_id"], self.agent_id)

        finally:
            await tr.rollback()

    async def test_stage3_complete_viewing_report_interested_transitions_to_negotiation(self):
        """
        Rule: When TASK_VIEWING_REPORT is completed with outcome 'INTERESTED':
          - Associated viewing record status -> 'COMPLETED', outcome -> 'INTERESTED'
          - Activity ACT_VIEWING_REPORT_SUBMITTED recorded
          - Opportunity stage advanced to 'NEGOTIATION'
          - Stage 4 task TASK_OFFER_SUBMIT is auto-spawned with priority 'HIGH'
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-stage3-002"
            cust_id = "test-cust-stage3-002"
            opp_id = "test-opp-stage3-002"

            await self.conn.execute("DELETE FROM communications WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM viewings WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Bandar', 'Al-Ghamdi', '+966588776655', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )

            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, branch_id, status, priority, inquiry_type, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'QUALIFIED', 'HIGH', 'BUY', NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.agent_id, self.branch_id
            )

            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'VIEWING', 2100000, NOW(), NOW())
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )

            # Insert scheduled viewing
            v_id = "test-viewing-002"
            await self.conn.execute(
                """
                INSERT INTO viewings (
                    viewing_id, opportunity_id, lead_id, unit_id, customer_id, agent_user_id,
                    scheduled_start, scheduled_end, status, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, NOW() - INTERVAL '1 hour', NOW(), 'SCHEDULED', NOW(), NOW())
                """,
                v_id, opp_id, lead_id, self.unit_id, cust_id, self.agent_id
            )

            # Spawn report task
            rep_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_VIEWING_REPORT",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id,
                priority="HIGH"
            )

            # Complete report task with INTERESTED
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=rep_task["task_id"],
                user_id=self.agent_id,
                outcome="INTERESTED",
                notes="العميل أبدى رغبة قوية بالشراء واقترح تقديم عرض بقيمة 2.05 مليون ريال",
                viewing_data={"offer_amount": 2050000}
            )

            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["new_stage"], "NEGOTIATION")

            # Check Viewing updated
            v_row = await self.conn.fetchrow("SELECT * FROM viewings WHERE viewing_id = $1", v_id)
            self.assertEqual(v_row["status"], "COMPLETED")
            self.assertEqual(v_row["outcome"], "INTERESTED")

            # Check Opportunity stage advanced to NEGOTIATION
            opp = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
            self.assertEqual(opp["stage"], "NEGOTIATION")

            # Check Activity recorded
            act = await self.conn.fetchrow("SELECT * FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_VIEWING_REPORT_SUBMITTED'", opp_id)
            self.assertIsNotNone(act)
            self.assertEqual(act["outcome"], "INTERESTED")

            # Check Stage 4 TASK_OFFER_SUBMIT auto-spawned
            offer_task = await self.conn.fetchrow(
                """
                SELECT * FROM tasks 
                WHERE opportunity_id = $1 AND template_id = 'TASK_OFFER_SUBMIT' AND status IN ('PENDING', 'OPEN')
                """,
                opp_id
            )
            self.assertIsNotNone(offer_task, "Stage 4 TASK_OFFER_SUBMIT must be auto-spawned")
            self.assertEqual(offer_task["assigned_user_id"], self.agent_id)

        finally:
            await tr.rollback()

    async def test_stage3_complete_viewing_report_needs_another_unit(self):
        """
        Rule: When TASK_VIEWING_REPORT is completed with outcome 'NEEDS_ANOTHER_UNIT':
          - Associated viewing record outcome -> 'NEEDS_ANOTHER_UNIT'
          - Opportunity remains in stage 'VIEWING'
          - New TASK_VIEWING_SCHEDULE is auto-spawned to organize another visit
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-stage3-003"
            cust_id = "test-cust-stage3-003"
            opp_id = "test-opp-stage3-003"

            await self.conn.execute("DELETE FROM viewings WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Mousa', 'Al-Shehri', '+966577665544', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )

            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, branch_id, status, priority, inquiry_type, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'QUALIFIED', 'NORMAL', 'BUY', NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.agent_id, self.branch_id
            )

            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'VIEWING', 1500000, NOW(), NOW())
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )

            # Insert scheduled viewing
            v_id = "test-viewing-003"
            await self.conn.execute(
                """
                INSERT INTO viewings (
                    viewing_id, opportunity_id, lead_id, unit_id, customer_id, agent_user_id,
                    scheduled_start, scheduled_end, status, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, NOW() - INTERVAL '1 hour', NOW(), 'SCHEDULED', NOW(), NOW())
                """,
                v_id, opp_id, lead_id, self.unit_id, cust_id, self.agent_id
            )

            # Spawn report task
            rep_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_VIEWING_REPORT",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )

            # Complete report task with NEEDS_ANOTHER_UNIT
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=rep_task["task_id"],
                user_id=self.agent_id,
                outcome="NEEDS_ANOTHER_UNIT",
                notes="الوحدة الحالية صغيرة، العميل طلب معاينة فيلا بمساحة أكبر 450م²"
            )

            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["new_stage"], "VIEWING")

            # Check Viewing updated
            v_row = await self.conn.fetchrow("SELECT * FROM viewings WHERE viewing_id = $1", v_id)
            self.assertEqual(v_row["outcome"], "NEEDS_ANOTHER_UNIT")

            # Check Opportunity stage remains VIEWING
            opp = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
            self.assertEqual(opp["stage"], "VIEWING")

            # Check new TASK_VIEWING_SCHEDULE is auto-spawned
            new_sched_task = await self.conn.fetchrow(
                """
                SELECT * FROM tasks 
                WHERE opportunity_id = $1 AND template_id = 'TASK_VIEWING_SCHEDULE' AND status IN ('PENDING', 'OPEN')
                """,
                opp_id
            )
            self.assertIsNotNone(new_sched_task, "Alternative TASK_VIEWING_SCHEDULE must be auto-spawned")

        finally:
            await tr.rollback()


if __name__ == "__main__":
    unittest.main()

