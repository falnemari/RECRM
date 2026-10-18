import asyncio
import unittest
from datetime import datetime, timezone, timedelta
import asyncpg
from app.config import settings
from app.services.workflow_engine import WorkflowEngine
from app.services.calculation_service import CalculationService


class TestConcurrencyControls(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(settings.asyncpg_dsn)
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

        # Dedicated test customer
        cust_row = await self.conn.fetchrow(
            """
            INSERT INTO customers (
                customer_id, organization_id, first_name, last_name, mobile, email, customer_type, created_at, updated_at
            ) VALUES (
                'cust-test-concurrency', $1, 'Concurrency', 'Tester', '966588887777', 'concurrency@test.com', 'INDIVIDUAL', NOW(), NOW()
            )
            ON CONFLICT (customer_id) DO UPDATE SET updated_at = NOW()
            RETURNING customer_id
            """,
            self.org_id
        )
        self.test_customer_id = cust_row["customer_id"]

        # Ensure isolated test unit
        self.bld_id = await self.conn.fetchval("SELECT building_id FROM buildings LIMIT 1") or "bld-1"
        self.pt_id = await self.conn.fetchval("SELECT property_type_id FROM property_types LIMIT 1") or "APT"
        self.test_unit_id = "unit-concurrency-test-01"

        await self.conn.execute(
            """
            INSERT INTO units (
                unit_id, building_id, unit_number, property_type_id, status, asking_price, rent_price, created_at, updated_at
            ) VALUES ($1, $2, 'CONC-101', $3, 'AVAILABLE', 750000.0, 60000.0, NOW(), NOW())
            ON CONFLICT (unit_id) DO UPDATE SET status = 'AVAILABLE', asking_price = 750000.0, rent_price = 60000.0
            """,
            self.test_unit_id, self.bld_id, self.pt_id
        )

    async def asyncTearDown(self):
        # Cleanup
        await self.conn.execute("DELETE FROM rent_collections WHERE tenancy_id IN (SELECT tenancy_id FROM tenancies WHERE unit_id = $1)", self.test_unit_id)
        await self.conn.execute("DELETE FROM tenancies WHERE unit_id = $1", self.test_unit_id)
        await self.conn.execute("DELETE FROM reservations WHERE unit_id = $1", self.test_unit_id)
        await self.conn.execute("DELETE FROM unit_status_history WHERE unit_id = $1", self.test_unit_id)
        await self.conn.execute("DELETE FROM communications WHERE customer_id = $1 OR lead_id IN (SELECT lead_id FROM leads WHERE customer_id = $1)", self.test_customer_id)
        await self.conn.execute("DELETE FROM tasks WHERE customer_id = $1", self.test_customer_id)
        await self.conn.execute("DELETE FROM activities WHERE customer_id = $1", self.test_customer_id)
        await self.conn.execute("DELETE FROM opportunity_units WHERE opportunity_id IN (SELECT opportunity_id FROM opportunities WHERE customer_id = $1)", self.test_customer_id)
        await self.conn.execute("DELETE FROM offers WHERE opportunity_id IN (SELECT opportunity_id FROM opportunities WHERE customer_id = $1)", self.test_customer_id)
        await self.conn.execute("DELETE FROM opportunities WHERE customer_id = $1", self.test_customer_id)
        await self.conn.execute("DELETE FROM leads WHERE customer_id = $1", self.test_customer_id)
        await self.conn.execute("DELETE FROM customers WHERE customer_id = $1", self.test_customer_id)
        await self.conn.execute("DELETE FROM units WHERE unit_id = $1", self.test_unit_id)
        await self.conn.close()

    async def test_01_simultaneous_unit_reservation_row_level_locking(self):
        """
        1. Two concurrent asynchronous tasks attempt to reserve the same unit simultaneously.
           Row-level locking (SELECT ... FOR UPDATE) ensures exactly one succeeds and one is rejected.
        """
        # Create 2 separate opportunities
        opp1 = "opp-conc-res-01"
        opp2 = "opp-conc-res-02"
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, 'QUALIFIED', 750000, NOW(), NOW()),
                   ($4, $2, $3, 'QUALIFIED', 750000, NOW(), NOW())
            """,
            opp1, self.test_customer_id, self.agent_id, opp2
        )

        async def attempt_reservation(opp_id):
            # Each concurrent task must run in its own database connection and transaction
            conn = await asyncpg.connect(settings.asyncpg_dsn)
            try:
                async with conn.transaction():
                    return await WorkflowEngine.create_unit_reservation(
                        conn=conn,
                        opportunity_id=opp_id,
                        unit_id=self.test_unit_id,
                        customer_id=self.test_customer_id,
                        deposit_amount=37500.0,
                        expiry_hours=48,
                        user_id=self.agent_id
                    )
            finally:
                await conn.close()

        # Run both simultaneously
        results = await asyncio.gather(
            attempt_reservation(opp1),
            attempt_reservation(opp2),
            return_exceptions=True
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]

        self.assertEqual(len(successes), 1, "Exactly one concurrent reservation must succeed")
        self.assertEqual(len(failures), 1, "Exactly one concurrent reservation must fail due to lock")
        self.assertIsInstance(failures[0], ValueError)
        self.assertIn("غير متاحة للحجز حالياً", str(failures[0]))

        # Unit status must be RESERVED
        unit_st = await self.conn.fetchval("SELECT status FROM units WHERE unit_id = $1", self.test_unit_id)
        self.assertEqual(unit_st, "RESERVED")

        # Cleanup
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id IN ($1, $2)", opp1, opp2)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id IN ($1, $2)", opp1, opp2)
        await self.conn.execute("DELETE FROM reservations WHERE unit_id = $1", self.test_unit_id)
        await self.conn.execute("UPDATE units SET status = 'AVAILABLE' WHERE unit_id = $1", self.test_unit_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id IN ($1, $2)", opp1, opp2)

    async def test_02_simultaneous_tenancy_execution_row_level_locking(self):
        """
        2. Two concurrent asynchronous tasks attempt to lease the same unit simultaneously.
           Row-level locking ensures exactly one tenancy is created and the second is rejected.
        """
        opp1 = "opp-conc-ten-01"
        opp2 = "opp-conc-ten-02"
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, 'QUALIFIED', 60000, NOW(), NOW()),
                   ($4, $2, $3, 'QUALIFIED', 60000, NOW(), NOW())
            """,
            opp1, self.test_customer_id, self.agent_id, opp2
        )

        start_d = datetime.now(timezone.utc)

        async def attempt_tenancy(opp_id):
            conn = await asyncpg.connect(settings.asyncpg_dsn)
            try:
                async with conn.transaction():
                    return await WorkflowEngine.execute_tenancy_agreement(
                        conn=conn,
                        unit_id=self.test_unit_id,
                        tenant_customer_id=self.test_customer_id,
                        start_date=start_d,
                        rent_amount=60000.0,
                        opportunity_id=opp_id,
                        user_id=self.agent_id
                    )
            finally:
                await conn.close()

        results = await asyncio.gather(
            attempt_tenancy(opp1),
            attempt_tenancy(opp2),
            return_exceptions=True
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]

        self.assertEqual(len(successes), 1, "Exactly one concurrent tenancy must succeed")
        self.assertEqual(len(failures), 1, "Exactly one concurrent tenancy must fail")
        self.assertIsInstance(failures[0], ValueError)
        self.assertIn("غير متاحة للإيجار", str(failures[0]))

        # Unit status must be RENTED
        unit_st = await self.conn.fetchval("SELECT status FROM units WHERE unit_id = $1", self.test_unit_id)
        self.assertEqual(unit_st, "RENTED")

        # Cleanup
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id IN ($1, $2)", opp1, opp2)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id IN ($1, $2)", opp1, opp2)
        await self.conn.execute("DELETE FROM rent_collections WHERE tenancy_id IN (SELECT tenancy_id FROM tenancies WHERE unit_id = $1)", self.test_unit_id)
        await self.conn.execute("DELETE FROM tenancies WHERE unit_id = $1", self.test_unit_id)
        await self.conn.execute("UPDATE units SET status = 'AVAILABLE' WHERE unit_id = $1", self.test_unit_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id IN ($1, $2)", opp1, opp2)

    async def test_03_non_destructive_offer_rejection(self):
        """
        3. Non-Destructive Offer Rejection:
           When an offer is rejected, the customer's lead and opportunity remain active,
           and a property rematching task is automatically spawned.
        """
        lead_id = "lead-conc-offer-01"
        opp_id = "opp-conc-offer-01"
        offer_id = "offer-conc-01"
        now_dt = datetime.now(timezone.utc)

        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, assigned_user_id, status, priority, inquiry_type, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'QUALIFIED', 'HIGH', 'BUY', NOW(), NOW())
            """,
            lead_id, self.org_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, $4, 'OFFER', 700000, NOW(), NOW())
            """,
            opp_id, lead_id, self.test_customer_id, self.agent_id
        )
        await self.conn.execute(
            """
            INSERT INTO offers (offer_id, opportunity_id, unit_id, offer_amount, status, submitted_at, valid_until)
            VALUES ($1, $2, $3, 700000, 'SUBMITTED', NOW(), NOW() + interval '3 days')
            """,
            offer_id, opp_id, self.test_unit_id
        )

        res = await WorkflowEngine.record_offer_decision(
            conn=self.conn,
            offer_id=offer_id,
            decision="REJECTED",
            notes="تم رفض العرض من قبل البائع لعدم مناسبة السعر.",
            user_id=self.agent_id
        )

        self.assertEqual(res["decision"], "REJECTED")

        # Offer status updated to REJECTED
        off_db = await self.conn.fetchrow("SELECT status FROM offers WHERE offer_id = $1", offer_id)
        self.assertEqual(off_db["status"], "REJECTED")

        # Opportunity and Lead must NOT be closed/lost!
        opp_db = await self.conn.fetchrow("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
        self.assertEqual(opp_db["stage"], "OFFER")  # Remains active
        lead_db = await self.conn.fetchrow("SELECT status FROM leads WHERE lead_id = $1", lead_id)
        self.assertEqual(lead_db["status"], "QUALIFIED")

        # Property Rematching task must be spawned
        next_task = res["next_task"]
        self.assertIsNotNone(next_task)
        self.assertEqual(next_task["template_id"], "TASK_OPPORTUNITY_MATCH_PROPERTIES")

        # Cleanup
        await self.conn.execute("DELETE FROM tasks WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM activities WHERE opportunity_id = $1 OR lead_id = $2", opp_id, lead_id)
        await self.conn.execute("DELETE FROM offers WHERE offer_id = $1", offer_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)
        await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", lead_id)

    async def test_04_reservation_expiration_and_unit_release(self):
        """
        4. Expired reservation without deposit verification automatically releases unit to AVAILABLE.
        """
        opp_id = "opp-conc-exp-01"
        res_id = "res-conc-exp-01"
        past_time = datetime.now(timezone.utc) - timedelta(hours=50)

        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
            VALUES ($1, $2, $3, 'RESERVATION', 750000, NOW(), NOW())
            """,
            opp_id, self.test_customer_id, self.agent_id
        )

        # Mark unit as RESERVED
        await self.conn.execute("UPDATE units SET status = 'RESERVED' WHERE unit_id = $1", self.test_unit_id)

        # Insert expired reservation
        await self.conn.execute(
            """
            INSERT INTO reservations (
                reservation_id, opportunity_id, unit_id, customer_id, reservation_number,
                reserved_at, expires_at, deposit_amount, status
            ) VALUES ($1, $2, $3, $4, 'RES-EXP-001', $5, $6, 37500.0, 'ACTIVE')
            """,
            res_id, opp_id, self.test_unit_id, self.test_customer_id, past_time, past_time + timedelta(hours=48)
        )

        # Run expiration processor
        res = await WorkflowEngine.process_expired_reservations(self.conn)

        self.assertGreaterEqual(len(res["expired_and_released"]), 1)

        # Reservation status is now EXPIRED
        res_db = await self.conn.fetchrow("SELECT status FROM reservations WHERE reservation_id = $1", res_id)
        self.assertEqual(res_db["status"], "EXPIRED")

        # Unit status is cleanly restored to AVAILABLE
        unit_st = await self.conn.fetchval("SELECT status FROM units WHERE unit_id = $1", self.test_unit_id)
        self.assertEqual(unit_st, "AVAILABLE")

        # Cleanup
        await self.conn.execute("DELETE FROM reservations WHERE reservation_id = $1", res_id)
        await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", opp_id)

    async def test_05_payment_amount_constraint_enforcement(self):
        """
        5. Balance & Payment Constraint Enforcement:
           Ensures amount_paid <= amount_due and balance calculation conforms to Article 3.E.
        """
        bal_res = CalculationService.calculate_outstanding_balance(
            amount_due=50000.0,
            amount_paid=20000.0
        )
        self.assertEqual(bal_res["outstanding_balance"], 30000.0)
        self.assertFalse(bal_res["is_fully_paid"])

        # Fully paid
        bal_full = CalculationService.calculate_outstanding_balance(
            amount_due=50000.0,
            amount_paid=50000.0
        )
        self.assertEqual(bal_full["outstanding_balance"], 0.0)
        self.assertTrue(bal_full["is_fully_paid"])

        # Overpayment rejection
        with self.assertRaises(ValueError):
            CalculationService.calculate_outstanding_balance(
                amount_due=50000.0,
                amount_paid=60000.0
            )


if __name__ == "__main__":
    unittest.main()
