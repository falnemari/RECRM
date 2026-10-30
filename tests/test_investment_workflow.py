import unittest
from datetime import datetime, timezone, timedelta
import asyncpg
from app.config import settings
from app.services.workflow_engine import WorkflowEngine
from app.services.calculation_service import CalculationService


class TestInvestmentWorkflow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(settings.asyncpg_dsn)
        
        # Discover baseline entities
        self.org_id = await self.conn.fetchval("SELECT organization_id FROM organizations LIMIT 1") or "org-default"
        self.agent_id = await self.conn.fetchval(
            """
            SELECT u.user_id FROM users u 
            JOIN user_roles ur ON u.user_id = ur.user_id 
            JOIN roles r ON ur.role_id = r.role_id 
            WHERE r.role_code IN ('SALES_AGENT', 'SYS_ADMIN', 'LEASING_AGENT') AND u.status = 'ACTIVE' 
            LIMIT 1
            """
        ) or "user-51"

        # Create isolated test customer
        cust_row = await self.conn.fetchrow(
            """
            INSERT INTO customers (
                customer_id, organization_id, first_name, last_name, mobile, email, customer_type, created_at, updated_at
            ) VALUES (
                'cust-test-invest-auto', $1, 'Investor', 'Automated', '966599998888', 'investor.auto@test.com', 'INDIVIDUAL', NOW(), NOW()
            )
            ON CONFLICT (customer_id) DO UPDATE SET updated_at = NOW()
            RETURNING customer_id
            """,
            self.org_id
        )
        self.test_customer_id = cust_row["customer_id"]

        # Ensure at least 2 test units exist for comparison
        bld_id = await self.conn.fetchval("SELECT building_id FROM buildings LIMIT 1") or "bld-1"
        pt_id = await self.conn.fetchval("SELECT property_type_id FROM property_types LIMIT 1") or "APT"
        self.unit_a_id = "unit-invest-test-a"
        self.unit_b_id = "unit-invest-test-b"

        # Unit A
        await self.conn.execute(
            """
            INSERT INTO units (
                unit_id, building_id, unit_number, property_type_id, status, asking_price, rent_price, created_at, updated_at
            ) VALUES ($1, $2, 'INV-101', $3, 'AVAILABLE', 1000000.0, 80000.0, NOW(), NOW())
            ON CONFLICT (unit_id) DO UPDATE SET status = 'AVAILABLE', asking_price = 1000000.0, rent_price = 80000.0
            """,
            self.unit_a_id, bld_id, pt_id
        )

        # Unit B
        await self.conn.execute(
            """
            INSERT INTO units (
                unit_id, building_id, unit_number, property_type_id, status, asking_price, rent_price, created_at, updated_at
            ) VALUES ($1, $2, 'INV-102', $3, 'AVAILABLE', 1200000.0, 110000.0, NOW(), NOW())
            ON CONFLICT (unit_id) DO UPDATE SET status = 'AVAILABLE', asking_price = 1200000.0, rent_price = 110000.0
            """,
            self.unit_b_id, bld_id, pt_id
        )

    async def asyncTearDown(self):
        # Cleanup test entities
        await self.conn.execute("UPDATE units SET owner_customer_id = NULL WHERE owner_customer_id = $1", self.test_customer_id)
        await self.conn.execute("DELETE FROM document_access_log WHERE document_id IN (SELECT document_id FROM documents WHERE customer_id = $1 OR unit_id IN ($2, $3))", self.test_customer_id, self.unit_a_id, self.unit_b_id)
        await self.conn.execute("DELETE FROM documents WHERE customer_id = $1 OR unit_id IN ($2, $3)", self.test_customer_id, self.unit_a_id, self.unit_b_id)
        await self.conn.execute("DELETE FROM reservations WHERE customer_id = $1", self.test_customer_id)
        await self.conn.execute("DELETE FROM communications WHERE customer_id = $1 OR lead_id IN (SELECT lead_id FROM leads WHERE customer_id = $1)", self.test_customer_id)
        await self.conn.execute("DELETE FROM tasks WHERE customer_id = $1", self.test_customer_id)
        await self.conn.execute("DELETE FROM activities WHERE customer_id = $1", self.test_customer_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id IN (SELECT opportunity_id FROM opportunities WHERE customer_id = $1)", self.test_customer_id)
        await self.conn.execute("DELETE FROM opportunities WHERE customer_id = $1", self.test_customer_id)
        await self.conn.execute("DELETE FROM leads WHERE customer_id = $1", self.test_customer_id)
        await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", self.test_customer_id)
        await self.conn.execute("DELETE FROM units WHERE unit_id IN ($1, $2)", self.unit_a_id, self.unit_b_id)
        await self.conn.close()

    async def test_01_investment_lead_creation_and_first_contact(self):
        """
        1. Inbound lead with inquiry_type='INVESTMENT' routes to TASK_INVEST_LEAD_FIRST_CONTACT (30m SLA).
        """
        lead_id = "lead-test-invest-01"
        await self.conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, assigned_user_id,
                status, priority, inquiry_type, budget_min, budget_max, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'NEW', 'HIGH', 'INVESTMENT', 800000, 1500000, NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )

        res = await WorkflowEngine.on_lead_assigned(
            conn=self.conn,
            lead_id=lead_id,
            assigned_user_id=self.agent_id
        )

        self.assertIn("task", res)
        task = res["task"]
        self.assertEqual(task["template_id"], "TASK_INVEST_LEAD_FIRST_CONTACT")
        self.assertEqual(task["status"], "PENDING")
        self.assertEqual(task["priority"], "HIGH")

        # Verify SLA is within 30 minutes
        due_at = task["due_at"]
        now = datetime.now(timezone.utc)
        time_diff = (due_at - now).total_seconds() / 60
        self.assertGreater(time_diff, 20)
        self.assertLessEqual(time_diff, 31)

        # Cleanup
        await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_02_investment_lead_qualification_and_objectives_spawning(self):
        """
        2. First contact completed with QUALIFIED -> ACT_INVEST_LEAD_QUALIFIED + TASK_INVEST_CONFIRM_OBJECTIVES.
        """
        lead_id = "lead-test-invest-02"
        await self.conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, assigned_user_id,
                status, priority, inquiry_type, budget_min, budget_max, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'NEW', 'HIGH', 'INVESTMENT', 1000000, 2000000, NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )

        contact_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_LEAD_FIRST_CONTACT",
            lead_id=lead_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id,
            priority="HIGH"
        )

        # Complete first contact with QUALIFIED outcome
        res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=contact_task["task_id"],
            user_id=self.agent_id,
            outcome="QUALIFIED",
            qualification_data={"budget_min": 1000000, "budget_max": 2000000}
        )

        self.assertEqual(res["status"], "COMPLETED")
        self.assertIn("business_transition", res)
        b_trans = res["business_transition"]
        self.assertEqual(b_trans["status"], "QUALIFIED")

        # Verify ACT_INVEST_LEAD_QUALIFIED recorded
        act = await self.conn.fetchrow(
            "SELECT template_id, outcome FROM activities WHERE lead_id = $1 AND template_id = 'ACT_INVEST_LEAD_QUALIFIED'",
            lead_id
        )
        self.assertIsNotNone(act)
        self.assertEqual(act["outcome"], "QUALIFIED")

        # Verify TASK_INVEST_CONFIRM_OBJECTIVES spawned
        obj_task = await self.conn.fetchrow(
            "SELECT task_id, template_id, status FROM tasks WHERE lead_id = $1 AND template_id = 'TASK_INVEST_CONFIRM_OBJECTIVES'",
            lead_id
        )
        self.assertIsNotNone(obj_task)
        self.assertEqual(obj_task["status"], "PENDING")

        opp_id = b_trans["opportunity_id"]
        # Cleanup
        await self.conn.execute("DELETE FROM tasks WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM activities WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_03_confirm_objectives_to_return_comparison(self):
        """
        3. Confirming objectives records ACT_INVEST_OBJECTIVES_CONFIRMED and spawns TASK_INVEST_COMPARE_RETURNS.
        """
        lead_id = "lead-test-invest-03"
        await self.conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, assigned_user_id,
                status, priority, inquiry_type, budget_min, budget_max, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'INVESTMENT', 1000000, 2000000, NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        opp_id = "opp-test-invest-03"
        await self.conn.execute(
            """
            INSERT INTO opportunities (
                opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'QUALIFIED', 1500000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        obj_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_CONFIRM_OBJECTIVES",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        # Complete objectives confirmation with criteria
        res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=obj_task["task_id"],
            user_id=self.agent_id,
            outcome="OBJECTIVES_CONFIRMED",
            notes="المستثمر يبحث عن عائد صافٍ لا يقل عن 7.5% مع أفق زمني 5 سنوات.",
            viewing_data={
                "purchase_price": 1200000.0,
                "target_yield_percent": 8.0,
                "investment_horizon_years": 5,
                "risk_tolerance": "LOW",
                "investment_strategy": "RENTAL_INCOME",
                "unit_ids": [self.unit_a_id, self.unit_b_id]
            }
        )

        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["business_transition"]["type"], "INVEST_OBJECTIVES_CONFIRMED")

        # Verify activity logged
        act = await self.conn.fetchrow(
            "SELECT template_id, description FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_INVEST_OBJECTIVES_CONFIRMED'",
            opp_id
        )
        self.assertIsNotNone(act)
        self.assertIn("رأس المال المستهدف: 1,200,000.00", act["description"])
        self.assertIn("العائد المستهدف: 8.0%", act["description"])
        self.assertIn("الأفق الزمني: 5 سنوات", act["description"])

        # Verify candidate units added to opportunity_units
        u_count = await self.conn.fetchval(
            "SELECT count(*) FROM opportunity_units WHERE opportunity_id = $1", opp_id
        )
        self.assertEqual(u_count, 2)

        # Verify next task spawned is TASK_INVEST_COMPARE_RETURNS
        comp_task = await self.conn.fetchrow(
            "SELECT template_id, status FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_INVEST_COMPARE_RETURNS'",
            opp_id
        )
        self.assertIsNotNone(comp_task)
        self.assertEqual(comp_task["status"], "PENDING")

        # Cleanup
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_04_compare_property_returns_and_validation(self):
        """
        4. Return comparison computes metrics via CalculationService and spawns TASK_INVEST_VALIDATE_FINANCIALS.
        """
        lead_id = "lead-test-invest-04"
        opp_id = "opp-test-invest-04"
        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'INVESTMENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 1000000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        comp_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_COMPARE_RETURNS",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        # Complete task with selected unit_a
        res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=comp_task["task_id"],
            user_id=self.agent_id,
            outcome="RETURNS_COMPARED",
            viewing_data={
                "unit_id": self.unit_a_id,
                "purchase_price": 1000000.0,
                "monthly_rent_forecast": 8000.0,
                "annual_vacancy_allowance": 4800.0,
                "annual_operating_expenses": 5200.0,
                "acquisition_costs": 50000.0,
                "cash_invested": 1000000.0,
                "annual_pre_tax_cash_flow": 86000.0
            }
        )

        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["business_transition"]["type"], "INVEST_RETURNS_COMPARED")

        # Check calculated metrics
        metrics = res["business_transition"]["metrics"]
        self.assertEqual(metrics["gross_annual_rent"], 96000.0)
        self.assertEqual(metrics["effective_annual_rent"], 91200.0)
        self.assertEqual(metrics["net_operating_income"], 86000.0)
        self.assertEqual(metrics["gross_yield_percent"], 9.6)
        self.assertAlmostEqual(metrics["net_operating_yield_percent"], 8.19, places=2)

        # Verify primary unit updated in opportunity_units
        is_prim = await self.conn.fetchval(
            "SELECT is_primary FROM opportunity_units WHERE opportunity_id = $1 AND unit_id = $2",
            opp_id, self.unit_a_id
        )
        self.assertTrue(is_prim)

        # Verify next task spawned is TASK_INVEST_SCHEDULE_INSPECTION (Due Diligence Site Inspection)
        sched_task = await self.conn.fetchrow(
            "SELECT template_id, status FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_INVEST_SCHEDULE_INSPECTION'",
            opp_id
        )
        self.assertIsNotNone(sched_task)
        self.assertEqual(sched_task["status"], "PENDING")

        # Cleanup
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_05_financial_validation_and_non_destructive_rejection(self):
        """
        5. Financial validation divergence:
           - Outcome REJECTED -> Non-destructively rematches alternative properties via TASK_INVEST_COMPARE_RETURNS.
           - Outcome VALIDATED -> Spawns TASK_INVEST_PREPARE_ACQUISITION_OFFER (12h SLA).
        """
        lead_id = "lead-test-invest-05"
        opp_id = "opp-test-invest-05"
        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'INVESTMENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 1000000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        val_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_VALIDATE_FINANCIALS",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        # Part A: Test non-destructive rejection
        rej_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=val_task["task_id"],
            user_id=self.agent_id,
            outcome="REJECTED",
            notes="العميل تحفظ على مصاريف الصيانة التقديرية ويرغب في بديل آخر."
        )
        self.assertEqual(rej_res["business_transition"]["type"], "INVEST_REMATCH_SPAWNED")
        rematch_task = rej_res["business_transition"]["next_task"]
        self.assertEqual(rematch_task["template_id"], "TASK_INVEST_COMPARE_RETURNS")

        # Opportunity and Lead must remain active (not LOST!)
        opp_stage = await self.conn.fetchval("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
        self.assertEqual(opp_stage, "QUALIFIED")

        # Part B: Now complete the validation positively
        val_task2, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_VALIDATE_FINANCIALS",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )
        val_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=val_task2["task_id"],
            user_id=self.agent_id,
            outcome="VALIDATED",
            notes="تم اعتماد كافة الافتراضات المالية بدقة."
        )
        self.assertEqual(val_res["business_transition"]["type"], "INVEST_FINANCIALS_VALIDATED")
        offer_task = val_res["business_transition"]["next_task"]
        self.assertEqual(offer_task["template_id"], "TASK_INVEST_PREPARE_ACQUISITION_OFFER")

        # Cleanup
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_06_acquisition_offer_won_and_baseline_performance(self):
        """
        6. Offer acceptance transitions opportunity/lead to WON, reserves unit (AVAILABLE -> RESERVED),
           creates reservation record & reservation document, and spawns TASK_INVEST_BASELINE_PERFORMANCE.
           Baseline completion converts reservation (ACTIVE -> CONVERTED) and sells unit (RESERVED -> SOLD).
        """
        lead_id = "lead-test-invest-06"
        opp_id = "opp-test-invest-06"
        test_unit = self.unit_a_id

        # Ensure unit is initially AVAILABLE
        await self.conn.execute("UPDATE units SET status = 'AVAILABLE', owner_customer_id = NULL WHERE unit_id = $1", test_unit)

        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'INVESTMENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 1000000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
            VALUES ($1, $2, TRUE, 1000000)
            """,
            opp_id, test_unit
        )

        offer_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_PREPARE_ACQUISITION_OFFER",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        # Complete acquisition offer with OFFER_ACCEPTED
        res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=offer_task["task_id"],
            user_id=self.agent_id,
            outcome="OFFER_ACCEPTED",
            notes="تم توقيع العرض وقبول الشروط بنجاح."
        )

        self.assertEqual(res["business_transition"]["type"], "INVEST_ACQUISITION_WON")
        self.assertEqual(res["business_transition"]["unit_status"], "RESERVED")
        self.assertIsNotNone(res["business_transition"]["reservation_number"])

        # Verify Unit status transitioned to RESERVED
        unit_after_offer = await self.conn.fetchrow("SELECT status FROM units WHERE unit_id = $1", test_unit)
        self.assertEqual(unit_after_offer["status"], "RESERVED")

        # Verify Reservation created in DB with status ACTIVE
        res_row = await self.conn.fetchrow("SELECT * FROM reservations WHERE opportunity_id = $1 AND unit_id = $2", opp_id, test_unit)
        self.assertIsNotNone(res_row)
        self.assertEqual(res_row["status"], "ACTIVE")
        self.assertEqual(float(res_row["deposit_amount"]), 50000.0)  # 5% of 1,000,000

        # Verify Lead & Opportunity WON
        opp_db = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
        self.assertEqual(opp_db["stage"], "WON")
        lead_db = await self.conn.fetchrow("SELECT status FROM leads WHERE lead_id = $1", lead_id)
        self.assertEqual(lead_db["status"], "WON")

        # Verify next task is TASK_INVEST_BASELINE_PERFORMANCE
        base_task = res["business_transition"]["next_task"]
        self.assertEqual(base_task["template_id"], "TASK_INVEST_BASELINE_PERFORMANCE")

        # Complete Baseline Performance task
        base_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=base_task["task_id"],
            user_id=self.agent_id,
            outcome="BASELINE_ESTABLISHED",
            viewing_data={
                "purchase_price": 1000000.0,
                "monthly_rent_forecast": 8000.0,
                "annual_vacancy_allowance": 4800.0,
                "annual_operating_expenses": 5200.0,
                "cash_invested": 1000000.0
            }
        )

        self.assertEqual(base_res["business_transition"]["type"], "INVEST_BASELINE_ESTABLISHED")
        self.assertEqual(base_res["business_transition"]["unit_status"], "SOLD")

        # Verify Unit status transitioned to SOLD and ownership transferred
        unit_after_base = await self.conn.fetchrow("SELECT status, owner_customer_id FROM units WHERE unit_id = $1", test_unit)
        self.assertEqual(unit_after_base["status"], "SOLD")
        self.assertEqual(unit_after_base["owner_customer_id"], self.test_customer_id)

        # Verify Reservation converted to CONVERTED
        res_converted = await self.conn.fetchrow("SELECT status FROM reservations WHERE opportunity_id = $1 AND unit_id = $2", opp_id, test_unit)
        self.assertEqual(res_converted["status"], "CONVERTED")

        # Verify ACT_INVEST_BASELINE_ESTABLISHED recorded
        base_act = await self.conn.fetchrow(
            "SELECT template_id, outcome FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_INVEST_BASELINE_ESTABLISHED'",
            opp_id
        )
        self.assertIsNotNone(base_act)
        self.assertEqual(base_act["outcome"], "BASELINE_ESTABLISHED")

        # Verify recurring monitoring task TASK_INVEST_MONITOR_ACTUAL_RETURNS spawned
        mon_task = base_res["business_transition"]["next_task"]
        self.assertEqual(mon_task["template_id"], "TASK_INVEST_MONITOR_ACTUAL_RETURNS")

        # Cleanup
        await self.conn.execute("DELETE FROM document_access_log WHERE document_id IN (SELECT document_id FROM documents WHERE opportunity_id = $1 OR lead_id = $2)", opp_id, lead_id)
        await self.conn.execute("DELETE FROM documents WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM reservations WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
        await self.conn.execute("UPDATE units SET status = 'AVAILABLE', owner_customer_id = NULL WHERE unit_id = $1", test_unit)

    async def test_07_monitor_actual_returns_and_portfolio_review(self):
        """
        7. Actual returns monitoring compares actuals vs baseline and spawns portfolio review.
        """
        lead_id = "lead-test-invest-07"
        opp_id = "opp-test-invest-07"
        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'WON', 'NORMAL', 'INVESTMENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'WON', 1000000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        mon_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_MONITOR_ACTUAL_RETURNS",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        # Complete monitoring with actual collections
        mon_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=mon_task["task_id"],
            user_id=self.agent_id,
            outcome="MONITORED",
            viewing_data={
                "actual_rental_income": 98000.0,
                "actual_expenses": 5000.0,
                "monthly_rent_forecast": 8000.0  # Forecast 96,000 / year
            }
        )

        self.assertEqual(mon_res["business_transition"]["type"], "INVEST_RETURNS_MONITORED")
        var_data = mon_res["business_transition"]["variance"]
        self.assertEqual(var_data["variance"], 2000.0)
        self.assertAlmostEqual(var_data["variance_percent"], 2.08, places=2)
        self.assertTrue(var_data["is_favorable"])

        # Verify TASK_INVEST_PORTFOLIO_REVIEW spawned
        rev_task = mon_res["business_transition"]["next_task"]
        self.assertEqual(rev_task["template_id"], "TASK_INVEST_PORTFOLIO_REVIEW")

        # Complete portfolio review with HOLD recommendation
        rev_res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=rev_task["task_id"],
            user_id=self.agent_id,
            outcome="HOLD",
            notes="الأداء الاستثماري يفوق التوقعات، يوصى بالاحتفاظ بالعقار (HOLD)."
        )

        self.assertEqual(rev_res["business_transition"]["type"], "INVEST_PORTFOLIO_REVIEWED")
        self.assertEqual(rev_res["business_transition"]["recommendation"], "HOLD")

        # Cleanup
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_08_multi_opportunity_isolation(self):
        """
        8. Multi-Opportunity Isolation:
           A single customer can have both a rental pipeline opportunity and an investment opportunity
           simultaneously without deduplication blocking or state lock collisions.
        """
        # Create Rental Lead & Opp
        rental_lead_id = "lead-rent-multi-01"
        rental_opp_id = "opp-rent-multi-01"
        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'RENT', NOW(), NOW())
            """,
            rental_lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 50000, NOW(), NOW())
            """,
            rental_opp_id, rental_lead_id, self.test_customer_id, self.agent_id
        )

        # Create Investment Lead & Opp for the SAME customer
        invest_lead_id = "lead-invest-multi-02"
        invest_opp_id = "opp-invest-multi-02"
        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'INVESTMENT', NOW(), NOW())
            """,
            invest_lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 1500000, NOW(), NOW())
            """,
            invest_opp_id, invest_lead_id, self.test_customer_id, self.agent_id
        )

        # Spawn rental task
        r_task, r_is_new = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_RENT_MATCH_PROPERTIES",
            lead_id=rental_lead_id,
            opportunity_id=rental_opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )
        self.assertTrue(r_is_new)

        # Spawn investment task
        i_task, i_is_new = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_CONFIRM_OBJECTIVES",
            lead_id=invest_lead_id,
            opportunity_id=invest_opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )
        self.assertTrue(i_is_new)

        # Both tasks exist concurrently for the same customer
        self.assertNotEqual(r_task["task_id"], i_task["task_id"])
        self.assertEqual(r_task["opportunity_id"], rental_opp_id)
        self.assertEqual(i_task["opportunity_id"], invest_opp_id)

        # Complete rental task without affecting investment task
        await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=r_task["task_id"],
            user_id=self.agent_id,
            outcome="PROPERTIES_MATCHED",
            viewing_data={"unit_ids": [self.unit_a_id]}
        )

        i_task_check = await self.conn.fetchrow(
            "SELECT status FROM tasks WHERE task_id = $1", i_task["task_id"]
        )
        self.assertEqual(i_task_check["status"], "PENDING", "Investment task must remain unaffected by rental task completion")

        # Cleanup
        await self.conn.execute("DELETE FROM communications WHERE lead_id IN ($1, $2)", rental_lead_id, invest_lead_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", rental_opp_id, rental_lead_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", invest_opp_id, invest_lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", rental_opp_id, rental_lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", invest_opp_id, invest_lead_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id IN ($1, $2)", rental_opp_id, invest_opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id IN ($1, $2)", rental_lead_id, invest_lead_id)

    async def test_09_multi_unit_investment_comparison_and_document_generation(self):
        """
        9. Multi-unit (2 to 3 properties) investment returns comparison:
           - Evaluates 3 candidate units side-by-side with NOI, Cap Rate, Gross Yield, and CoC.
           - Sets designated primary recommended unit in opportunity_units.
           - Generates and archives official INVEST_COMPARATIVE_REPORT document.
           - Verifies printable HTML rendering with REGA compliance and benchmark matrix.
        """
        lead_id = "lead-test-multi-compare-09"
        opp_id = "opp-test-multi-compare-09"
        unit_c_id = "unit-invest-test-c"
        bld_id = await self.conn.fetchval("SELECT building_id FROM buildings LIMIT 1") or "bld-1"
        pt_id = await self.conn.fetchval("SELECT property_type_id FROM property_types LIMIT 1") or "APT"

        # Create Unit C
        await self.conn.execute(
            """
            INSERT INTO units (
                unit_id, building_id, unit_number, property_type_id, status, asking_price, rent_price, area_sqm, created_at, updated_at
            ) VALUES ($1, $2, 'INV-103', $3, 'AVAILABLE', 1500000.0, 135000.0, 320.0, NOW(), NOW())
            ON CONFLICT (unit_id) DO UPDATE SET status = 'AVAILABLE', asking_price = 1500000.0, rent_price = 135000.0
            """,
            unit_c_id, bld_id, pt_id
        )

        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'INVESTMENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 1200000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_COMPARE_RETURNS",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        compared_payload = [
            {
                "unit_id": self.unit_a_id,
                "unit_number": "INV-101",
                "property_type": "شقة استثمارية 1",
                "area_sqm": "220",
                "purchase_price": 1000000.0,
                "gross_annual_rent": 85000.0,
                "annual_vacancy_allowance": 4250.0,
                "annual_operating_expenses": 8500.0,
                "acquisition_costs": 25000.0,
                "cash_invested": 1000000.0,
                "is_primary": False
            },
            {
                "unit_id": self.unit_b_id,
                "unit_number": "INV-102",
                "property_type": "شقة استثمارية 2",
                "area_sqm": "260",
                "purchase_price": 1200000.0,
                "gross_annual_rent": 120000.0,
                "annual_vacancy_allowance": 6000.0,
                "annual_operating_expenses": 12000.0,
                "acquisition_costs": 30000.0,
                "cash_invested": 1200000.0,
                "is_primary": True  # Top recommended
            },
            {
                "unit_id": unit_c_id,
                "unit_number": "INV-103",
                "property_type": "شقة استثمارية 3",
                "area_sqm": "320",
                "purchase_price": 1500000.0,
                "gross_annual_rent": 135000.0,
                "annual_vacancy_allowance": 6750.0,
                "annual_operating_expenses": 13500.0,
                "acquisition_costs": 37500.0,
                "cash_invested": 1500000.0,
                "is_primary": False
            }
        ]

        res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=task["task_id"],
            user_id=self.agent_id,
            outcome="RETURNS_COMPARED",
            notes="تمت مقارنة 3 وحدات استثمارية والتوصية بالوحدة INV-102 لتحقيقها أعلى عائد تشغيلي صافي.",
            viewing_data={
                "compared_units": compared_payload,
                "recommendation_notes": "نوصي بالاستحواذ على الأصل INV-102 لتحقيقه عائد Cap Rate متميز واستقراراً نقدياً للمستثمر."
            }
        )

        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["business_transition"]["type"], "INVEST_RETURNS_COMPARED")
        self.assertEqual(len(res["business_transition"]["compared_units"]), 3)
        self.assertEqual(res["business_transition"]["primary_unit_id"], self.unit_b_id)
        
        doc_id = res["business_transition"]["document_id"]
        self.assertIsNotNone(doc_id)

        # Verify all 3 units inserted into opportunity_units with proper is_primary flags
        opp_units = await self.conn.fetch(
            "SELECT unit_id, is_primary, offered_price FROM opportunity_units WHERE opportunity_id = $1 ORDER BY unit_id",
            opp_id
        )
        self.assertEqual(len(opp_units), 3)
        unit_b_record = next(u for u in opp_units if u["unit_id"] == self.unit_b_id)
        unit_a_record = next(u for u in opp_units if u["unit_id"] == self.unit_a_id)
        unit_c_record = next(u for u in opp_units if u["unit_id"] == unit_c_id)

        self.assertTrue(unit_b_record["is_primary"])
        self.assertFalse(unit_a_record["is_primary"])
        self.assertFalse(unit_c_record["is_primary"])
        self.assertEqual(float(unit_b_record["offered_price"]), 1200000.0)

        # Verify document archived in documents table
        doc_row = await self.conn.fetchrow(
            """
            SELECT d.*, dt.code as document_type_code, dt.name as document_type_name
            FROM documents d
            LEFT JOIN document_types dt ON d.document_type_id = dt.document_type_id
            WHERE d.document_id = $1
            """,
            doc_id
        )
        self.assertIsNotNone(doc_row)
        self.assertEqual(doc_row["document_type_code"], "INVEST_COMPARATIVE_REPORT")

        # Test official HTML rendering
        from app.services.document_templates import render_document_html
        html_out = render_document_html(dict(doc_row))
        self.assertIn("تقرير المفاضلة والتحليل المالي المقارن للوحدات الاستثمارية", html_out)
        self.assertIn("INV-101", html_out)
        self.assertIn("INV-102", html_out)
        self.assertIn("INV-103", html_out)
        self.assertIn("الخيار الموصى به للاستحواذ", html_out)
        self.assertIn("Cap Rate", html_out)

        # Cleanup
        await self.conn.execute("DELETE FROM documents WHERE document_id = $1", doc_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)
        await self.conn.execute("DELETE FROM units WHERE unit_id = $1", unit_c_id)

    async def test_10_single_unit_feasibility_and_fast_track_offer(self):
        """
        10. Single unit feasibility & Fast-Track direct acquisition offer:
           - Handles single available investment unit (no multi-asset blocking).
           - Generates single-asset feasibility study document.
           - Outcome 'FAST_TRACK_OFFER' advances directly to TASK_INVEST_PREPARE_ACQUISITION_OFFER
             bypassing Due Diligence site inspection when asset is under warranty or pre-inspected.
        """
        lead_id = "lead-test-single-fast-10"
        opp_id = "opp-test-single-fast-10"

        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'INVESTMENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 1000000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_COMPARE_RETURNS",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        # Single unit payload
        single_payload = [
            {
                "unit_id": self.unit_a_id,
                "unit_number": "INV-101",
                "property_type": "مكتب استثماري مميز",
                "area_sqm": "180",
                "purchase_price": 950000.0,
                "gross_annual_rent": 90000.0,
                "annual_vacancy_allowance": 4500.0,
                "annual_operating_expenses": 7500.0,
                "acquisition_costs": 23750.0,
                "cash_invested": 950000.0,
                "is_primary": True
            }
        ]

        res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=task["task_id"],
            user_id=self.agent_id,
            outcome="FAST_TRACK_OFFER",
            notes="الوحدة جديدة بضمان المطور وتم استكمال دراسة الجدوى وتخطي الفحص الميداني مباشرة لتقديم عرض الاستحواذ.",
            viewing_data={
                "compared_units": single_payload,
                "recommendation_notes": "دراسة جدوى استثمارية لأصل منفرد واعد بعائد صافي يتجاوز 8%."
            }
        )

        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["business_transition"]["type"], "INVEST_RETURNS_COMPARED")
        self.assertEqual(len(res["business_transition"]["compared_units"]), 1)
        self.assertEqual(res["business_transition"]["primary_unit_id"], self.unit_a_id)

        # Verify fast-track next task is TASK_INVEST_PREPARE_ACQUISITION_OFFER
        next_task = res["business_transition"]["next_task"]
        self.assertIsNotNone(next_task)
        self.assertEqual(next_task["template_id"], "TASK_INVEST_PREPARE_ACQUISITION_OFFER")

        # Verify document title and rendering
        doc_id = res["business_transition"]["document_id"]
        doc_row = await self.conn.fetchrow(
            """
            SELECT d.*, dt.code as document_type_code, dt.name as document_type_name
            FROM documents d
            LEFT JOIN document_types dt ON d.document_type_id = dt.document_type_id
            WHERE d.document_id = $1
            """,
            doc_id
        )
        self.assertIsNotNone(doc_row)
        import json
        doc_meta = json.loads(doc_row["metadata"]) if isinstance(doc_row["metadata"], str) else (doc_row["metadata"] or {})
        self.assertIn("دراسة الجدوى والعوائد الاستثمارية للأصل", doc_meta.get("doc_title", ""))

        from app.services.document_templates import render_document_html
        html_out = render_document_html(dict(doc_row))
        self.assertIn("دراسة الجدوى والعوائد الاستثمارية للأصل العقاري", html_out)
        self.assertIn("INV-101", html_out)
        self.assertIn("الأصل المعتمد للاستحواذ", html_out)
        self.assertIn("Approved Investment Asset", html_out)

        # Cleanup
        await self.conn.execute("DELETE FROM documents WHERE document_id = $1", doc_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_11_compare_returns_with_100_percent_vacancy_new_building(self):
        """
        11. Verifies 100% vacancy scenario for brand new buildings:
            - Gross rent entered (pro-forma potential), vacancy = 100% of gross rent.
            - NOI is negative (carrying cost = -OPEX) without crashing.
            - Document renders properly and displays 'قيد التسكين (شغور)'.
        """
        lead_id = "lead-test-invest-11"
        opp_id = "opp-test-invest-11"
        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'INVESTMENT', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 2000000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )

        comp_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_COMPARE_RETURNS",
            lead_id=lead_id,
            opportunity_id=opp_id,
            customer_id=self.test_customer_id,
            assigned_user_id=self.agent_id
        )

        vacant_payload = [{
            "unit_id": self.unit_a_id,
            "unit_number": "NEW-BLD-01",
            "property_type": "مبنى تجاري جديد",
            "area_sqm": "850",
            "purchase_price": 2000000.0,
            "gross_annual_rent": 180000.0,
            "monthly_rent_forecast": 15000.0,
            "annual_vacancy_allowance": 180000.0, # 100% vacancy during lease-up
            "annual_operating_expenses": 12000.0, # Carrying OPEX
            "acquisition_costs": 150000.0,
            "cash_invested": 2150000.0,
            "net_operating_income": -12000.0,
            "cap_rate": -0.56,
            "gross_yield_percent": 9.0,
            "cash_on_cash_return_percent": 0.0,
            "payback_years": 0.0,
            "investment_notes": "مبنى جديد بالكامل - مرحلة التسكين والاستئجار الأولى.",
            "is_primary": True
        }]

        res = await WorkflowEngine.complete_task_with_outcome(
            conn=self.conn,
            task_id=comp_task["task_id"],
            user_id=self.agent_id,
            outcome="RETURNS_COMPARED",
            viewing_data={
                "unit_id": self.unit_a_id,
                "compared_units": vacant_payload,
                "recommendation_notes": "مبنى جديد واعد بعائد تشغيلي مستهدف 8.4% بعد اكتمال التسكين."
            }
        )

        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["business_transition"]["type"], "INVEST_RETURNS_COMPARED")

        # Verify document generated and rendered with lease-up status
        doc_id = res["business_transition"]["document_id"]
        doc_row = await self.conn.fetchrow(
            """
            SELECT d.*, dt.code as document_type_code, dt.name as document_type_name
            FROM documents d
            LEFT JOIN document_types dt ON d.document_type_id = dt.document_type_id
            WHERE d.document_id = $1
            """,
            doc_id
        )
        self.assertIsNotNone(doc_row)

        from app.services.document_templates import render_document_html
        html_out = render_document_html(dict(doc_row))
        self.assertIn("NEW-BLD-01", html_out)
        self.assertIn("قيد التسكين (شغور)", html_out)

        # Cleanup
        await self.conn.execute("DELETE FROM documents WHERE document_id = $1", doc_id)
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)


if __name__ == "__main__":
    unittest.main()
