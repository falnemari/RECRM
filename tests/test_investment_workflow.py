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
        6. Offer acceptance transitions opportunity/lead to WON and spawns TASK_INVEST_BASELINE_PERFORMANCE.
        """
        lead_id = "lead-test-invest-06"
        opp_id = "opp-test-invest-06"
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
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

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


if __name__ == "__main__":
    unittest.main()
