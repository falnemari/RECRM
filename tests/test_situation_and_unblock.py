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


class TestSituationAndUnblock(unittest.IsolatedAsyncioTestCase):

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
        )

    async def asyncTearDown(self):
        await self.conn.close()

    async def test_lead_situation_stalled_detection_and_unblock(self):
        """
        Verify that a lead/deal at VIEWING stage with 0 pending tasks is flagged as is_stalled=True,
        provides recommended actions, and unblocks successfully.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            cust_id = "test-cust-sit-01"
            lead_id = "test-lead-sit-01"
            opp_id = "test-opp-sit-01"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Tariq', 'Al-Ghamdi', '+966550001122', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )

            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, inquiry_type, status, priority, assigned_user_id, created_at, updated_at)
                VALUES ($1, $2, $3, 'BUY', 'QUALIFIED', 'HIGH', $4, NOW(), NOW())
                """,
                lead_id, self.org_id, cust_id, self.agent_id
            )

            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'VIEWING', 500000.00, NOW(), NOW())
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )

            # Check situation - should be stalled since 0 pending tasks
            situation = await WorkflowEngine.get_entity_situation(self.conn, lead_id=lead_id)
            self.assertEqual(situation["lead_id"], lead_id)
            self.assertEqual(situation["opportunity_id"], opp_id)
            self.assertTrue(situation["is_stalled"])
            self.assertIn("VIEWING", situation["stalled_reason_ar"])
            self.assertTrue(any(a["action"] == "SPAWN_VIEWING_REPORT" for a in situation["recommended_actions"]))

            # Now unblock with SPAWN_VIEWING_REPORT
            unblock_res = await WorkflowEngine.unblock_entity_situation(
                conn=self.conn,
                lead_id=lead_id,
                action="SPAWN_VIEWING_REPORT",
                user_id=self.agent_id
            )
            self.assertIsNotNone(unblock_res["spawned_task"])
            self.assertEqual(unblock_res["spawned_task"]["template_id"], "TASK_VIEWING_REPORT")

            # Check situation again - should now be active (not stalled)
            updated_sit = await WorkflowEngine.get_entity_situation(self.conn, lead_id=lead_id)
            self.assertFalse(updated_sit["is_stalled"])
            self.assertEqual(len(updated_sit["pending_tasks"]), 1)
            self.assertEqual(updated_sit["pending_tasks"][0]["template_id"], "TASK_VIEWING_REPORT")
            # Verify UI backward compatibility aliases
            self.assertIn("due_date", updated_sit["pending_tasks"][0])
            self.assertIn("assignee_name", updated_sit["pending_tasks"][0])

        finally:
            await tr.rollback()

    async def test_multi_opportunity_lead_situation_isolation(self):
        """
        Verify that a customer having an existing active contract on Lead A does NOT leak
        into Lead B's situation (Article 1 & 4 Multi-Opportunity Isolation).
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            cust_id = "test-cust-multi-sit"
            lead_a = "test-lead-multi-a"
            opp_a = "test-opp-multi-a"
            res_a = "test-res-multi-a"
            con_a = "test-con-multi-a"
            lead_b = "test-lead-multi-b"

            # 1. Customer
            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Sultan', 'Al-Mutairi', '+966551122334', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )

            # 2. Lead A (Converted, Opp A, Reservation A, Contract A)
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, inquiry_type, status, priority, assigned_user_id, created_at, updated_at)
                VALUES ($1, $2, $3, 'BUY', 'CONVERTED', 'HIGH', $4, NOW(), NOW())
                """,
                lead_a, self.org_id, cust_id, self.agent_id
            )
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, $4, 'CLOSED_WON', 1200000.00, NOW(), NOW())
                """,
                opp_a, lead_a, cust_id, self.agent_id
            )
            unit_id = await self.conn.fetchval("SELECT unit_id FROM units LIMIT 1")
            await self.conn.execute(
                """
                INSERT INTO reservations (reservation_id, opportunity_id, unit_id, customer_id, reservation_number, status, deposit_amount, reserved_at)
                VALUES ($1, $2, $3, $4, 'RES-TEST-MULTI-A', 'ACTIVE', 50000.00, NOW())
                """,
                res_a, opp_a, unit_id, cust_id
            )
            await self.conn.execute(
                """
                INSERT INTO contracts (contract_id, reservation_id, contract_number, contract_type, status, contract_value, signed_at)
                VALUES ($1, $2, 'CON-TEST-MULTI-A', 'SALE', 'ACTIVE', 1200000.00, NOW())
                """,
                con_a, res_a
            )
            # Spawn a completed task for Lead A
            await self.conn.execute(
                """
                INSERT INTO tasks (task_id, lead_id, opportunity_id, customer_id, title, status, priority, created_at)
                VALUES ('task-multi-a-1', $1, $2, $3, 'Finalize Deal A', 'COMPLETED', 'HIGH', NOW())
                """,
                lead_a, opp_a, cust_id
            )

            # 3. Lead B (Brand new inquiry for the same customer, BUY, status=NEW)
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, inquiry_type, status, priority, assigned_user_id, created_at, updated_at)
                VALUES ($1, $2, $3, 'BUY', 'NEW', 'HIGH', $4, NOW(), NOW())
                """,
                lead_b, self.org_id, cust_id, self.agent_id
            )
            # Spawn one pending task specifically for Lead B
            await self.conn.execute(
                """
                INSERT INTO tasks (task_id, lead_id, customer_id, title, status, priority, created_at)
                VALUES ('task-multi-b-1', $1, $2, 'Contact Client for Inquiry B', 'PENDING', 'HIGH', NOW())
                """,
                lead_b, cust_id
            )

            # 4. Check Lead B Situation - Must NEVER see Lead A's contract or tasks
            sit_b = await WorkflowEngine.get_entity_situation(self.conn, lead_id=lead_b)
            self.assertEqual(sit_b["lead_id"], lead_b)
            self.assertIsNone(sit_b["opportunity_id"])
            self.assertEqual(sit_b["current_stage"], "LEAD (NEW)")
            self.assertFalse(sit_b["is_stalled"])
            self.assertEqual(sit_b["contracts_count"], 0)
            self.assertEqual(sit_b["reservations_count"], 0)
            self.assertEqual(sit_b["completed_tasks_count"], 0)
            self.assertEqual(len(sit_b["pending_tasks"]), 1)
            self.assertEqual(sit_b["pending_tasks"][0]["task_id"], "task-multi-b-1")

            # 5. Check Lead A Situation - Must see its own contract and completed task
            sit_a = await WorkflowEngine.get_entity_situation(self.conn, lead_id=lead_a)
            self.assertEqual(sit_a["lead_id"], lead_a)
            self.assertEqual(sit_a["opportunity_id"], opp_a)
            self.assertEqual(sit_a["current_stage"], "CONTRACT (ACTIVE)")
            self.assertEqual(sit_a["contracts_count"], 1)
            self.assertEqual(sit_a["reservations_count"], 1)
            self.assertEqual(sit_a["completed_tasks_count"], 1)

        finally:
            await tr.rollback()

    async def test_unblock_first_contact_routing_by_inquiry_type(self):
        """
        Verify that SPAWN_FIRST_CONTACT unblock action selects the correct task template
        based on the lead's inquiry_type (RENT -> TASK_RENT_LEAD_FIRST_CONTACT, BUY -> TASK_LEAD_FIRST_CONTACT).
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            cust_id = "test-cust-unblock-types"
            lead_rent = "test-lead-rent-unblock"
            lead_invest = "test-lead-invest-unblock"
            lead_buy = "test-lead-buy-unblock"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Nasser', 'Al-Otaibi', '+966559988776', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )

            # RENT Lead
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, inquiry_type, status, priority, assigned_user_id, created_at, updated_at)
                VALUES ($1, $2, $3, 'RENT', 'NEW', 'HIGH', $4, NOW(), NOW())
                """,
                lead_rent, self.org_id, cust_id, self.agent_id
            )
            res_rent = await WorkflowEngine.unblock_entity_situation(
                conn=self.conn, lead_id=lead_rent, action="SPAWN_FIRST_CONTACT", user_id=self.agent_id
            )
            self.assertEqual(res_rent["spawned_task"]["template_id"], "TASK_RENT_LEAD_FIRST_CONTACT")

            # INVESTMENT Lead
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, inquiry_type, status, priority, assigned_user_id, created_at, updated_at)
                VALUES ($1, $2, $3, 'INVESTMENT', 'NEW', 'HIGH', $4, NOW(), NOW())
                """,
                lead_invest, self.org_id, cust_id, self.agent_id
            )
            res_invest = await WorkflowEngine.unblock_entity_situation(
                conn=self.conn, lead_id=lead_invest, action="SPAWN_FIRST_CONTACT", user_id=self.agent_id
            )
            self.assertEqual(res_invest["spawned_task"]["template_id"], "TASK_INVEST_LEAD_FIRST_CONTACT")

            # BUY Lead
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, inquiry_type, status, priority, assigned_user_id, created_at, updated_at)
                VALUES ($1, $2, $3, 'BUY', 'NEW', 'HIGH', $4, NOW(), NOW())
                """,
                lead_buy, self.org_id, cust_id, self.agent_id
            )
            res_buy = await WorkflowEngine.unblock_entity_situation(
                conn=self.conn, lead_id=lead_buy, action="SPAWN_FIRST_CONTACT", user_id=self.agent_id
            )
            self.assertEqual(res_buy["spawned_task"]["template_id"], "TASK_LEAD_FIRST_CONTACT")

        finally:
            await tr.rollback()
