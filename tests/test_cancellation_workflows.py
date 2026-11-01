import os
import sys
import unittest
from datetime import datetime, timezone, timedelta, date
from uuid import uuid4

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

import asyncpg
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.database import get_next_id
from app.services.workflow_engine import WorkflowEngine


class TestCancellationWorkflows(unittest.IsolatedAsyncioTestCase):
    """
    Test suite for Task & Deal Cancellation Workflows:
    1. Warning confirmation dialogs (UI verified)
    2. Cancellation reason capturing & ACT_TASK_CANCELLED logging
    3. Direct deal cancellation when zero obligations exist
    4. Gated deal cancellation when financial/inventory obligations exist:
       - Transitions stage to UNDER_CANCELLATION
       - Automatically spawns TASK_DEAL_FINANCIAL_SETTLEMENT & TASK_DEAL_INVENTORY_RELEASE
       - Logs ACT_DEAL_CANCELLATION_INITIATED
    5. Gating enforcement: Blocks direct transition to CLOSED_LOST while remediation is pending
    6. Automatic deal finalization to CLOSED_LOST when all remediation tasks complete
    7. Cascading deal cancellation from task cancellation
    8. Strict database cleanup and hygiene
    """

    @classmethod
    def setUpClass(cls):
        cls.client_cm = TestClient(app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)

    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(settings.asyncpg_dsn)
        
        # Test trackers for clean teardown
        self.created_task_ids = []
        self.created_opp_ids = []
        self.created_lead_ids = []
        self.created_cust_ids = []
        self.created_unit_ids = []
        self.created_inv_ids = []
        self.created_res_ids = []

        # Reference user, organization, building, and property type
        self.user_id = await self.conn.fetchval(
            """
            SELECT u.user_id FROM users u
            JOIN user_roles ur ON u.user_id = ur.user_id
            JOIN roles r ON ur.role_id = r.role_id
            WHERE r.role_code IN ('SALES_AGENT', 'SYS_ADMIN') AND u.status = 'ACTIVE'
            LIMIT 1
            """
        ) or "user-51"

        self.org_id = await self.conn.fetchval("SELECT organization_id FROM organizations LIMIT 1") or "org-1"
        self.building_id = await self.conn.fetchval("SELECT building_id FROM buildings LIMIT 1")
        self.property_type_id = await self.conn.fetchval("SELECT property_type_id FROM property_types LIMIT 1")

        # Create isolated test customer
        cust_id = f"test-cust-{uuid4().hex[:8]}"
        await self.conn.execute(
            """
            INSERT INTO customers (customer_id, organization_id, first_name, last_name, mobile, email, customer_type, status)
            VALUES ($1, $2, 'TestCancel', 'Client', $3, $4, 'INDIVIDUAL', 'ACTIVE')
            """,
            cust_id, self.org_id, f"+9665{uuid4().hex[:8][:8]}", f"cancel_{uuid4().hex[:6]}@test.com"
        )
        self.cust_id = cust_id
        self.created_cust_ids.append(cust_id)

    async def asyncTearDown(self):
        # Clean up database records created during test in strict reverse order
        for opp_id in self.created_opp_ids:
            await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM invoices WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM reservations WHERE opportunity_id = $1", opp_id)
            await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)

        for task_id in self.created_task_ids:
            await self.conn.execute("DELETE FROM activities WHERE task_id = $1", task_id)
            await self.conn.execute("DELETE FROM tasks WHERE task_id = $1", task_id)

        for lead_id in self.created_lead_ids:
            await self.conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

        for res_id in self.created_res_ids:
            await self.conn.execute("DELETE FROM reservations WHERE reservation_id = $1", res_id)

        for inv_id in self.created_inv_ids:
            await self.conn.execute("DELETE FROM invoices WHERE invoice_id = $1", inv_id)

        for unit_id in self.created_unit_ids:
            await self.conn.execute("DELETE FROM unit_status_history WHERE unit_id = $1", unit_id)
            await self.conn.execute("DELETE FROM units WHERE unit_id = $1", unit_id)

        for cust_id in self.created_cust_ids:
            await self.conn.execute("DELETE FROM activities WHERE customer_id = $1", cust_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", cust_id)

        await self.conn.close()

    async def _create_test_lead_and_opportunity(self, stage: str = "QUALIFIED"):
        lead_id = f"test-lead-{uuid4().hex[:8]}"
        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, inquiry_type, status, priority, assigned_user_id)
            VALUES ($1, $2, $3, 'BUY', 'QUALIFIED', 'NORMAL', $4)
            """,
            lead_id, self.org_id, self.cust_id, self.user_id
        )
        self.created_lead_ids.append(lead_id)

        opp_id = f"test-opp-{uuid4().hex[:8]}"
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, customer_id, lead_id, assigned_user_id, stage, expected_value)
            VALUES ($1, $2, $3, $4, $5, 1200000)
            """,
            opp_id, self.cust_id, lead_id, self.user_id, stage
        )
        self.created_opp_ids.append(opp_id)
        return lead_id, opp_id

    async def _create_test_unit(self, status: str = "AVAILABLE"):
        unit_id = f"test-unit-{uuid4().hex[:8]}"
        await self.conn.execute(
            """
            INSERT INTO units (unit_id, building_id, property_type_id, unit_number, status, asking_price, rent_price)
            VALUES ($1, $2, $3, $4, $5, 1000000, 80000)
            """,
            unit_id, self.building_id, self.property_type_id, f"U-{uuid4().hex[:4]}", status
        )
        self.created_unit_ids.append(unit_id)
        return unit_id

    # -------------------------------------------------------------
    # 1. Task Cancellation
    # -------------------------------------------------------------
    async def test_task_cancellation_without_cascade(self):
        """Verify cancelling a standalone task marks it CANCELLED and logs ACT_TASK_CANCELLED."""
        lead_id, opp_id = await self._create_test_lead_and_opportunity()

        task_id = f"test-task-{uuid4().hex[:8]}"
        await self.conn.execute(
            """
            INSERT INTO tasks (task_id, opportunity_id, lead_id, customer_id, assigned_user_id, title, status, priority)
            VALUES ($1, $2, $3, $4, $5, 'Test follow-up call', 'OPEN', 'NORMAL')
            """,
            task_id, opp_id, lead_id, self.cust_id, self.user_id
        )
        self.created_task_ids.append(task_id)

        # Execute cancellation API
        res = self.client.post(
            f"/api/v1/tasks/{task_id}/cancel",
            json={
                "reason": "CLIENT_REQUEST",
                "notes": "العميل طلب تأجيل التواصل حالياً",
                "cascade_cancel_opportunity": False
            },
            headers={"X-User-ID": self.user_id}
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()["data"]
        self.assertEqual(data["task_id"], task_id)
        self.assertEqual(data["status"], "CANCELLED")

        # Verify DB state
        task_row = await self.conn.fetchrow("SELECT status FROM tasks WHERE task_id = $1", task_id)
        self.assertEqual(task_row["status"], "CANCELLED")

        # Verify activity log
        act = await self.conn.fetchrow(
            """
            SELECT a.*, at.code as type_code FROM activities a
            JOIN activity_types at ON a.activity_type_id = at.activity_type_id
            WHERE a.task_id = $1
            ORDER BY a.created_at DESC LIMIT 1
            """,
            task_id
        )
        self.assertIsNotNone(act)
        self.assertEqual(act["template_id"], "ACT_TASK_CANCELLED")
        self.assertIn("إلغاء المهمة", act["subject"])

    # -------------------------------------------------------------
    # 2. Deal Cancellation without Obligations (Direct Finalization)
    # -------------------------------------------------------------
    async def test_deal_cancellation_immediate_when_no_commitments(self):
        """Verify deal cancellation with zero commitments closes directly to CLOSED_LOST."""
        lead_id, opp_id = await self._create_test_lead_and_opportunity(stage="QUALIFIED")

        res = self.client.post(
            f"/api/v1/opportunities/{opp_id}/cancel",
            json={
                "reason": "PROPERTY_UNAVAILABLE",
                "notes": "لم تتوفر وحدة مناسبة للميزانية"
            },
            headers={"X-User-ID": self.user_id}
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()["data"]
        self.assertEqual(data["opportunity_id"], opp_id)
        self.assertEqual(data["stage"], "CLOSED_LOST")
        self.assertFalse(data["is_settlement_required"])
        self.assertEqual(len(data["remediation_tasks"]), 0)

        # Check DB opportunity and lead
        opp_row = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
        self.assertEqual(opp_row["stage"], "CLOSED_LOST")

        lead_row = await self.conn.fetchrow("SELECT status FROM leads WHERE lead_id = $1", lead_id)
        self.assertEqual(lead_row["status"], "LOST")

        # Check activity
        act = await self.conn.fetchrow(
            """
            SELECT * FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_DEAL_CANCELLATION_FINALIZED'
            """,
            opp_id
        )
        self.assertIsNotNone(act)

    # -------------------------------------------------------------
    # 3. Deal Cancellation with Commitments (Gated Remediation Workflow)
    # -------------------------------------------------------------
    async def test_deal_cancellation_gated_with_commitments(self):
        """
        Verify deal cancellation with active reservations and pending invoices:
        - Must NOT close immediately to CLOSED_LOST
        - Must transition to UNDER_CANCELLATION
        - Spawns TASK_DEAL_FINANCIAL_SETTLEMENT and TASK_DEAL_INVENTORY_RELEASE
        - Blocks premature transition to CLOSED_LOST
        - Auto-finalizes to CLOSED_LOST once remediation tasks are completed
        """
        lead_id, opp_id = await self._create_test_lead_and_opportunity(stage="NEGOTIATION")
        unit_id = await self._create_test_unit(status="RESERVED")

        # Link unit to opportunity
        await self.conn.execute(
            "INSERT INTO opportunity_units (opportunity_id, unit_id) VALUES ($1, $2)",
            opp_id, unit_id
        )

        # Create active reservation with deposit
        res_id = f"test-res-{uuid4().hex[:8]}"
        await self.conn.execute(
            """
            INSERT INTO reservations (reservation_id, opportunity_id, unit_id, customer_id, reservation_number, deposit_amount, status, reserved_at)
            VALUES ($1, $2, $3, $4, $5, 25000, 'ACTIVE', NOW())
            """,
            res_id, opp_id, unit_id, self.cust_id, f"RES-{uuid4().hex[:6]}"
        )
        self.created_res_ids.append(res_id)

        # Create unpaid invoice
        inv_id = f"test-inv-{uuid4().hex[:8]}"
        await self.conn.execute(
            """
            INSERT INTO invoices (
                invoice_id, opportunity_id, payer_customer_id, invoice_number, 
                invoice_type, payer_type, transaction_type, line_items,
                total_amount, subtotal, vat_rate, vat_amount, amount_paid, status
            )
            VALUES (
                $1, $2, $3, $4, 
                'TAX_INVOICE', 'CUSTOMER', 'SALE', '[]',
                25000, 21739.13, 15, 3260.87, 0, 'ISSUED'
            )
            """,
            inv_id, opp_id, self.cust_id, f"INV-{uuid4().hex[:6]}"
        )
        self.created_inv_ids.append(inv_id)

        # Create standard open operational task (should be cancelled upon initiation)
        op_task_id = f"test-op-task-{uuid4().hex[:8]}"
        await self.conn.execute(
            """
            INSERT INTO tasks (task_id, opportunity_id, lead_id, customer_id, assigned_user_id, title, status, priority)
            VALUES ($1, $2, $3, $4, $5, 'Prepare Sale Contract Draft', 'OPEN', 'HIGH')
            """,
            op_task_id, opp_id, lead_id, self.cust_id, self.user_id
        )
        self.created_task_ids.append(op_task_id)

        # Initiate deal cancellation
        res = self.client.post(
            f"/api/v1/opportunities/{opp_id}/cancel",
            json={
                "reason": "CLIENT_WITHDREW",
                "notes": "العميل يرغب في استرداد العربون وإلغاء الحجز"
            },
            headers={"X-User-ID": self.user_id}
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()["data"]
        self.assertEqual(data["opportunity_id"], opp_id)
        self.assertEqual(data["stage"], "UNDER_CANCELLATION")
        self.assertTrue(data["is_settlement_required"])
        self.assertEqual(len(data["remediation_tasks"]), 2)

        # Track remediation tasks for teardown
        fin_task_id = next(t["task_id"] for t in data["remediation_tasks"] if t["template_id"] == "TASK_DEAL_FINANCIAL_SETTLEMENT")
        inv_task_id = next(t["task_id"] for t in data["remediation_tasks"] if t["template_id"] == "TASK_DEAL_INVENTORY_RELEASE")
        self.created_task_ids.extend([fin_task_id, inv_task_id])

        # Verify operational task was cancelled
        op_row = await self.conn.fetchrow("SELECT status FROM tasks WHERE task_id = $1", op_task_id)
        self.assertEqual(op_row["status"], "CANCELLED")

        # Verify initiation activity logged
        init_act = await self.conn.fetchrow(
            "SELECT * FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_DEAL_CANCELLATION_INITIATED'",
            opp_id
        )
        self.assertIsNotNone(init_act)

        # ---------------------------------------------------------
        # Strict Gating Test: Attempting to directly PATCH to LOST must FAIL
        # ---------------------------------------------------------
        patch_res = self.client.patch(
            f"/api/v1/opportunities/{opp_id}",
            json={"stage": "LOST"},
            headers={"X-User-ID": self.user_id}
        )
        self.assertEqual(patch_res.status_code, 400)
        self.assertIn("مهام تسوية", patch_res.json()["detail"])

        # Opportunity must STILL be in UNDER_CANCELLATION
        opp_row = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
        self.assertEqual(opp_row["stage"], "UNDER_CANCELLATION")

        # ---------------------------------------------------------
        # Complete Inventory Release Task
        # ---------------------------------------------------------
        res_inv = self.client.post(
            f"/api/v1/tasks/{inv_task_id}/complete",
            json={"outcome": "UNIT_RELEASED", "notes": "تم فك الحجز وإعادة الوحدة للمخزون المتاح"},
            headers={"X-User-ID": self.user_id}
        )
        self.assertEqual(res_inv.status_code, 200, res_inv.text)

        # Check unit is now AVAILABLE and reservation is CANCELLED
        unit_row = await self.conn.fetchrow("SELECT status FROM units WHERE unit_id = $1", unit_id)
        self.assertEqual(unit_row["status"], "AVAILABLE")
        res_row = await self.conn.fetchrow("SELECT status FROM reservations WHERE reservation_id = $1", res_id)
        self.assertEqual(res_row["status"], "CANCELLED")

        # Opp must STILL be UNDER_CANCELLATION because financial task is not yet completed
        opp_row = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
        self.assertEqual(opp_row["stage"], "UNDER_CANCELLATION")

        # ---------------------------------------------------------
        # Complete Financial Settlement Task -> Triggers Auto-Finalization!
        # ---------------------------------------------------------
        res_fin = self.client.post(
            f"/api/v1/tasks/{fin_task_id}/complete",
            json={"outcome": "REFUNDED", "notes": "تمت تسوية الفاتورة وإجراء تسوية العربون المسترد"},
            headers={"X-User-ID": self.user_id}
        )
        self.assertEqual(res_fin.status_code, 200, res_fin.text)

        # Check invoice is now CANCELLED
        inv_row = await self.conn.fetchrow("SELECT status FROM invoices WHERE invoice_id = $1", inv_id)
        self.assertEqual(inv_row["status"], "CANCELLED")

        # GATING VERIFICATION: All remediation tasks completed -> Deal automatically CLOSED_LOST!
        opp_final = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
        self.assertEqual(opp_final["stage"], "CLOSED_LOST")

        lead_final = await self.conn.fetchrow("SELECT status FROM leads WHERE lead_id = $1", lead_id)
        self.assertEqual(lead_final["status"], "LOST")

        # Final activity recorded
        fin_act = await self.conn.fetchrow(
            "SELECT * FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_DEAL_CANCELLATION_FINALIZED'",
            opp_id
        )
        self.assertIsNotNone(fin_act)

    # -------------------------------------------------------------
    # 4. Cascading Deal Cancellation from Task
    # -------------------------------------------------------------
    async def test_task_cancellation_with_cascading_deal(self):
        """Verify cancelling a task with cascade_cancel_opportunity=True triggers deal cancellation."""
        lead_id, opp_id = await self._create_test_lead_and_opportunity(stage="QUALIFIED")

        task_id = f"test-cascade-task-{uuid4().hex[:8]}"
        await self.conn.execute(
            """
            INSERT INTO tasks (task_id, opportunity_id, lead_id, customer_id, assigned_user_id, title, status, priority)
            VALUES ($1, $2, $3, $4, $5, 'Client Discovery Call', 'OPEN', 'NORMAL')
            """,
            task_id, opp_id, lead_id, self.cust_id, self.user_id
        )
        self.created_task_ids.append(task_id)

        res = self.client.post(
            f"/api/v1/tasks/{task_id}/cancel",
            json={
                "reason": "CLIENT_REQUEST",
                "notes": "العميل طلب إلغاء المعاملة والصفقة بالكامل",
                "cascade_cancel_opportunity": True
            },
            headers={"X-User-ID": self.user_id}
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()["data"]
        self.assertEqual(data["task_id"], task_id)
        self.assertEqual(data["status"], "CANCELLED")
        self.assertIn("opportunity_cancellation", data)
        self.assertEqual(data["opportunity_cancellation"]["stage"], "CLOSED_LOST")

        # Verify DB
        opp_row = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
        self.assertEqual(opp_row["stage"], "CLOSED_LOST")


if __name__ == "__main__":
    unittest.main()
