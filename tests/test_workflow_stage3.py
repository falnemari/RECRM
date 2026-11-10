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
            unit_price = await self.conn.fetchval("SELECT asking_price FROM units WHERE unit_id = $1", self.unit_id) or 2500000.0
            test_offer = min(2050000.0, float(unit_price) * 0.95)
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=rep_task["task_id"],
                user_id=self.agent_id,
                outcome="INTERESTED",
                notes=f"العميل أبدى رغبة قوية بالشراء واقترح تقديم عرض بقيمة {test_offer:,.0f} ريال",
                viewing_data={"offer_amount": test_offer}
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

    async def test_stage3_viewing_report_offer_ceiling_enforcement(self):
        """
        Rule: Proposed offer amount in TASK_VIEWING_REPORT must never exceed the property unit's price.
        - If offer_amount > unit_asking_price: raises ValueError with Arabic explanation.
        - If offer_amount <= unit_asking_price: updates opportunity expected_value and opportunity_units offered_price.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-stage3-ceiling"
            cust_id = "test-cust-stage3-ceiling"
            opp_id = "test-opp-stage3-ceiling"
            unit_id = "test-unit-ceiling-01"

            await self.conn.execute("DELETE FROM communications WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM viewings WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)
            await self.conn.execute("DELETE FROM units WHERE unit_id = $1", unit_id)

            # Insert Unit with asking price = 800,000 SAR
            await self.conn.execute(
                """
                INSERT INTO units (unit_id, unit_number, property_type_id, area_sqm, asking_price, status, created_at, updated_at)
                VALUES ($1, 'Unit-Ceiling-Test', 'property_type-10', 500.0, 800000.0, 'AVAILABLE', NOW(), NOW())
                """,
                unit_id
            )

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Tariq', 'Al-Hazmi', '+966511223344', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )

            # Lead with budget_max = 1,000,000 SAR (higher than unit price 800,000 SAR)
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, branch_id, status, priority, inquiry_type, budget_min, budget_max, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'QUALIFIED', 'HIGH', 'BUY', 500000, 1000000, NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.agent_id, self.branch_id
            )

            # Opportunity initialized with buyer's budget_max = 1,000,000 SAR
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'VIEWING', 1000000, NOW(), NOW())
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )

            # Insert scheduled viewing linked to unit_id (asking_price 800,000)
            v_id = "test-viewing-ceiling-01"
            await self.conn.execute(
                """
                INSERT INTO viewings (
                    viewing_id, opportunity_id, lead_id, unit_id, customer_id, agent_user_id,
                    scheduled_start, scheduled_end, status, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, NOW() - INTERVAL '1 hour', NOW(), 'SCHEDULED', NOW(), NOW())
                """,
                v_id, opp_id, lead_id, unit_id, cust_id, self.agent_id
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

            # 1. Attempt to complete with offer_amount = 1,000,000 (exceeds unit asking price 800,000)
            with self.assertRaises(ValueError) as ctx:
                await WorkflowEngine.complete_task_with_outcome(
                    conn=self.conn,
                    task_id=rep_task["task_id"],
                    user_id=self.agent_id,
                    outcome="INTERESTED",
                    notes="العميل يرغب بتقديم عرض بمبلغ 1,000,000 ريال",
                    viewing_data={"offer_amount": 1000000.0}
                )
            self.assertIn("لا يمكن أن يتجاوز العرض المالي المقترح", str(ctx.exception))
            self.assertIn("800,000.00", str(ctx.exception))

            # 2. Attempt with Stage 4 submit_commercial_offer directly: also blocked if offer > asking
            with self.assertRaises(ValueError) as ctx2:
                await WorkflowEngine.submit_commercial_offer(
                    conn=self.conn,
                    opportunity_id=opp_id,
                    unit_id=unit_id,
                    offer_amount=950000.0,
                    user_id=self.agent_id
                )
            self.assertIn("لا يمكن أن يتجاوز العرض المالي", str(ctx2.exception))

            # 3. Complete with valid offer_amount = 780,000 (<= 800,000 unit asking price)
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=rep_task["task_id"],
                user_id=self.agent_id,
                outcome="INTERESTED",
                notes="تم الاتفاق على تقديم عرض بقيمة 780,000 ريال",
                viewing_data={"offer_amount": 780000.0}
            )
            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["new_stage"], "NEGOTIATION")

            # Verify Opportunity expected_value was updated from 1,000,000 down to proposed 780,000
            opp_row = await self.conn.fetchrow("SELECT stage, expected_value FROM opportunities WHERE opportunity_id = $1", opp_id)
            self.assertEqual(opp_row["stage"], "NEGOTIATION")
            self.assertEqual(float(opp_row["expected_value"]), 780000.0)

            # Verify opportunity_units offered_price was updated to 780,000
            ou_row = await self.conn.fetchrow("SELECT offered_price FROM opportunity_units WHERE opportunity_id = $1 AND unit_id = $2", opp_id, unit_id)
            self.assertIsNotNone(ou_row)
            self.assertEqual(float(ou_row["offered_price"]), 780000.0)

        finally:
            await tr.rollback()

    async def test_stage3_viewing_report_interested_without_offer_caps_bloated_opp_value(self):
        """
        Rule: When TASK_VIEWING_REPORT is completed with INTERESTED without an explicit offer amount,
        if opportunities.expected_value was bloated by buyer's budget_max (1,000,000 SAR) and exceeds
        the unit asking price (800,000 SAR), it must be capped at the unit asking price (800,000 SAR).
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-stage3-cap"
            cust_id = "test-cust-stage3-cap"
            opp_id = "test-opp-stage3-cap"
            unit_id = "test-unit-cap-01"

            await self.conn.execute("DELETE FROM communications WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM viewings WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)
            await self.conn.execute("DELETE FROM units WHERE unit_id = $1", unit_id)

            await self.conn.execute(
                """
                INSERT INTO units (unit_id, unit_number, property_type_id, area_sqm, asking_price, status, created_at, updated_at)
                VALUES ($1, 'Unit-Cap-Test', 'property_type-10', 500.0, 800000.0, 'AVAILABLE', NOW(), NOW())
                """,
                unit_id
            )

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Sami', 'Al-Omari', '+966522334455', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )

            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, branch_id, status, priority, inquiry_type, budget_max, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'QUALIFIED', 'NORMAL', 'BUY', 1000000, NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.agent_id, self.branch_id
            )

            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'VIEWING', 1000000, NOW(), NOW())
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )

            await self.conn.execute(
                """
                INSERT INTO viewings (
                    viewing_id, opportunity_id, lead_id, unit_id, customer_id, agent_user_id,
                    scheduled_start, scheduled_end, status, created_at, updated_at
                ) VALUES ('viewing-cap-01', $1, $2, $3, $4, $5, NOW() - INTERVAL '1 hour', NOW(), 'SCHEDULED', NOW(), NOW())
                """,
                opp_id, lead_id, unit_id, cust_id, self.agent_id
            )

            rep_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_VIEWING_REPORT",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )

            # Complete with INTERESTED without passing offer_amount
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=rep_task["task_id"],
                user_id=self.agent_id,
                outcome="INTERESTED",
                notes="العميل مهتم جداً"
            )
            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["new_stage"], "NEGOTIATION")

            # Check that expected_value was capped to unit asking price (800,000 SAR)
            opp_row = await self.conn.fetchrow("SELECT expected_value FROM opportunities WHERE opportunity_id = $1", opp_id)
            self.assertEqual(float(opp_row["expected_value"]), 800000.0)

        finally:
            await tr.rollback()

    async def test_viewing_report_outcome_offer_requested(self):
        """
        Rule: When TASK_VIEWING_REPORT is completed with outcome 'OFFER_REQUESTED':
          - Opportunity advances to stage 'NEGOTIATION'
          - Stage 4 TASK_OFFER_SUBMIT is spawned with parent_task_id set to the viewing report task
          - Activity ACT_VIEWING_REPORT_SUBMITTED is recorded with outcome 'OFFER_REQUESTED'
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-offer-requested"
            cust_id = "test-cust-offer-requested"
            opp_id = "test-opp-offer-requested"

            await self.conn.execute("DELETE FROM viewings WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
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
                VALUES ($1, $2, $3, $4, 'VIEWING', 1500000, NOW(), NOW())
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )

            rep_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_VIEWING_REPORT",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )

            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=rep_task["task_id"],
                user_id=self.agent_id,
                outcome="OFFER_REQUESTED",
                notes="طلب تقديم عرض مالي رسمي"
            )

            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["new_stage"], "NEGOTIATION")
            self.assertIsNotNone(res.get("next_action"))
            self.assertEqual(res["next_action"]["type"], "OFFER_TASK_SPAWNED")

            spawned_task = res["next_action"]["task"]
            self.assertEqual(spawned_task["template_id"], "TASK_OFFER_SUBMIT")
            self.assertEqual(spawned_task["parent_task_id"], rep_task["task_id"])

            opp_stage = await self.conn.fetchval("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
            self.assertEqual(opp_stage, "NEGOTIATION")

        finally:
            await tr.rollback()

    async def test_viewing_report_outcome_requests_another_viewing(self):
        """
        Rule: When TASK_VIEWING_REPORT is completed with outcome 'REQUESTS_ANOTHER_VIEWING':
          - Opportunity retains stage 'VIEWING'
          - A new TASK_VIEWING_SCHEDULE task is automatically spawned with priority 'HIGH'
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-another-viewing"
            cust_id = "test-cust-another-viewing"
            opp_id = "test-opp-another-viewing"

            await self.conn.execute("DELETE FROM viewings WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Nasser', 'Al-Qahtani', '+966577889900', 'ACTIVE', NOW(), NOW())
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
                VALUES ($1, $2, $3, $4, 'VIEWING', 1500000, NOW(), NOW())
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )
            await self.conn.execute(
                """
                INSERT INTO viewings (
                    viewing_id, opportunity_id, lead_id, unit_id, customer_id, agent_user_id,
                    scheduled_start, scheduled_end, status, created_at, updated_at
                ) VALUES ('viewing-another-01', $1, $2, $3, $4, $5, NOW() - INTERVAL '1 hour', NOW(), 'SCHEDULED', NOW(), NOW())
                """,
                opp_id, lead_id, self.unit_id, cust_id, self.agent_id
            )

            rep_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_VIEWING_REPORT",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )

            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=rep_task["task_id"],
                user_id=self.agent_id,
                outcome="REQUESTS_ANOTHER_VIEWING",
                notes="العميل طلب زيارة معاينة أخرى لمراجعة تفاصيل العقار"
            )

            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["new_stage"], "VIEWING")
            self.assertEqual(res["business_transition"]["next_action"]["type"], "VIEWING_TASK_SPAWNED")

            # Verify new TASK_VIEWING_SCHEDULE was spawned
            next_task = await self.conn.fetchrow(
                "SELECT task_id, template_id, status, priority FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_VIEWING_SCHEDULE' AND status IN ('PENDING', 'OPEN')",
                opp_id
            )
            self.assertIsNotNone(next_task, "TASK_VIEWING_SCHEDULE must be auto-spawned for another viewing")
            self.assertEqual(next_task["priority"], "HIGH")

        finally:
            await tr.rollback()

    async def test_viewing_report_multi_unit_selection(self):
        """
        Rule: When multiple units are presented, selecting a specific unit in TASK_VIEWING_REPORT:
          - Promotes that unit to is_primary = TRUE in opportunity_units
          - Validates and enforces offer ceiling against that selected unit's price
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-multi-unit"
            cust_id = "test-cust-multi-unit"
            opp_id = "test-opp-multi-unit"
            unit_1 = "unit-test-m1"
            unit_2 = "unit-test-m2"

            await self.conn.execute("DELETE FROM viewings WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM units WHERE unit_id IN ($1, $2)", unit_1, unit_2)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

            await self.conn.execute(
                """
                INSERT INTO units (unit_id, unit_number, property_type_id, status, asking_price, created_at, updated_at)
                VALUES ($1, 'U-M1', 'property_type-8', 'AVAILABLE', 1200000, NOW(), NOW()),
                       ($2, 'U-M2', 'property_type-8', 'AVAILABLE', 750000, NOW(), NOW())
                """,
                unit_1, unit_2
            )

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Sami', 'Al-Harbi', '+966566112233', 'ACTIVE', NOW(), NOW())
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
                VALUES ($1, $2, $3, $4, 'VIEWING', 1200000, NOW(), NOW())
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )

            # Link both units: unit_1 as primary initially
            await self.conn.execute(
                """
                INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary)
                VALUES ($1, $2, TRUE), ($1, $3, FALSE)
                """,
                opp_id, unit_1, unit_2
            )

            await self.conn.execute(
                """
                INSERT INTO viewings (
                    viewing_id, opportunity_id, lead_id, unit_id, customer_id, agent_user_id,
                    scheduled_start, scheduled_end, status, created_at, updated_at
                ) VALUES ('viewing-multi-01', $1, $2, $3, $4, $5, NOW() - INTERVAL '1 hour', NOW(), 'SCHEDULED', NOW(), NOW())
                """,
                opp_id, lead_id, unit_1, cust_id, self.agent_id
            )

            rep_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_VIEWING_REPORT",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )

            # Completing task with unit_2 selected and offer exceeding unit_2 price (750k) must fail
            with self.assertRaises(ValueError):
                await WorkflowEngine.complete_task_with_outcome(
                    conn=self.conn,
                    task_id=rep_task["task_id"],
                    user_id=self.agent_id,
                    outcome="INTERESTED",
                    viewing_data={"unit_id": unit_2, "offer_amount": 900000}
                )

            # Completing task with unit_2 selected and valid offer (700k) succeeds
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=rep_task["task_id"],
                user_id=self.agent_id,
                outcome="INTERESTED",
                viewing_data={"unit_id": unit_2, "offer_amount": 700000}
            )
            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["new_stage"], "NEGOTIATION")

            # Check that unit_2 is now primary
            is_u2_prim = await self.conn.fetchval(
                "SELECT is_primary FROM opportunity_units WHERE opportunity_id = $1 AND unit_id = $2",
                opp_id, unit_2
            )
            self.assertTrue(is_u2_prim, "Selected unit_2 must be promoted to is_primary = TRUE")

            is_u1_prim = await self.conn.fetchval(
                "SELECT is_primary FROM opportunity_units WHERE opportunity_id = $1 AND unit_id = $2",
                opp_id, unit_1
            )
            self.assertFalse(is_u1_prim, "Previous unit_1 must no longer be primary")

            # Opportunity expected value updated to 700k
            exp_val = await self.conn.fetchval("SELECT expected_value FROM opportunities WHERE opportunity_id = $1", opp_id)
            self.assertEqual(float(exp_val), 700000.0)

        finally:
            await tr.rollback()

    async def test_stage3_offer_followup_counter_and_negotiate_concessions(self):
        """
        Verify that completing TASK_OFFER_FOLLOWUP with outcome 'COUNTER' (and synonyms):
        1. Does not raise ValueError('Unknown decision COUNTER')
        2. Sets offer status to 'COUNTERED'
        3. Advances/keeps opportunity stage in 'NEGOTIATION' with counter amount
        4. Auto-spawns TASK_SALE_NEGOTIATE_CONCESSIONS with HIGH priority
        5. Completing TASK_SALE_NEGOTIATE_CONCESSIONS with 'CONCESSION_AGREED' updates offer to 'ACCEPTED'
           and auto-spawns TASK_RESERVATION_VERIFY_AVAILABILITY (Stage F transition).
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            now_dt = datetime.now(timezone.utc)
            cust_id = "cust-test-counter-01"
            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, email, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'سعود', 'العتيبي', '0509998877', 'saud@test.com', 'ACTIVE', NOW(), NOW())
                ON CONFLICT (customer_id) DO NOTHING
                """,
                cust_id, self.org_id
            )

            lead_id = "lead-test-counter-01"
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, branch_id, assigned_user_id, status, inquiry_type, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'CONTACTED', 'BUY', NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.branch_id, self.agent_id
            )

            opp_id = "opp-test-counter-01"
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'OFFER', 2000000.0, NOW(), NOW())
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )

            await self.conn.execute(
                """
                INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary)
                VALUES ($1, $2, TRUE)
                """,
                opp_id, self.unit_id
            )

            offer_id = "offer-test-counter-01"
            await self.conn.execute(
                """
                INSERT INTO offers (offer_id, opportunity_id, unit_id, offer_amount, submitted_at, valid_until, status)
                VALUES ($1, $2, $3, 2000000.0, NOW(), NOW() + INTERVAL '2 days', 'SUBMITTED')
                """,
                offer_id, opp_id, self.unit_id
            )

            # Spawn TASK_OFFER_FOLLOWUP
            fup_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_OFFER_FOLLOWUP",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )
            self.assertIsNotNone(fup_task)

            # Complete TASK_OFFER_FOLLOWUP with outcome='COUNTER' and counter_amount=1850000.0
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=fup_task["task_id"],
                user_id=self.agent_id,
                outcome="COUNTER",
                notes="العميل يرغب بتقديم عرض مضاد بمبلغ 1,850,000 ريال",
                viewing_data={"offer_id": offer_id, "counter_amount": 1850000.0}
            )

            self.assertEqual(res["status"], "COMPLETED")
            offer_st = await self.conn.fetchval("SELECT status FROM offers WHERE offer_id = $1", offer_id)
            self.assertEqual(offer_st, "COUNTERED", "Offer status must be updated to COUNTERED")

            opp_st = await self.conn.fetchrow("SELECT stage, expected_value FROM opportunities WHERE opportunity_id = $1", opp_id)
            self.assertEqual(opp_st["stage"], "NEGOTIATION", "Opportunity stage must be NEGOTIATION")
            self.assertEqual(float(opp_st["expected_value"]), 1850000.0, "Opportunity expected value must match counter amount")

            # Check that TASK_SALE_NEGOTIATE_CONCESSIONS was auto-spawned
            concess_task = await self.conn.fetchrow(
                "SELECT * FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_SALE_NEGOTIATE_CONCESSIONS' ORDER BY created_at DESC LIMIT 1",
                opp_id
            )
            self.assertIsNotNone(concess_task, "TASK_SALE_NEGOTIATE_CONCESSIONS must be auto-spawned for COUNTER outcome")
            self.assertEqual(concess_task["priority"], "HIGH")

            # Complete TASK_SALE_NEGOTIATE_CONCESSIONS with CONCESSION_AGREED
            res_concess = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=concess_task["task_id"],
                user_id=self.agent_id,
                outcome="CONCESSION_AGREED",
                notes="تم الاتفاق مع المالك والمشتري على السعر 1,850,000 ريال",
                viewing_data={"negotiated_price": 1850000.0}
            )
            self.assertEqual(res_concess["status"], "COMPLETED")

            # Verify latest offer is now ACCEPTED
            offer_st2 = await self.conn.fetchval("SELECT status FROM offers WHERE offer_id = $1", offer_id)
            self.assertEqual(offer_st2, "ACCEPTED", "Offer status must be promoted to ACCEPTED after concession agreement")

            # Verify TASK_RESERVATION_VERIFY_AVAILABILITY was auto-spawned for Stage F
            reserv_task = await self.conn.fetchrow(
                "SELECT * FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_RESERVATION_VERIFY_AVAILABILITY' ORDER BY created_at DESC LIMIT 1",
                opp_id
            )
            self.assertIsNotNone(reserv_task, "TASK_RESERVATION_VERIFY_AVAILABILITY must be auto-spawned to transition to Stage F")
            self.assertEqual(reserv_task["priority"], "URGENT")

        finally:
            await tr.rollback()


if __name__ == "__main__":
    unittest.main()

