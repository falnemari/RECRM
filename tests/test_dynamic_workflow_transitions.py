import unittest
import asyncio
import os
import sys
import json
from datetime import datetime, timezone, timedelta

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

import asyncpg
from app.config import settings
from app.services.workflow_engine import WorkflowEngine


class TestDynamicWorkflowTransitions(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(settings.asyncpg_dsn)
        self.org_id = await self.conn.fetchval("SELECT organization_id FROM organizations LIMIT 1")
        self.agent_id = await self.conn.fetchval(
            """
            SELECT u.user_id FROM users u 
            JOIN user_roles ur ON u.user_id = ur.user_id 
            JOIN roles r ON ur.role_id = r.role_id 
            WHERE r.role_code IN ('INVESTMENT_ADVISOR', 'SALES_AGENT', 'SYS_ADMIN') AND u.status = 'ACTIVE' 
            LIMIT 1
            """
        )
        self.branch_id = await self.conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", self.agent_id) or "branch-3"

    async def asyncTearDown(self):
        await self.conn.close()

    async def test_resolve_next_task_template_happy_path(self):
        """
        Verify that resolve_next_task_template returns default next_template_id
        when no outcome is supplied or outcome has no special override.
        """
        # Investment linear sequence: Objectives -> Compare Returns -> Inspection Schedule -> Inspection Report
        next_1 = await WorkflowEngine.resolve_next_task_template(
            self.conn, "TASK_INVEST_CONFIRM_OBJECTIVES"
        )
        self.assertEqual(next_1, "TASK_INVEST_COMPARE_RETURNS")

        next_2 = await WorkflowEngine.resolve_next_task_template(
            self.conn, "TASK_INVEST_COMPARE_RETURNS"
        )
        self.assertEqual(next_2, "TASK_INVEST_SCHEDULE_INSPECTION")

        next_3 = await WorkflowEngine.resolve_next_task_template(
            self.conn, "TASK_INVEST_SCHEDULE_INSPECTION"
        )
        self.assertEqual(next_3, "TASK_INVEST_INSPECTION_REPORT")

    async def test_resolve_next_task_template_branching_outcomes(self):
        """
        Verify outcome-based transitions (e.g. Recommended vs Rejected).
        """
        # TASK_INVEST_INSPECTION_REPORT:
        # RECOMMENDED -> TASK_INVEST_VALIDATE_FINANCIALS
        # REJECTED -> TASK_INVEST_COMPARE_RETURNS
        rec_next = await WorkflowEngine.resolve_next_task_template(
            self.conn, "TASK_INVEST_INSPECTION_REPORT", outcome="RECOMMENDED"
        )
        self.assertEqual(rec_next, "TASK_INVEST_VALIDATE_FINANCIALS")

        rej_next = await WorkflowEngine.resolve_next_task_template(
            self.conn, "TASK_INVEST_INSPECTION_REPORT", outcome="REJECTED"
        )
        self.assertEqual(rej_next, "TASK_INVEST_COMPARE_RETURNS")

        # TASK_INVEST_VALIDATE_FINANCIALS:
        # DISCOUNT_REQUIRED -> TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT
        disc_next = await WorkflowEngine.resolve_next_task_template(
            self.conn, "TASK_INVEST_VALIDATE_FINANCIALS", outcome="DISCOUNT_REQUIRED"
        )
        self.assertEqual(disc_next, "TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT")

    async def test_terminal_and_consultative_tasks_have_no_successor(self):
        """
        Verify that Terminal tasks and Standalone Consultative tasks return None.
        (مهام ليس لها مهام بعدها)
        """
        # Terminal tasks
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_CONTRACT_HANDOVER")
        )
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_RENT_COLLECTION_MONITORING")
        )
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_LEAD_COMPLETE_INFO")
        )
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_COLLECT_SAUDI_FEES")
        )
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_COMMISSION_SETTLEMENT")
        )

        # Standalone Consultative Tasks
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_INVEST_LEGAL_TITLE_AUDIT")
        )
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_INVEST_TAX_ZAKAT_ADVISORY")
        )
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_INVEST_TAQEEM_VALUATION")
        )
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_INVEST_ENVIRONMENTAL_SOIL_CHECK")
        )
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_SALE_TITLE_DEED_VERIFICATION")
        )
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_SALE_MORTGAGE_PREQUALIFICATION")
        )
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_SALE_DEFECTS_DISCLOSURE")
        )
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_RENT_TENANT_SCREENING_CREDIT")
        )
        self.assertIsNone(
            await WorkflowEngine.resolve_next_task_template(self.conn, "TASK_RENT_COMMERCIAL_LICENSING_CHECK")
        )

    async def test_dynamic_reconfiguration_without_code_changes(self):
        """
        Verify zero-downtime reconfiguration:
        Modifying next_template_id in database immediately alters the workflow progression.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-dyn-01"
            cust_id = "test-cust-dyn-01"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status)
                VALUES ($1, $2, 'INDIVIDUAL', 'Nasser', 'Al-Otaibi', '+966555998877', 'ACTIVE')
                """,
                cust_id, self.org_id
            )
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, branch_id, status, inquiry_type)
                VALUES ($1, $2, $3, $4, $5, 'QUALIFIED', 'INVESTMENT')
                """,
                lead_id, self.org_id, cust_id, self.agent_id, self.branch_id
            )
            opp_id = "opp-dyn-01"
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value)
                VALUES ($1, $2, $3, $4, 'PROPOSAL', 5000000)
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )

            # Spawn TASK_INVEST_CONFIRM_OBJECTIVES
            t_obj, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_INVEST_CONFIRM_OBJECTIVES",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )

            # Normal DB transition is TASK_INVEST_COMPARE_RETURNS
            res_normal = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=t_obj["task_id"],
                user_id=self.agent_id,
                outcome="CONFIRMED",
                notes="Normal transition"
            )
            self.assertEqual(res_normal["business_transition"]["next_task"]["template_id"], "TASK_INVEST_COMPARE_RETURNS")

            # Now, simulate an admin updating the workflow template in DB:
            # Route TASK_INVEST_CONFIRM_OBJECTIVES directly to TASK_INVEST_SCHEDULE_INSPECTION
            await self.conn.execute(
                """
                UPDATE workflow_templates
                SET next_template_id = 'TASK_INVEST_SCHEDULE_INSPECTION'
                WHERE template_id = 'TASK_INVEST_CONFIRM_OBJECTIVES'
                """
            )

            # Spawn a second objectives task to test new transition
            t_obj2, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_INVEST_CONFIRM_OBJECTIVES",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )

            res_updated = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=t_obj2["task_id"],
                user_id=self.agent_id,
                outcome="CONFIRMED",
                notes="Custom transition from DB update"
            )
            # The engine immediately picked up the updated DB rule without code modification!
            self.assertEqual(res_updated["business_transition"]["next_task"]["template_id"], "TASK_INVEST_SCHEDULE_INSPECTION")

        finally:
            await tr.rollback()

    async def test_negotiate_price_discount_updates_ddr_and_unlocks_baseline(self):
        """
        Verify that completing TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT:
        1. Updates investment_due_diligence_reports (purchase_price_sar, cash_invested_sar, gross_annual_rent_sar, opex, noi, cap_rate).
        2. Updates opportunities.expected_value and opportunity_units.offered_price.
        3. Unlocks existing pending TASK_INVEST_BASELINE_PERFORMANCE to OPEN.
        4. When TASK_INVEST_BASELINE_PERFORMANCE executes, it inherits the updated figures.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-neg-01"
            cust_id = "test-cust-neg-01"
            opp_id = "test-opp-neg-01"
            unit_id = await self.conn.fetchval("SELECT unit_id FROM units LIMIT 1")

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status)
                VALUES ($1, $2, 'INDIVIDUAL', 'Sultan', 'Al-Ghamdi', '+966555112233', 'ACTIVE')
                """,
                cust_id, self.org_id
            )
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, branch_id, status, inquiry_type, priority)
                VALUES ($1, $2, $3, $4, $5, 'QUALIFIED', 'INVESTMENT', 'HIGH')
                """,
                lead_id, self.org_id, cust_id, self.agent_id, self.branch_id
            )
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value)
                VALUES ($1, $2, $3, $4, 'NEGOTIATION', 12000000)
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )
            if unit_id:
                await self.conn.execute(
                    """
                    INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
                    VALUES ($1, $2, TRUE, 12000000)
                    """,
                    opp_id, unit_id
                )

            # Insert Due Diligence Report
            ddr_id = "test-ddr-neg-01"
            await self.conn.execute(
                """
                INSERT INTO investment_due_diligence_reports (
                    report_id, opportunity_id, unit_id, inspector_user_id,
                    purchase_price_sar, gross_annual_rent_sar, operating_expenses_opex_sar,
                    net_operating_income_noi_sar, estimated_capex_sar, suggested_price_adjustment_sar,
                    cash_invested_sar, structural_condition, saudi_building_code_compliant
                ) VALUES (
                    $1, $2, $3, $4,
                    12000000, 600000, 60000, 510000, 228000, 228000,
                    12000000, 'GOOD', TRUE
                )
                """,
                ddr_id, opp_id, unit_id, self.agent_id
            )

            # Create downstream baseline task in PENDING status
            t_base, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_INVEST_BASELINE_PERFORMANCE",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )
            await self.conn.execute("UPDATE tasks SET status = 'PENDING' WHERE task_id = $1", t_base["task_id"])

            # Create negotiation task in OPEN status
            t_neg, _ = await WorkflowEngine.spawn_task_from_template(
                conn=self.conn,
                template_id="TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT",
                lead_id=lead_id,
                opportunity_id=opp_id,
                customer_id=cust_id,
                assigned_user_id=self.agent_id
            )

            # Complete negotiation task with DISCOUNT_ACCEPTED
            neg_payload = {
                "approved_acquisition_price": 11772000.0,
                "equity_cash_invested": 11772000.0,
                "gross_annual_rent": 600000.0,
                "operating_expenses_opex": 60000.0,
                "target_net_operating_income_noi": 510000.0
            }
            res = await WorkflowEngine.complete_task_with_outcome(
                conn=self.conn,
                task_id=t_neg["task_id"],
                user_id=self.agent_id,
                outcome="DISCOUNT_ACCEPTED",
                viewing_data=neg_payload,
                notes="Seller accepted 228,000 SAR discount."
            )

            # Verify negotiation task is COMPLETED
            t_neg_db = await self.conn.fetchrow("SELECT status FROM tasks WHERE task_id = $1", t_neg["task_id"])
            self.assertEqual(t_neg_db["status"], "COMPLETED")

            # Verify due diligence report was updated with negotiated values
            rep = await self.conn.fetchrow("SELECT * FROM investment_due_diligence_reports WHERE report_id = $1", ddr_id)
            self.assertEqual(float(rep["purchase_price_sar"]), 11772000.0)
            self.assertEqual(float(rep["cash_invested_sar"]), 11772000.0)
            self.assertEqual(float(rep["gross_annual_rent_sar"]), 600000.0)
            self.assertEqual(float(rep["net_operating_income_noi_sar"]), 510000.0)
            self.assertAlmostEqual(float(rep["cap_rate_percent"]), round(510000 / 11772000 * 100, 2))

            # Verify opportunity and opportunity_units updated
            opp_db = await self.conn.fetchrow("SELECT expected_value FROM opportunities WHERE opportunity_id = $1", opp_id)
            self.assertEqual(float(opp_db["expected_value"]), 11772000.0)
            if unit_id:
                u_db = await self.conn.fetchrow("SELECT offered_price FROM opportunity_units WHERE opportunity_id = $1", opp_id)
                self.assertEqual(float(u_db["offered_price"]), 11772000.0)

            # Verify baseline task was unlocked to OPEN
            t_base_db = await self.conn.fetchrow("SELECT status FROM tasks WHERE task_id = $1", t_base["task_id"])
            self.assertEqual(t_base_db["status"], "OPEN")

        finally:
            await tr.rollback()

    async def test_task_creation_inherits_lead_priority_and_bidirectional_sync(self):
        """
        Verify API POST /api/v1/tasks inherits lead priority and auto-links lead/opp.
        """
        from app.routers.communications import create_task
        from app.schemas.communications import TaskCreateIn

        tr = self.conn.transaction()
        await tr.start()
        try:
            lead_id = "test-lead-pri-01"
            cust_id = "test-cust-pri-01"
            opp_id = "test-opp-pri-01"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status)
                VALUES ($1, $2, 'INDIVIDUAL', 'Tariq', 'Al-Shehri', '+966555334455', 'ACTIVE')
                """,
                cust_id, self.org_id
            )
            # Create Lead with URGENT priority
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, branch_id, status, inquiry_type, priority)
                VALUES ($1, $2, $3, $4, $5, 'QUALIFIED', 'INVESTMENT', 'URGENT')
                """,
                lead_id, self.org_id, cust_id, self.agent_id, self.branch_id
            )
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value)
                VALUES ($1, $2, $3, $4, 'PROPOSAL', 4000000)
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )

            # Case 1: Create task passing only lead_id (no opportunity_id, default priority NORMAL)
            # Should auto-resolve opportunity_id and strictly inherit URGENT priority from lead
            task_payload = TaskCreateIn(
                title="Ad-Hoc Negotiation Check",
                template_id="TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT",
                lead_id=lead_id,
                due_at=datetime.now(timezone.utc) + timedelta(days=1),
                priority="NORMAL"  # User/frontend submitted normal, should be overridden by URGENT
            )
            task_res = await create_task(task_payload, conn=self.conn)
            self.assertEqual(task_res.data.priority, "URGENT")
            self.assertEqual(task_res.data.opportunity_id, opp_id)

            # Case 2: Create task passing only opportunity_id (no lead_id)
            # Should auto-resolve lead_id and inherit URGENT priority from lead
            task_payload_opp = TaskCreateIn(
                title="Baseline Setup",
                template_id="TASK_INVEST_BASELINE_PERFORMANCE",
                opportunity_id=opp_id,
                due_at=datetime.now(timezone.utc) + timedelta(days=1),
                priority="NORMAL"
            )
            task_res_opp = await create_task(task_payload_opp, conn=self.conn)
            self.assertEqual(task_res_opp.data.priority, "URGENT")
            self.assertEqual(task_res_opp.data.lead_id, lead_id)

        finally:
            await tr.rollback()

