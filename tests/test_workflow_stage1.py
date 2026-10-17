import unittest
import asyncio
import os
import sys
from datetime import datetime, timezone

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

import asyncpg
from app.config import settings
from app.services.workflow_engine import WorkflowEngine, normalize_saudi_phone


class TestWorkflowStage1(unittest.IsolatedAsyncioTestCase):

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

    async def asyncTearDown(self):
        await self.conn.close()

    def test_phone_normalization(self):
        self.assertEqual(normalize_saudi_phone("0500558590"), "+966500558590")
        self.assertEqual(normalize_saudi_phone("500558590"), "+966500558590")
        self.assertEqual(normalize_saudi_phone("966500558590"), "+966500558590")
        self.assertEqual(normalize_saudi_phone("+966500558590"), "+966500558590")
        self.assertEqual(normalize_saudi_phone("050-055-8590"), "+966500558590")

    async def test_stage1_flow_deduplication_and_task_spawning(self):
        test_mobile = "0599112233"
        test_norm_mobile = "+966599112233"

        tr = self.conn.transaction()
        await tr.start()
        try:
            # 1. Clean up any previous test records
            await self.conn.execute("DELETE FROM customers WHERE mobile IN ($1, $2)", test_mobile, test_norm_mobile)

            # 2. First Customer Intake -> Should create new customer
            cust1_id, is_dup1, info1 = await WorkflowEngine.find_or_create_customer(
                conn=self.conn,
                org_id=self.org_id,
                first_name="Sultan",
                last_name="Al-Otaibi",
                mobile=test_mobile,
                email="sultan@example.com"
            )
            self.assertFalse(is_dup1, "First customer must NOT be marked duplicate")
            self.assertTrue(cust1_id.startswith("customer-"))

            # 3. Second Intake with same phone (variant format) -> Must detect duplicate and REUSE cust1_id
            cust2_id, is_dup2, info2 = await WorkflowEngine.find_or_create_customer(
                conn=self.conn,
                org_id=self.org_id,
                first_name="Sultan",
                last_name="Al-Otaibi Alternate",
                mobile="+966599112233"
            )
            self.assertTrue(is_dup2, "Second customer with same mobile MUST be flagged as duplicate")
            self.assertEqual(cust1_id, cust2_id, "Must reuse existing customer_id, not create a new one")

            # 4. Create Lead and verify Task & Activity generation
            lead_id = "test-lead-stage1-001"
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'NEW', 'HIGH', 'BUY', NOW(), NOW())
                """,
                lead_id, self.org_id, cust1_id, self.agent_id
            )

            # Spawn TASK_LEAD_FIRST_CONTACT
            task1, is_new1 = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_FIRST_CONTACT",
                lead_id=lead_id,
                customer_id=cust1_id,
                assigned_user_id=self.agent_id,
                priority="HIGH"
            )
            self.assertTrue(is_new1, "First task spawn must be marked as new")
            self.assertEqual(task1["template_id"], "TASK_LEAD_FIRST_CONTACT")
            self.assertEqual(task1["status"], "PENDING")

            # Anti-Duplication check: Calling spawn again MUST NOT create a duplicate open task
            task2, is_new2 = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_FIRST_CONTACT",
                lead_id=lead_id,
                customer_id=cust1_id,
                assigned_user_id=self.agent_id,
                priority="HIGH"
            )
            self.assertFalse(is_new2, "Subsequent spawn for same lead & template must be flagged as duplicate")
            self.assertEqual(task1["task_id"], task2["task_id"], "Must return existing task_id")

            # Verify Lead status is still strictly 'NEW' (not marked contacted on task generation)
            lead_status = await self.conn.fetchval("SELECT status FROM leads WHERE lead_id = $1", lead_id)
            self.assertEqual(lead_status, "NEW", "Lead must remain NEW until actual contact is logged")

            # Complete task with outcome 'CONNECTED'
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=task1["task_id"],
                user_id=self.agent_id,
                outcome="CONNECTED",
                notes="Client answered and requested villa viewing in Riyadh"
            )

            self.assertEqual(res["status"], "COMPLETED")
            self.assertEqual(res["activity"]["outcome"], "CONNECTED")
            self.assertEqual(res["business_transition"]["new_status"], "CONTACTED")

            # Verify lead is now CONTACTED in DB and qualification task spawned
            updated_lead = await self.conn.fetchrow("SELECT status, first_contact_at FROM leads WHERE lead_id = $1", lead_id)
            self.assertEqual(updated_lead["status"], "CONTACTED")
            self.assertIsNotNone(updated_lead["first_contact_at"])

            qual_task = await self.conn.fetchrow(
                "SELECT task_id, template_id, status FROM tasks WHERE lead_id = $1 AND template_id = 'TASK_LEAD_QUALIFY'",
                lead_id
            )
            self.assertIsNotNone(qual_task, "Qualification task must be automatically spawned after connection")
        finally:
            await tr.rollback()

    async def test_no_answer_triggers_followup(self):
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-stage1-002"
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
                VALUES ($1, $2, $3, 'NEW', 'NORMAL', 'RENT', NOW(), NOW())
                """,
                lead_id, self.org_id, self.agent_id
            )

            task, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_FIRST_CONTACT",
                lead_id=lead_id,
                assigned_user_id=self.agent_id
            )

            # Complete with NO_ANSWER
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=task["task_id"],
                user_id=self.agent_id,
                outcome="NO_ANSWER",
                notes="No answer, line was busy"
            )

            # Lead must REMAIN 'NEW'
            lead_status = await self.conn.fetchval("SELECT status FROM leads WHERE lead_id = $1", lead_id)
            self.assertEqual(lead_status, "NEW", "Lead must remain NEW if outcome was NO_ANSWER")

            # Follow-up task must be spawned
            followup = await self.conn.fetchrow(
                "SELECT task_id, template_id, status FROM tasks WHERE lead_id = $1 AND template_id = 'TASK_LEAD_FOLLOWUP'",
                lead_id
            )
            self.assertIsNotNone(followup, "Follow-up task must be scheduled when client does not answer")
        finally:
            await tr.rollback()

    async def test_deduplication_by_email(self):
        tr = self.conn.transaction()
        await tr.start()
        try:
            # 1. Create first customer with specific email
            cust1_id, is_dup1, _ = await WorkflowEngine.find_or_create_customer(
                conn=self.conn,
                org_id=self.org_id,
                first_name="Fahad",
                last_name="Al-Harbi",
                mobile="0511223344",
                email="fahad.harbi@example.com"
            )
            self.assertFalse(is_dup1)

            # 2. Intake with DIFFERENT phone, but SAME email (different case and trailing space)
            cust2_id, is_dup2, info2 = await WorkflowEngine.find_or_create_customer(
                conn=self.conn,
                org_id=self.org_id,
                first_name="Fahad",
                last_name="Al-Harbi Alternate",
                mobile="0588990011",
                email="  FAHAD.HARBI@EXAMPLE.COM "
            )
            self.assertTrue(is_dup2, "Customer with matching email MUST be detected as duplicate")
            self.assertEqual(cust1_id, cust2_id, "Must reuse original customer_id")
            self.assertIn("Email", info2.get("matched_by", ""))
        finally:
            await tr.rollback()

    async def test_deduplication_by_national_id(self):
        tr = self.conn.transaction()
        await tr.start()
        try:
            test_nid = "1999888777"
            # 1. Create first customer with national ID
            cust1_id, is_dup1, _ = await WorkflowEngine.find_or_create_customer(
                conn=self.conn,
                org_id=self.org_id,
                first_name="Nasser",
                last_name="Al-Qahtani",
                mobile="0522334455",
                email="nasser@example.com",
                national_id=test_nid
            )
            self.assertFalse(is_dup1)

            # 2. Intake with DIFFERENT phone, DIFFERENT email, but SAME national ID with dashes
            cust2_id, is_dup2, info2 = await WorkflowEngine.find_or_create_customer(
                conn=self.conn,
                org_id=self.org_id,
                first_name="Nasser",
                last_name="Al-Qahtani Alternate",
                mobile="0577665544",
                email="different.email@example.com",
                national_id="199-988-8777"
            )
            self.assertTrue(is_dup2, "Customer with matching National ID MUST be detected as duplicate")
            self.assertEqual(cust1_id, cust2_id, "Must reuse original customer_id")
            self.assertIn("National ID", info2.get("matched_by", ""))
        finally:
            await tr.rollback()


    async def test_auto_enrichment_on_duplicate(self):
        tr = self.conn.transaction()
        await tr.start()
        try:
            # 1. Create customer with ONLY mobile number
            cust1_id, is_dup1, _ = await WorkflowEngine.find_or_create_customer(
                conn=self.conn,
                org_id=self.org_id,
                first_name="Turki",
                last_name="Al-Shehri",
                mobile="0533445566"
            )
            self.assertFalse(is_dup1)

            # Check DB: email and national_id_hash are null
            row_before = await self.conn.fetchrow("SELECT email, national_id_hash FROM customers WHERE customer_id = $1", cust1_id)
            self.assertIsNone(row_before["email"])
            self.assertIsNone(row_before["national_id_hash"])

            # 2. Re-intake with SAME mobile, but now providing new email and national ID
            cust2_id, is_dup2, _ = await WorkflowEngine.find_or_create_customer(
                conn=self.conn,
                org_id=self.org_id,
                first_name="Turki",
                last_name="Al-Shehri",
                mobile="0533445566",
                email="turki.shehri@example.com",
                national_id="1044556677"
            )
            self.assertTrue(is_dup2)
            self.assertEqual(cust1_id, cust2_id)

            # Check DB: customer record was auto-enriched with the new email and national_id_hash
            row_after = await self.conn.fetchrow("SELECT email, national_id_hash FROM customers WHERE customer_id = $1", cust1_id)
            self.assertEqual(row_after["email"], "turki.shehri@example.com")
            self.assertIsNotNone(row_after["national_id_hash"])
        finally:
            await tr.rollback()

    async def test_unassigned_lead_routed_to_branch_manager_by_preferred_city(self):
        tr = self.conn.transaction()
        await tr.start()
        try:
            # 1. Create intake customer
            cust_id, _, _ = await WorkflowEngine.find_or_create_customer(
                conn=self.conn,
                org_id=self.org_id,
                first_name="Rakan",
                last_name="Al-Ghamdi",
                mobile="0544556677",
                email="rakan.ghamdi@test.sa"
            )

            # 2. Find branch & manager for Jeddah (city-7)
            branch_id, manager_id = await WorkflowEngine.find_branch_and_manager_for_city(self.conn, city_id="city-7")
            self.assertEqual(branch_id, "branch-5", "Jeddah city must map to Jeddah Branch (branch-5)")
            self.assertEqual(manager_id, "user-9", "Jeddah Branch Manager must be user-9 (Ahmad Alnemari)")

            # 3. Simulate unassigned lead creation
            lead_id = "test-lead-unassigned-001"
            await self.conn.execute(
                """
                INSERT INTO leads (
                    lead_id, organization_id, customer_id, branch_id, assigned_user_id,
                    preferred_city_id, status, priority, inquiry_type, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, NULL, 'city-7', 'NEW', 'HIGH', 'BUY', NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, branch_id
            )

            # Spawn TASK_LEAD_ASSIGN for the Branch Manager
            assign_task, is_new = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_LEAD_ASSIGN",
                lead_id=lead_id,
                customer_id=cust_id,
                assigned_user_id=manager_id,
                priority="HIGH"
            )
            self.assertTrue(is_new)
            self.assertEqual(assign_task["template_id"], "TASK_LEAD_ASSIGN")
            self.assertEqual(assign_task["assigned_user_id"], manager_id)
            self.assertEqual(assign_task["status"], "PENDING")

            # Record ACT_LEAD_ROUTED
            await WorkflowEngine.record_activity_from_template(
                conn=self.conn,
                template_id="ACT_LEAD_ROUTED",
                user_id=manager_id,
                customer_id=cust_id,
                lead_id=lead_id,
                outcome="ROUTED",
                notes="طلب وارد بدون وسيط. تم توجيهه لمدير الفرع."
            )

            routed_act = await self.conn.fetchrow(
                "SELECT * FROM activities WHERE lead_id = $1 AND template_id = 'ACT_LEAD_ROUTED'",
                lead_id
            )
            self.assertIsNotNone(routed_act)

            # 4. Manager assigns an agent: on_lead_assigned
            res = await WorkflowEngine.on_lead_assigned(
                conn=self.conn,
                lead_id=lead_id,
                assigned_user_id=self.agent_id,
                assigner_user_id=manager_id
            )
            self.assertEqual(res["status"], "assigned")

            # Verify TASK_LEAD_ASSIGN is COMPLETED
            completed_assign_task = await self.conn.fetchrow(
                "SELECT status, completed_at FROM tasks WHERE task_id = $1",
                assign_task["task_id"]
            )
            self.assertEqual(completed_assign_task["status"], "COMPLETED")
            self.assertIsNotNone(completed_assign_task["completed_at"])

            # Verify TASK_LEAD_FIRST_CONTACT is now SPAWNED for the assigned sales agent
            first_contact_task = await self.conn.fetchrow(
                "SELECT task_id, template_id, assigned_user_id, status FROM tasks WHERE lead_id = $1 AND template_id = 'TASK_LEAD_FIRST_CONTACT'",
                lead_id
            )
            self.assertIsNotNone(first_contact_task)
            self.assertEqual(first_contact_task["assigned_user_id"], self.agent_id)
            self.assertEqual(first_contact_task["status"], "PENDING")

            # Verify lead has first_contact_due_at set
            updated_lead = await self.conn.fetchrow("SELECT first_contact_due_at FROM leads WHERE lead_id = $1", lead_id)
            self.assertIsNotNone(updated_lead["first_contact_due_at"])
        finally:
            await tr.rollback()

    async def test_unassigned_lead_fallback_to_main_branch(self):
        tr = self.conn.transaction()
        await tr.start()
        try:
            # If city_id is None, must fallback to Riyadh Main Branch (branch-3)
            branch_id, manager_id = await WorkflowEngine.find_branch_and_manager_for_city(self.conn, city_id=None)
            self.assertEqual(branch_id, "branch-3")
            self.assertEqual(manager_id, "user-1", "Main Branch Manager is user-1 (Tariq Al-Otaibi)")
        finally:
            await tr.rollback()


if __name__ == "__main__":
    unittest.main()



