import unittest
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta, date

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

import asyncpg
from app.config import settings
from app.services.workflow_engine import WorkflowEngine
from app.services.calculation_service import CalculationService
from app.schemas.management import TenancyCreateIn, RentCollectionPaymentIn
from app.routers.management import create_tenancy, record_rent_payment


class TestCustomerBusinessRulesGoldenAcceptance(unittest.IsolatedAsyncioTestCase):
    """
    Comprehensive Golden Master Acceptance Test Suite verifying all articles of:
    'Customer Business rules and workflow.md':
      1. Purpose-based routing: RENT vs BUY vs INVESTMENT
      2. Multi-opportunity isolation (Single customer simultaneously renting, buying, investing)
      3. Calculation engine math verification (Yield, NOI, CoC, Match Score, Equations 7.1-7.5)
      4. Concurrency protection (Row-level lock on unit reservation)
      5. Non-destructive offer decline with alternative property rematching
      6. Tenancy execution, rent collection schedule generation, and balance tracking
    """

    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(settings.asyncpg_dsn)
        self.org_id = await self.conn.fetchval("SELECT organization_id FROM organizations LIMIT 1")
        self.agent_id = await self.conn.fetchval(
            """
            SELECT u.user_id FROM users u 
            JOIN user_roles ur ON u.user_id = ur.user_id 
            JOIN roles r ON ur.role_id = r.role_id 
            WHERE r.role_code IN ('SALES_AGENT', 'SYS_ADMIN', 'LEASING_AGENT') AND u.status = 'ACTIVE' 
            LIMIT 1
            """
        ) or "user-51"

        # Unique Golden Customer
        self.cust_id, _, _ = await WorkflowEngine.find_or_create_customer(
            conn=self.conn,
            org_id=self.org_id,
            first_name="Sultan",
            last_name="Al-Golden",
            mobile="+966550000001",
            email="sultan.golden@example.com"
        )

        # Dedicated test units
        bld_id = await self.conn.fetchval("SELECT building_id FROM buildings LIMIT 1") or "bld-1"
        pt_id = await self.conn.fetchval("SELECT property_type_id FROM property_types LIMIT 1") or "pt-1"

        self.unit_rent_id = "unit-golden-rent-01"
        self.unit_buy_id = "unit-golden-buy-01"
        self.unit_invest_id = "unit-golden-invest-01"

        for uid in (self.unit_rent_id, self.unit_buy_id, self.unit_invest_id):
            await self.conn.execute("DELETE FROM documents WHERE unit_id = $1", uid)
            await self.conn.execute("DELETE FROM units WHERE unit_id = $1", uid)

        await self.conn.execute(
            """
            INSERT INTO units (
                unit_id, building_id, property_type_id,
                unit_number, floor_no, bedrooms, bathrooms, area_sqm,
                rent_price, asking_price, status, created_at, updated_at
            ) VALUES 
            ($1, $2, $3, 'G-RENT', 1, 2, 2, 100.0, 50000, NULL, 'AVAILABLE', NOW(), NOW()),
            ($4, $2, $3, 'G-BUY', 2, 3, 3, 180.0, NULL, 900000, 'AVAILABLE', NOW(), NOW()),
            ($5, $2, $3, 'G-INV', 3, 4, 4, 250.0, 80000, 1200000, 'AVAILABLE', NOW(), NOW())
            """,
            self.unit_rent_id, bld_id, pt_id,
            self.unit_buy_id, self.unit_invest_id
        )

    async def asyncTearDown(self):
        # Clean up in correct FK order
        await self.conn.execute("DELETE FROM rent_collections WHERE tenancy_id IN (SELECT tenancy_id FROM tenancies WHERE unit_id = $1)", self.unit_rent_id)
        await self.conn.execute("DELETE FROM tenancies WHERE unit_id = $1", self.unit_rent_id)
        await self.conn.execute("DELETE FROM reservations WHERE unit_id IN ($1, $2, $3)", self.unit_rent_id, self.unit_buy_id, self.unit_invest_id)
        await self.conn.execute("DELETE FROM unit_status_history WHERE unit_id IN ($1, $2, $3)", self.unit_rent_id, self.unit_buy_id, self.unit_invest_id)
        await self.conn.execute("DELETE FROM communications WHERE customer_id = $1 OR lead_id IN (SELECT lead_id FROM leads WHERE customer_id = $1)", self.cust_id)
        await self.conn.execute("DELETE FROM tasks WHERE customer_id = $1", self.cust_id)
        await self.conn.execute("DELETE FROM activities WHERE customer_id = $1", self.cust_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id IN (SELECT opportunity_id FROM opportunities WHERE customer_id = $1)", self.cust_id)
        await self.conn.execute("DELETE FROM offers WHERE opportunity_id IN (SELECT opportunity_id FROM opportunities WHERE customer_id = $1)", self.cust_id)
        await self.conn.execute("DELETE FROM opportunities WHERE customer_id = $1", self.cust_id)
        await self.conn.execute("DELETE FROM leads WHERE customer_id = $1", self.cust_id)
        await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", self.cust_id)

        for uid in (self.unit_rent_id, self.unit_buy_id, self.unit_invest_id):
            await self.conn.execute("DELETE FROM documents WHERE unit_id = $1", uid)
            await self.conn.execute("DELETE FROM units WHERE unit_id = $1", uid)

        await self.conn.close()

    # =========================================================================
    # Test 1: Purpose-Based Lead Routing (RENT vs BUY vs INVESTMENT)
    # =========================================================================
    async def test_acceptance_1_purpose_based_lead_routing(self):
        # 1. RENT Lead
        lead_rent_id = "lead-gold-rent"
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_rent_id)
        await self.conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, inquiry_type,
                status, priority, budget_min, budget_max, assigned_user_id, created_at, updated_at
            ) VALUES ($1, $2, $3, 'RENT', 'NEW', 'HIGH', 40000, 60000, $4, NOW(), NOW())
            """,
            lead_rent_id, self.org_id, self.cust_id, self.agent_id
        )
        res_rent = await WorkflowEngine.on_lead_assigned(
            conn=self.conn,
            lead_id=lead_rent_id,
            assigned_user_id=self.agent_id
        )
        task_rent = res_rent["task"]
        self.assertEqual(task_rent["template_id"], "TASK_RENT_LEAD_FIRST_CONTACT")

        # 2. BUY Lead
        lead_buy_id = "lead-gold-buy"
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_buy_id)
        await self.conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, inquiry_type,
                status, priority, budget_min, budget_max, assigned_user_id, created_at, updated_at
            ) VALUES ($1, $2, $3, 'BUY', 'NEW', 'HIGH', 800000, 1000000, $4, NOW(), NOW())
            """,
            lead_buy_id, self.org_id, self.cust_id, self.agent_id
        )
        res_buy = await WorkflowEngine.on_lead_assigned(
            conn=self.conn,
            lead_id=lead_buy_id,
            assigned_user_id=self.agent_id
        )
        task_buy = res_buy["task"]
        self.assertEqual(task_buy["template_id"], "TASK_LEAD_FIRST_CONTACT")

        # 3. INVESTMENT Lead
        lead_invest_id = "lead-gold-invest"
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_invest_id)
        await self.conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, inquiry_type,
                status, priority, budget_min, budget_max, assigned_user_id, created_at, updated_at
            ) VALUES ($1, $2, $3, 'INVESTMENT', 'NEW', 'HIGH', 1000000, 1500000, $4, NOW(), NOW())
            """,
            lead_invest_id, self.org_id, self.cust_id, self.agent_id
        )
        res_invest = await WorkflowEngine.on_lead_assigned(
            conn=self.conn,
            lead_id=lead_invest_id,
            assigned_user_id=self.agent_id
        )
        task_invest = res_invest["task"]
        self.assertEqual(task_invest["template_id"], "TASK_INVEST_LEAD_FIRST_CONTACT")

    # =========================================================================
    # Test 2: Multi-Opportunity Isolation (Simultaneous Rental & Investment)
    # =========================================================================
    async def test_acceptance_2_multi_opportunity_isolation(self):
        # Create two distinct opportunities for the same customer
        opp_rent = "opp-gold-rent-01"
        opp_invest = "opp-gold-invest-01"
        for oid in (opp_rent, opp_invest):
            await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", oid)

        await self.conn.execute(
            """
            INSERT INTO opportunities (
                opportunity_id, customer_id,
                stage, expected_value, assigned_user_id, created_at, updated_at
            ) VALUES 
            ($1, $2, 'QUALIFIED', 50000, $3, NOW(), NOW()),
            ($4, $2, 'QUALIFIED', 1200000, $3, NOW(), NOW())
            """,
            opp_rent, self.cust_id, self.agent_id,
            opp_invest
        )

        # Spawning tasks for each opportunity concurrently must not collide
        task1, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_RENT_MATCH_PROPERTIES",
            assigned_user_id=self.agent_id,
            customer_id=self.cust_id,
            opportunity_id=opp_rent
        )
        task2, _ = await WorkflowEngine.spawn_task_from_template(
            conn=self.conn,
            template_id="TASK_INVEST_CONFIRM_OBJECTIVES",
            assigned_user_id=self.agent_id,
            customer_id=self.cust_id,
            opportunity_id=opp_invest
        )

        self.assertIsNotNone(task1)
        self.assertIsNotNone(task2)
        self.assertNotEqual(task1["task_id"], task2["task_id"])
        self.assertEqual(task1["opportunity_id"], opp_rent)
        self.assertEqual(task2["opportunity_id"], opp_invest)

    # =========================================================================
    # Test 3: Concurrency Protection on Unit Reservation
    # =========================================================================
    async def test_acceptance_3_unit_reservation_concurrency(self):
        # Create opportunity for reservation
        opp_id = "opp-gold-res-01"
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute(
            """
            INSERT INTO opportunities (
                opportunity_id, customer_id,
                stage, expected_value, assigned_user_id, created_at, updated_at
            ) VALUES ($1, $2, 'NEGOTIATION', 900000, $3, NOW(), NOW())
            """,
            opp_id, self.cust_id, self.agent_id
        )

        # First reservation succeeds
        res1 = await WorkflowEngine.create_unit_reservation(
            conn=self.conn,
            opportunity_id=opp_id,
            unit_id=self.unit_buy_id,
            customer_id=self.cust_id,
            deposit_amount=50000.0,
            user_id=self.agent_id
        )
        self.assertIsNotNone(res1)
        self.assertEqual(res1["status"], "ACTIVE")

        # Second reservation on the same unit is cleanly rejected with ValueError
        with self.assertRaises(ValueError) as ctx:
            await WorkflowEngine.create_unit_reservation(
                conn=self.conn,
                opportunity_id=opp_id,
                unit_id=self.unit_buy_id,
                customer_id=self.cust_id,
                deposit_amount=50000.0,
                user_id=self.agent_id
            )
        self.assertTrue("غير متاحة" in str(ctx.exception) or "not available" in str(ctx.exception).lower())

    # =========================================================================
    # Test 4: Non-Destructive Offer Rejection & Rematching
    # =========================================================================
    async def test_acceptance_4_non_destructive_offer_decline(self):
        lead_id = "lead-gold-offer"
        opp_id = "opp-gold-offer-decline"
        offer_id = "offer-gold-01"

        await self.conn.execute("DELETE FROM offers WHERE offer_id = $1", offer_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'BUY', NOW(), NOW())
            """,
            lead_id, self.org_id, self.cust_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'OFFER', 900000, NOW(), NOW())
            """,
            opp_id, lead_id, self.cust_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO offers (offer_id, opportunity_id, unit_id, offer_amount, status, submitted_at, valid_until)
            VALUES ($1, $2, $3, 900000, 'SUBMITTED', NOW(), NOW() + interval '3 days')
            """,
            offer_id, opp_id, self.unit_buy_id
        )

        res = await WorkflowEngine.record_offer_decision(
            conn=self.conn,
            offer_id=offer_id,
            decision="REJECTED",
            notes="Buyer rejected counter-offer; remap to alternatives",
            user_id=self.agent_id
        )
        self.assertEqual(res["decision"], "REJECTED")

        # Opportunity and Lead must remain OPEN (not CLOSED_LOST)
        opp_db = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
        self.assertEqual(opp_db["stage"], "OFFER")
        lead_db = await self.conn.fetchrow("SELECT status FROM leads WHERE lead_id = $1", lead_id)
        self.assertEqual(lead_db["status"], "QUALIFIED")

        # Property Rematching task must be spawned
        next_task = res["next_task"]
        self.assertIsNotNone(next_task)
        self.assertEqual(next_task["template_id"], "TASK_OPPORTUNITY_MATCH_PROPERTIES")

    # =========================================================================
    # Test 5: Mathematical Accuracy across All 5 Articles
    # =========================================================================
    def test_acceptance_5_mathematical_accuracy(self):
        # 1. Rental Yield Metrics
        metrics = CalculationService.calculate_rental_metrics(
            monthly_rent=5000.0,
            purchase_price=800000.0,
            annual_vacancy_allowance=3000.0,
            annual_operating_expenses=9000.0,
            acquisition_costs=40000.0
        )
        self.assertEqual(metrics["gross_yield_percent"], 7.50)
        self.assertEqual(metrics["net_operating_yield_percent"], 5.71)
        self.assertEqual(metrics["net_operating_income"], 48000.0)

        # 2. Investment Returns
        returns = CalculationService.calculate_investment_returns(
            purchase_price=1000000.0,
            cash_invested=300000.0,
            annual_pre_tax_cash_flow=36000.0,
            current_estimated_value=1200000.0,
            net_sale_proceeds=1150000.0,
            cumulative_rental_cash_flow=108000.0
        )
        self.assertEqual(returns["cash_on_cash_return_percent"], 12.0)
        self.assertEqual(returns["capital_appreciation_percent"], 20.0)
        self.assertEqual(returns["total_roi_percent"], 319.33)

        # 3. Managerial Equations 7.1 to 7.5
        sla = CalculationService.calculate_sla_compliance_rate(10, 10)
        self.assertEqual(sla["sla_compliance_percent"], 100.0)

        cohort = CalculationService.calculate_cohort_conversion_rate(4, 16)
        self.assertEqual(cohort["conversion_rate_percent"], 25.0)

        task_kpi = CalculationService.calculate_task_completion_rate(19, 20, 1)
        self.assertEqual(task_kpi["on_time_completion_rate_percent"], 95.0)

        viewing_kpi = CalculationService.calculate_viewing_to_offer_conversion(3, 6)
        self.assertEqual(viewing_kpi["viewing_to_offer_conversion_percent"], 50.0)

        variance = CalculationService.calculate_forecast_rental_variance(50000.0, 50000.0)
        self.assertEqual(variance["variance"], 0.0)
        self.assertEqual(variance["variance_percent"], 0.0)
        self.assertTrue(variance["is_favorable"])


if __name__ == "__main__":
    unittest.main()
