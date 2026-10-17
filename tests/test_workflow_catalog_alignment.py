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


class TestWorkflowCatalogAlignment(unittest.IsolatedAsyncioTestCase):

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
        self.unit_id = await self.conn.fetchval("SELECT unit_id FROM units LIMIT 1")

    async def asyncTearDown(self):
        await self.conn.close()

    async def test_stage_a_explicit_assignment_activity(self):
        """
        Stage A Research Rule:
          Assignment must explicitly record ACT_LEAD_ASSIGNED.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-cat-a-01"
            cust_id = "test-cust-cat-a-01"

            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Adel', 'Al-Subaie', '+966500112233', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )

            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, branch_id, status, priority, inquiry_type, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'NEW', 'NORMAL', 'BUY', NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.branch_id
            )

            # Assign lead to agent
            res = await WorkflowEngine.on_lead_assigned(
                conn=self.conn,
                lead_id=lead_id,
                assigned_user_id=self.agent_id
            )
            self.assertEqual(res["status"], "assigned")

            # Verify ACT_LEAD_ASSIGNED activity
            act = await self.conn.fetchrow(
                "SELECT * FROM activities WHERE lead_id = $1 AND template_id = 'ACT_LEAD_ASSIGNED'",
                lead_id
            )
            self.assertIsNotNone(act, "ACT_LEAD_ASSIGNED must be explicitly logged upon assignment")
            self.assertEqual(act["outcome"], "ASSIGNED")

        finally:
            await tr.rollback()

    async def test_stage_b_max_retries_and_anti_loop_policy(self):
        """
        Stage B Research Rule:
          Do not create an endless chain of reminders.
          Maximum 3 retries policy:
            - Attempt 1: retry_count=1, follow-up spawned
            - Attempt 2: retry_count=2, follow-up spawned
            - Attempt 3: Terminal outcome UNREACHABLE, no 4th follow-up task spawned.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-cat-b-01"
            cust_id = "test-cust-cat-b-01"

            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Khaled', 'Al-Zahrani', '+966555110022', 'ACTIVE', NOW(), NOW())
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

            # Spawn first contact task
            t1, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_FIRST_CONTACT",
                lead_id=lead_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )

            # 1st attempt: NO_ANSWER
            res1 = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=t1["task_id"],
                user_id=self.agent_id,
                outcome="NO_ANSWER",
                notes="المحاولة الأولى: العميل لم يرد"
            )
            self.assertEqual(res1["business_transition"]["retry_count"], 1)
            t2 = res1["business_transition"]["followup_task"]
            self.assertIsNotNone(t2)

            # 2nd attempt: NO_ANSWER
            res2 = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=t2["task_id"],
                user_id=self.agent_id,
                outcome="NO_ANSWER",
                notes="المحاولة الثانية: الهاتف مشغول"
            )
            self.assertEqual(res2["business_transition"]["retry_count"], 2)
            t3 = res2["business_transition"]["followup_task"]
            self.assertIsNotNone(t3)

            # 3rd attempt: NO_ANSWER -> Must hit terminal status UNREACHABLE!
            res3 = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=t3["task_id"],
                user_id=self.agent_id,
                outcome="NO_ANSWER",
                notes="المحاولة الثالثة: لا يوجد رد نهائياً"
            )
            self.assertTrue(res3["business_transition"]["max_retries_exceeded"])
            self.assertEqual(res3["business_transition"]["new_status"], "UNREACHABLE")

            # Verify no 4th follow-up task was spawned
            open_tasks = await self.conn.fetch(
                "SELECT * FROM tasks WHERE lead_id = $1 AND status IN ('PENDING', 'OPEN')",
                lead_id
            )
            self.assertEqual(len(open_tasks), 0, "No endless loop: no tasks should remain open after 3 failed retries")

            # Verify lead status in DB
            lead_st = await self.conn.fetchval("SELECT status FROM leads WHERE lead_id = $1", lead_id)
            self.assertEqual(lead_st, "UNREACHABLE")

        finally:
            await tr.rollback()

    async def test_stage_b_callback_requested_and_invalid_contact(self):
        """
        Stage B Research Rule:
          - CALLBACK_REQUESTED: schedules follow-up at the exact requested datetime.
          - INVALID_CONTACT: immediately terminates lead as DISQUALIFIED.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-cat-b-02"
            cust_id = "test-cust-cat-b-02"

            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Saleh', 'Al-Mutairi', '+966555223344', 'ACTIVE', NOW(), NOW())
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

            t1, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_FIRST_CONTACT",
                lead_id=lead_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )

            # Test CALLBACK_REQUESTED
            callback_target = datetime.now(timezone.utc) + timedelta(days=2, hours=3)
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=t1["task_id"],
                user_id=self.agent_id,
                outcome="CALLBACK_REQUESTED",
                notes="العميل في اجتماع وطلب الاتصال بعد يومين",
                viewing_data={"callback_at": callback_target.isoformat()}
            )

            cb_task = res["business_transition"]["followup_task"]
            self.assertIsNotNone(cb_task)
            self.assertEqual(cb_task["priority"], "HIGH")

            # Complete that follow-up with INVALID_CONTACT
            res_inv = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=cb_task["task_id"],
                user_id=self.agent_id,
                outcome="INVALID_CONTACT",
                notes="الرقم مفصول وخارج الخدمة"
            )
            self.assertEqual(res_inv["business_transition"]["new_status"], "DISQUALIFIED")

            lead_st = await self.conn.fetchval("SELECT status FROM leads WHERE lead_id = $1", lead_id)
            self.assertEqual(lead_st, "DISQUALIFIED")

        finally:
            await tr.rollback()

    async def test_stage_c_property_matching_and_recommendations(self):
        """
        Stage C Research Rule:
          - Qualification spawns TASK_OPPORTUNITY_MATCH_PROPERTIES.
          - Presenting properties logs ACT_OPPORTUNITY_PROPERTIES_PRESENTED,
            COMM_OPPORTUNITY_RECOMMENDATIONS, and spawns TASK_VIEWING_SCHEDULE.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-cat-c-01"
            cust_id = "test-cust-cat-c-01"

            await self.conn.execute("DELETE FROM communications WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM opportunities WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Rayan', 'Al-Shehri', '+966544998877', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )

            # Lead without pre-selected unit
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, branch_id, status, priority, inquiry_type, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'CONTACTED', 'HIGH', 'BUY', NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.agent_id, self.branch_id
            )

            q_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_QUALIFY",
                lead_id=lead_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )

            # 1. Complete Qualification -> Spawns Stage C TASK_OPPORTUNITY_MATCH_PROPERTIES
            res_qual = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=q_task["task_id"],
                user_id=self.agent_id,
                outcome="QUALIFIED",
                notes="العميل مؤهل ولديه ميزانية 3 ملايين ريال",
                qualification_data={"budget_min": 2500000, "budget_max": 3000000}
            )

            opp_id = res_qual["business_transition"]["opportunity_id"]
            self.assertIsNotNone(opp_id)

            match_task = await self.conn.fetchrow(
                "SELECT * FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_OPPORTUNITY_MATCH_PROPERTIES' AND status IN ('PENDING', 'OPEN')",
                opp_id
            )
            self.assertIsNotNone(match_task, "Stage C TASK_OPPORTUNITY_MATCH_PROPERTIES must be spawned upon qualification")

            # 2. Complete Property Matching by presenting units
            res_pres = await WorkflowEngine.present_opportunity_properties(
                conn=self.conn,
                user_id=self.agent_id,
                opportunity_id=opp_id,
                unit_ids=[self.unit_id],
                notes="تم ترشيح فيلا مميزة في مشروع النخيل"
            )
            self.assertEqual(res_pres["status"], "PROPERTIES_PRESENTED")

            # Verify ACT_OPPORTUNITY_PROPERTIES_PRESENTED
            act = await self.conn.fetchrow(
                "SELECT * FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_OPPORTUNITY_PROPERTIES_PRESENTED'",
                opp_id
            )
            self.assertIsNotNone(act)

            # Verify COMM_OPPORTUNITY_RECOMMENDATIONS
            comm = await self.conn.fetchrow(
                "SELECT * FROM communications WHERE customer_id = $1 AND template_id = 'COMM_OPPORTUNITY_RECOMMENDATIONS'",
                cust_id
            )
            self.assertIsNotNone(comm)
            self.assertEqual(comm["channel"], "WHATSAPP")

            # Verify Stage D TASK_VIEWING_SCHEDULE was spawned
            view_task = await self.conn.fetchrow(
                "SELECT * FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_VIEWING_SCHEDULE' AND status IN ('PENDING', 'OPEN')",
                opp_id
            )
            self.assertIsNotNone(view_task, "Stage D TASK_VIEWING_SCHEDULE must be auto-spawned after presenting recommendations")

        finally:
            await tr.rollback()

    async def test_stage_d_viewing_no_show_and_auto_reschedule(self):
        """
        Stage D Research Rule:
          If customer does not attend (NO_SHOW), record no-show and auto-spawn
          rescheduling task TASK_VIEWING_RESCHEDULE.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-cat-d-01"
            cust_id = "test-cust-cat-d-01"
            opp_id = "test-opp-cat-d-01"

            await self.conn.execute("DELETE FROM viewings WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1 OR opportunity_id = $2", lead_id, opp_id)
            await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Waleed', 'Al-Qahtani', '+966533887766', 'ACTIVE', NOW(), NOW())
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
                VALUES ($1, $2, $3, $4, 'VIEWING', 1900000, NOW(), NOW())
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )

            # Insert scheduled viewing
            v_id = "test-viewing-cat-d-01"
            await self.conn.execute(
                """
                INSERT INTO viewings (
                    viewing_id, opportunity_id, lead_id, unit_id, customer_id, agent_user_id,
                    scheduled_start, scheduled_end, status, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, $5, $6, NOW() - INTERVAL '1 hour', NOW(), 'SCHEDULED', NOW(), NOW())
                """,
                v_id, opp_id, lead_id, self.unit_id, cust_id, self.agent_id
            )

            # Spawn inspection report task
            rep_task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_VIEWING_REPORT",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id,
                priority="HIGH"
            )

            # Agent completes report with NO_SHOW
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=rep_task["task_id"],
                user_id=self.agent_id,
                outcome="NO_SHOW",
                notes="انتظرت العميل 30 دقيقة أمام العقار ولم يحضر واعتذر لانشغاله الطارئ"
            )

            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["new_stage"], "VIEWING")

            # Check viewing status updated
            v_status = await self.conn.fetchval("SELECT status FROM viewings WHERE viewing_id = $1", v_id)
            self.assertEqual(v_status, "NO_SHOW")

            # Check TASK_VIEWING_RESCHEDULE auto-spawned
            resched_task = await self.conn.fetchrow(
                """
                SELECT * FROM tasks 
                WHERE opportunity_id = $1 AND template_id = 'TASK_VIEWING_RESCHEDULE' AND status IN ('PENDING', 'OPEN')
                """,
                opp_id
            )
            self.assertIsNotNone(resched_task, "TASK_VIEWING_RESCHEDULE must be auto-spawned when customer no-shows")
            self.assertEqual(resched_task["assigned_user_id"], self.agent_id)

        finally:
            await tr.rollback()


if __name__ == "__main__":
    unittest.main()
