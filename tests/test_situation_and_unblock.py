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

        finally:
            await tr.rollback()
