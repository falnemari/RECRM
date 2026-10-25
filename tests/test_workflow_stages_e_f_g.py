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


class TestWorkflowStagesEFG(unittest.IsolatedAsyncioTestCase):

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
        self.branch_id = await self.conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", self.agent_id) or "branch-3"
        self.building_id = await self.conn.fetchval("SELECT building_id FROM buildings LIMIT 1") or "bld-1"
        self.property_type_id = await self.conn.fetchval("SELECT property_type_id FROM property_types LIMIT 1") or "pt-1"

    async def asyncTearDown(self):
        await self.conn.close()

    async def test_stage_e_commercial_offer_within_threshold(self):
        """
        Stage E Test:
          Commercial offer submitted within 5% threshold:
          - Asking price: 500,000 SAR, Offer: 485,000 SAR (3% discount)
          - Offer status becomes SUBMITTED
          - Opportunity stage advances to OFFER
          - Activity ACT_OFFER_CREATED logged
          - Outbound WhatsApp COMM_OFFER_PROPOSAL_SENT recorded
          - TASK_OFFER_FOLLOWUP spawned with due date before expiry
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            cust_id = "test-cust-e-01"
            opp_id = "test-opp-e-01"
            unit_id = "test-unit-e-01"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Sultan', 'Al-Otaibi', '+966500998877', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )
            await self.conn.execute(
                """
                INSERT INTO units (unit_id, building_id, unit_number, property_type_id, asking_price, status, created_at, updated_at)
                VALUES ($1, $2, 'U-E01', $3, 500000.0, 'AVAILABLE', NOW(), NOW())
                """,
                unit_id, self.building_id, self.property_type_id
            )
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, 'NEGOTIATION', 500000.0, NOW(), NOW())
                """,
                opp_id, cust_id, self.agent_id
            )

            # Submit commercial offer with 3% discount (485,000)
            res = await WorkflowEngine.submit_commercial_offer(
                conn=self.conn,
                opportunity_id=opp_id,
                unit_id=unit_id,
                offer_amount=485000.0,
                valid_until=datetime.now(timezone.utc) + timedelta(days=5),
                user_id=self.agent_id
            )

            self.assertEqual(res["status"], "SUBMITTED")
            self.assertFalse(res["requires_manager_approval"])
            self.assertIsNotNone(res["followup_task"])

            # Verify Opportunity stage advanced to OFFER
            opp_stage = await self.conn.fetchval("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
            self.assertEqual(opp_stage, "OFFER")

            # Verify ACT_OFFER_CREATED logged
            act = await self.conn.fetchrow(
                "SELECT * FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_OFFER_CREATED'",
                opp_id
            )
            self.assertIsNotNone(act)
            self.assertEqual(act["outcome"], "SUBMITTED")

            # Verify COMM_OFFER_PROPOSAL_SENT recorded
            comm = await self.conn.fetchrow(
                "SELECT * FROM communications WHERE customer_id = $1 AND template_id = 'COMM_OFFER_PROPOSAL_SENT'",
                cust_id
            )
            self.assertIsNotNone(comm)
            self.assertEqual(comm["delivery_status"], "SENT")

        finally:
            await tr.rollback()

    async def test_stage_e_discount_exceeds_threshold_requires_manager_approval(self):
        """
        Stage E Test:
          Offer with discount > 5% (Asking: 500k, Offer: 450k -> 10% discount):
          - Offer status becomes PENDING_APPROVAL
          - Automatically spawns TASK_OFFER_MANAGER_APPROVAL
          - Proposal is NOT sent to customer yet
          - When Manager approves, becomes SUBMITTED and spawns follow-up
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            cust_id = "test-cust-e-02"
            opp_id = "test-opp-e-02"
            unit_id = "test-unit-e-02"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Bandar', 'Al-Dosari', '+966500334455', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )
            await self.conn.execute(
                """
                INSERT INTO units (unit_id, building_id, unit_number, property_type_id, asking_price, status, created_at, updated_at)
                VALUES ($1, $2, 'U-E02', $3, 500000.0, 'AVAILABLE', NOW(), NOW())
                """,
                unit_id, self.building_id, self.property_type_id
            )
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, 'NEGOTIATION', 500000.0, NOW(), NOW())
                """,
                opp_id, cust_id, self.agent_id
            )

            # Submit offer with 10% discount (450,000)
            res = await WorkflowEngine.submit_commercial_offer(
                conn=self.conn,
                opportunity_id=opp_id,
                unit_id=unit_id,
                offer_amount=450000.0,
                user_id=self.agent_id
            )

            self.assertEqual(res["status"], "PENDING_APPROVAL")
            self.assertTrue(res["requires_manager_approval"])
            self.assertIsNotNone(res["manager_approval_task"])
            self.assertEqual(res["manager_approval_task"]["template_id"], "TASK_OFFER_MANAGER_APPROVAL")

            # Verify no proposal sent to customer while pending approval
            comm_cnt = await self.conn.fetchval(
                "SELECT count(*) FROM communications WHERE customer_id = $1 AND template_id = 'COMM_OFFER_PROPOSAL_SENT'",
                cust_id
            )
            self.assertEqual(comm_cnt, 0)

            # Now Manager approves the offer
            offer_id = res["offer_id"]
            dec_res = await WorkflowEngine.record_offer_decision(
                conn=self.conn,
                offer_id=offer_id,
                decision="APPROVED",
                notes="Approved by Branch Manager",
                user_id=self.agent_id
            )

            self.assertEqual(dec_res["decision"], "APPROVED")
            offer_row = await self.conn.fetchrow("SELECT status FROM offers WHERE offer_id = $1", offer_id)
            self.assertEqual(offer_row["status"], "SUBMITTED")

            # Proposal now sent
            comm = await self.conn.fetchrow(
                "SELECT * FROM communications WHERE customer_id = $1 AND template_id = 'COMM_OFFER_PROPOSAL_SENT'",
                cust_id
            )
            self.assertIsNotNone(comm)
            self.assertEqual(comm["delivery_status"], "SENT")

        finally:
            await tr.rollback()

    async def test_stage_e_offer_acceptance_triggers_reservation_task(self):
        """
        Stage E -> Stage F Transition:
          When an offer is marked ACCEPTED:
          - Offer status becomes ACCEPTED
          - ACT_OFFER_DECISION logged with outcome ACCEPTED
          - COMM_OFFER_DECISION_COMMUNICATED sent to client
          - Automatically spawns Stage F task: TASK_RESERVATION_VERIFY_AVAILABILITY
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            cust_id = "test-cust-e-03"
            opp_id = "test-opp-e-03"
            unit_id = "test-unit-e-03"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Nasser', 'Al-Harbi', '+966500889900', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )
            await self.conn.execute(
                """
                INSERT INTO units (unit_id, building_id, unit_number, property_type_id, asking_price, status, created_at, updated_at)
                VALUES ($1, $2, 'U-E03', $3, 600000.0, 'AVAILABLE', NOW(), NOW())
                """,
                unit_id, self.building_id, self.property_type_id
            )
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, 'OFFER', 600000.0, NOW(), NOW())
                """,
                opp_id, cust_id, self.agent_id
            )

            res = await WorkflowEngine.submit_commercial_offer(
                conn=self.conn,
                opportunity_id=opp_id,
                unit_id=unit_id,
                offer_amount=590000.0,
                user_id=self.agent_id
            )
            offer_id = res["offer_id"]

            # Record customer acceptance
            dec_res = await WorkflowEngine.record_offer_decision(
                conn=self.conn,
                offer_id=offer_id,
                decision="ACCEPTED",
                notes="Client accepted the proposal",
                user_id=self.agent_id
            )

            self.assertEqual(dec_res["decision"], "ACCEPTED")
            # Verify TASK_RESERVATION_VERIFY_AVAILABILITY was spawned
            res_task = dec_res["next_task"]
            self.assertIsNotNone(res_task)
            self.assertEqual(res_task["template_id"], "TASK_RESERVATION_VERIFY_AVAILABILITY")

        finally:
            await tr.rollback()

    async def test_stage_f_atomic_reservation_and_concurrency_locking(self):
        """
        Stage F Research Rule:
          Reservation must check availability transactionally (FOR UPDATE).
          - Reserves unit, atomically updates status to RESERVED
          - Inserts unit_status_history record
          - Spawns TASK_RESERVATION_DEPOSIT_FOLLOWUP for Finance (48h SLA)
          - Prevents race condition: Second attempt to reserve the same unit fails immediately.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            cust_id_1 = "test-cust-f-01"
            cust_id_2 = "test-cust-f-02"
            opp_id_1 = "test-opp-f-01"
            opp_id_2 = "test-opp-f-02"
            unit_id = "test-unit-f-01"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES 
                  ($1, $3, 'INDIVIDUAL', 'Rami', 'Al-Shehri', '+966555112233', 'ACTIVE', NOW(), NOW()),
                  ($2, $3, 'INDIVIDUAL', 'Fahad', 'Al-Qahtani', '+966555445566', 'ACTIVE', NOW(), NOW())
                """,
                cust_id_1, cust_id_2, self.org_id
            )
            await self.conn.execute(
                """
                INSERT INTO units (unit_id, building_id, unit_number, property_type_id, asking_price, status, created_at, updated_at)
                VALUES ($1, $2, 'U-F01', $3, 750000.0, 'AVAILABLE', NOW(), NOW())
                """,
                unit_id, self.building_id, self.property_type_id
            )
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES 
                  ($1, $3, $5, 'NEGOTIATION', 750000.0, NOW(), NOW()),
                  ($2, $4, $5, 'NEGOTIATION', 750000.0, NOW(), NOW())
                """,
                opp_id_1, opp_id_2, cust_id_1, cust_id_2, self.agent_id
            )

            # Agent 1 successfully reserves the unit
            res1 = await WorkflowEngine.create_unit_reservation(
                conn=self.conn,
                opportunity_id=opp_id_1,
                unit_id=unit_id,
                customer_id=cust_id_1,
                deposit_amount=37500.0,
                expiry_hours=48,
                user_id=self.agent_id
            )

            self.assertEqual(res1["status"], "ACTIVE")
            self.assertEqual(res1["deposit_amount"], 37500.0)

            # Verify Unit status is now RESERVED
            u_status = await self.conn.fetchval("SELECT status FROM units WHERE unit_id = $1", unit_id)
            self.assertEqual(u_status, "RESERVED")

            # Verify unit_status_history record
            hist = await self.conn.fetchrow(
                "SELECT * FROM unit_status_history WHERE unit_id = $1 ORDER BY changed_at DESC LIMIT 1",
                unit_id
            )
            self.assertIsNotNone(hist)
            self.assertEqual(hist["old_status"], "AVAILABLE")
            self.assertEqual(hist["new_status"], "RESERVED")

            # Verify deposit follow-up task created
            dep_task = res1["deposit_task"]
            self.assertIsNotNone(dep_task)
            self.assertEqual(dep_task["template_id"], "TASK_RESERVATION_DEPOSIT_FOLLOWUP")

            # Agent 2 attempts to reserve the same unit simultaneously -> must fail with ValueError
            with self.assertRaises(ValueError) as ctx:
                await WorkflowEngine.create_unit_reservation(
                    conn=self.conn,
                    opportunity_id=opp_id_2,
                    unit_id=unit_id,
                    customer_id=cust_id_2,
                    deposit_amount=37500.0,
                    user_id=self.agent_id
                )
            self.assertIn("غير متاحة للحجز حالياً", str(ctx.exception))

        finally:
            await tr.rollback()

    async def test_stage_f_deposit_verification_spawns_contract_draft(self):
        """
        Stage F -> Stage G Transition:
          - Reservation deposit is verified by Finance
          - Reservation status becomes CONFIRMED
          - Automatically spawns Stage G task: TASK_CONTRACT_DRAFT for Legal
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            cust_id = "test-cust-f-03"
            opp_id = "test-opp-f-03"
            unit_id = "test-unit-f-03"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Saad', 'Al-Mutairi', '+966555778899', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )
            await self.conn.execute(
                """
                INSERT INTO units (unit_id, building_id, unit_number, property_type_id, asking_price, status, created_at, updated_at)
                VALUES ($1, $2, 'U-F03', $3, 800000.0, 'AVAILABLE', NOW(), NOW())
                """,
                unit_id, self.building_id, self.property_type_id
            )
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, 'NEGOTIATION', 800000.0, NOW(), NOW())
                """,
                opp_id, cust_id, self.agent_id
            )

            res = await WorkflowEngine.create_unit_reservation(
                conn=self.conn,
                opportunity_id=opp_id,
                unit_id=unit_id,
                customer_id=cust_id,
                deposit_amount=40000.0,
                user_id=self.agent_id
            )
            res_id = res["reservation_id"]

            # Finance verifies deposit receipt
            v_res = await WorkflowEngine.verify_reservation_deposit(
                conn=self.conn,
                reservation_id=res_id,
                amount_received=40000.0,
                payment_method="BANK_TRANSFER",
                payment_ref="DEP-TX-998811",
                user_id=self.agent_id
            )

            self.assertEqual(v_res["status"], "CONFIRMED")
            self.assertTrue(v_res["deposit_verified"])

            # Verify Stage G TASK_CONTRACT_DRAFT spawned
            draft_task = v_res["draft_task"]
            self.assertIsNotNone(draft_task)
            self.assertEqual(draft_task["template_id"], "TASK_CONTRACT_DRAFT")

        finally:
            await tr.rollback()

    async def test_stage_g_full_contract_lifecycle_to_closure(self):
        """
        Stage G End-to-End Test:
          1. Contract draft created (DRAFT) -> spawns internal review
          2. Legal approves draft -> moves to PENDING_SIGNATURE, spawns customer signature
          3. Contract signed -> moves to SIGNED, reservation CONVERTED, creates DUE payments,
             spawns TASK_CONTRACT_RECONCILIATION & TASK_CONTRACT_HANDOVER
          4. Handover completed -> Contract ACTIVE, unit SOLD, unit_status_history logged,
             opportunity CLOSED_WON, ACT_CONTRACT_CLOSED recorded.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            cust_id = "test-cust-g-01"
            opp_id = "test-opp-g-01"
            unit_id = "test-unit-g-01"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Mishal', 'Al-Ghamdi', '+966555123456', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )
            await self.conn.execute(
                """
                INSERT INTO units (unit_id, building_id, unit_number, property_type_id, asking_price, status, created_at, updated_at)
                VALUES ($1, $2, 'U-G01', $3, 900000.0, 'AVAILABLE', NOW(), NOW())
                """,
                unit_id, self.building_id, self.property_type_id
            )
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, 'RESERVATION', 900000.0, NOW(), NOW())
                """,
                opp_id, cust_id, self.agent_id
            )

            res = await WorkflowEngine.create_unit_reservation(
                conn=self.conn,
                opportunity_id=opp_id,
                unit_id=unit_id,
                customer_id=cust_id,
                deposit_amount=50000.0,
                user_id=self.agent_id
            )
            res_id = res["reservation_id"]

            # Step 1: Initiate Contract Draft
            draft_res = await WorkflowEngine.initiate_contract_draft(
                conn=self.conn,
                reservation_id=res_id,
                contract_type="SALE",
                contract_value=900000.0,
                user_id=self.agent_id
            )
            contract_id = draft_res["contract_id"]
            self.assertEqual(draft_res["status"], "DRAFT")
            self.assertEqual(draft_res["review_task"]["template_id"], "TASK_CONTRACT_INTERNAL_REVIEW")

            # Step 2: Legal Approves Draft
            rev_res = await WorkflowEngine.advance_contract_lifecycle(
                conn=self.conn,
                contract_id=contract_id,
                action="APPROVE_DRAFT",
                user_id=self.agent_id
            )
            self.assertEqual(rev_res["next_task"]["template_id"], "TASK_CONTRACT_SIGNATURE")
            c_status = await self.conn.fetchval("SELECT status FROM contracts WHERE contract_id = $1", contract_id)
            self.assertEqual(c_status, "PENDING_SIGNATURE")

            # Step 3: Record Customer Signature
            sign_res = await WorkflowEngine.advance_contract_lifecycle(
                conn=self.conn,
                contract_id=contract_id,
                action="RECORD_SIGNATURE",
                user_id=self.agent_id
            )
            c_status = await self.conn.fetchval("SELECT status FROM contracts WHERE contract_id = $1", contract_id)
            self.assertEqual(c_status, "SIGNED")

            # Verify reservation is CONVERTED
            r_status = await self.conn.fetchval("SELECT status FROM reservations WHERE reservation_id = $1", res_id)
            self.assertEqual(r_status, "CONVERTED")

            # Verify payment schedule created: Deposit (PAID), Remaining (DUE)
            payments = await self.conn.fetch("SELECT amount_due, amount_paid, status FROM payments WHERE contract_id = $1 ORDER BY due_date ASC", contract_id)
            self.assertGreaterEqual(len(payments), 2)
            self.assertEqual(payments[0]["status"], "PAID")
            self.assertEqual(payments[0]["amount_paid"], 50000.0)
            self.assertEqual(payments[1]["status"], "DUE")
            self.assertEqual(payments[1]["amount_due"], 850000.0)

            # Verify commission created as PENDING (not yet paid)
            comm = await self.conn.fetchrow("SELECT * FROM commissions WHERE contract_id = $1", contract_id)
            self.assertIsNotNone(comm)
            self.assertEqual(comm["status"], "PENDING")
            gross_brokerage = float(comm.get("gross_brokerage_amount") or comm["amount"])
            self.assertEqual(gross_brokerage, 900000.0 * 0.025)

            # Step 4: Finalize Handover & Deal Closure
            close_res = await WorkflowEngine.advance_contract_lifecycle(
                conn=self.conn,
                contract_id=contract_id,
                action="COMPLETE_HANDOVER",
                user_id=self.agent_id
            )
            self.assertEqual(close_res["action"], "COMPLETE_HANDOVER")

            # Verify Unit is SOLD
            u_status = await self.conn.fetchval("SELECT status FROM units WHERE unit_id = $1", unit_id)
            self.assertEqual(u_status, "SOLD")

            # Verify Opportunity is CLOSED_WON
            o_stage = await self.conn.fetchval("SELECT stage FROM opportunities WHERE opportunity_id = $1", opp_id)
            self.assertEqual(o_stage, "CLOSED_WON")

            # Verify ACT_CONTRACT_CLOSED logged
            act_close = await self.conn.fetchrow(
                "SELECT * FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_CONTRACT_CLOSED'",
                opp_id
            )
            self.assertIsNotNone(act_close)
            self.assertEqual(act_close["outcome"], "CLOSED_WON")

        finally:
            await tr.rollback()

    async def test_stage_f_expired_reservation_cleanup_and_release(self):
        """
        Stage F Expiration Test:
          - An unpaid reservation past its expiry is marked EXPIRED and unit returned to AVAILABLE with history.
          - A reservation expiring within 12h spawns TASK_RESERVATION_EXPIRY_REVIEW.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            cust_id = "test-cust-f-exp"
            opp_id_1 = "test-opp-f-exp1"
            opp_id_2 = "test-opp-f-exp2"
            unit_id_1 = "test-unit-f-exp1"
            unit_id_2 = "test-unit-f-exp2"
            res_id_1 = "test-res-f-exp1"
            res_id_2 = "test-res-f-exp2"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Nasser', 'Al-Qahtani', '+966500554433', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )
            # Unit 1 - will expire
            await self.conn.execute(
                """
                INSERT INTO units (unit_id, building_id, unit_number, property_type_id, asking_price, status, created_at, updated_at)
                VALUES ($1, $2, 'U-EXP1', $3, 750000.0, 'RESERVED', NOW(), NOW())
                """,
                unit_id_1, self.building_id, self.property_type_id
            )
            # Unit 2 - approaching expiry (in 4 hours)
            await self.conn.execute(
                """
                INSERT INTO units (unit_id, building_id, unit_number, property_type_id, asking_price, status, created_at, updated_at)
                VALUES ($1, $2, 'U-EXP2', $3, 850000.0, 'RESERVED', NOW(), NOW())
                """,
                unit_id_2, self.building_id, self.property_type_id
            )
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, 'UNDER_OFFER', 750000.0, NOW(), NOW()),
                       ($4, $2, $3, 'UNDER_OFFER', 850000.0, NOW(), NOW())
                """,
                opp_id_1, cust_id, self.agent_id, opp_id_2
            )

            # Insert expired reservation (expired 2 hours ago)
            past_expiry = datetime.now(timezone.utc) - timedelta(hours=2)
            await self.conn.execute(
                """
                INSERT INTO reservations (
                    reservation_id, reservation_number, opportunity_id, unit_id, customer_id,
                    deposit_amount, status, expires_at, reserved_at
                ) VALUES ($1, 'RES-EXP-001', $2, $3, $4, 37500.0, 'ACTIVE', $5, NOW() - interval '50 hours')
                """,
                res_id_1, opp_id_1, unit_id_1, cust_id, past_expiry
            )

            # Insert approaching expiry reservation (expires in 4 hours)
            near_expiry = datetime.now(timezone.utc) + timedelta(hours=4)
            await self.conn.execute(
                """
                INSERT INTO reservations (
                    reservation_id, reservation_number, opportunity_id, unit_id, customer_id,
                    deposit_amount, status, expires_at, reserved_at
                ) VALUES ($1, 'RES-EXP-002', $2, $3, $4, 42500.0, 'ACTIVE', $5, NOW() - interval '44 hours')
                """,
                res_id_2, opp_id_2, unit_id_2, cust_id, near_expiry
            )

            # Process expirations
            res_summary = await WorkflowEngine.process_expired_reservations(self.conn)

            # Assert expired reservation cancelled and unit released
            self.assertIn(res_id_1, res_summary["expired_and_released"])
            r1_status = await self.conn.fetchval("SELECT status FROM reservations WHERE reservation_id = $1", res_id_1)
            self.assertEqual(r1_status, "EXPIRED")
            u1_status = await self.conn.fetchval("SELECT status FROM units WHERE unit_id = $1", unit_id_1)
            self.assertEqual(u1_status, "AVAILABLE")

            # Check unit_status_history
            ush = await self.conn.fetchrow(
                "SELECT * FROM unit_status_history WHERE unit_id = $1 ORDER BY changed_at DESC LIMIT 1",
                unit_id_1
            )
            self.assertIsNotNone(ush)
            self.assertEqual(ush["new_status"], "AVAILABLE")

            # Assert approaching expiry spawned review task
            self.assertIn(res_id_2, res_summary["approaching_expiry_reviews"])
            task = await self.conn.fetchrow(
                "SELECT * FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_RESERVATION_EXPIRY_REVIEW'",
                opp_id_2
            )
            self.assertIsNotNone(task)
            self.assertEqual(task["priority"], "URGENT")

        finally:
            await tr.rollback()

    async def test_stage_g_contract_cancellation_cascade(self):
        """
        Stage G Test:
          Contract Cancellation Cascade:
          - Initiating CANCEL on a contract updates its status to CANCELLED.
          - Unpaid payments (DUE) are automatically updated to CANCELLED.
          - Settled payments (PAID) remain untouched.
          - Unpaid commissions (PENDING) are automatically updated to CANCELLED.
          - Operational contract tasks are cancelled.
          - Unit is released back to AVAILABLE with status history.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            cust_id = "test-cust-cancel-01"
            opp_id = "test-opp-cancel-01"
            unit_id = "test-unit-cancel-01"
            res_id = "test-res-cancel-01"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at, updated_at)
                VALUES ($1, $2, 'INDIVIDUAL', 'Hamad', 'Al-Harbi', '+966551122334', 'ACTIVE', NOW(), NOW())
                """,
                cust_id, self.org_id
            )
            await self.conn.execute(
                """
                INSERT INTO units (unit_id, building_id, unit_number, property_type_id, asking_price, status, created_at, updated_at)
                VALUES ($1, $2, 'U-CANCEL01', $3, 1000000.0, 'RESERVED', NOW(), NOW())
                """,
                unit_id, self.building_id, self.property_type_id
            )
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, customer_id, assigned_user_id, stage, expected_value, created_at, updated_at)
                VALUES ($1, $2, $3, 'UNDER_OFFER', 1000000.0, NOW(), NOW())
                """,
                opp_id, cust_id, self.agent_id
            )
            await self.conn.execute(
                """
                INSERT INTO reservations (
                    reservation_id, reservation_number, opportunity_id, unit_id, customer_id,
                    deposit_amount, status, expires_at, reserved_at
                ) VALUES ($1, 'RES-CANCEL-001', $2, $3, $4, 50000.0, 'ACTIVE', NOW() + interval '48 hours', NOW())
                """,
                res_id, opp_id, unit_id, cust_id
            )

            # Step 1: Initiate draft contract
            draft_res = await WorkflowEngine.initiate_contract_draft(
                conn=self.conn,
                reservation_id=res_id,
                contract_type="SALE",
                contract_value=1000000.0,
                user_id=self.agent_id
            )
            contract_id = draft_res["contract_id"]

            # Step 2: Record signature (generates deposit PAID, remaining DUE, commission PENDING, tasks)
            await WorkflowEngine.advance_contract_lifecycle(
                conn=self.conn,
                contract_id=contract_id,
                action="RECORD_SIGNATURE",
                user_id=self.agent_id
            )

            # Verify payments exist
            payments = await self.conn.fetch("SELECT payment_id, status, amount_due, amount_paid FROM payments WHERE contract_id = $1", contract_id)
            self.assertEqual(len(payments), 2)
            paid_payment = next(p for p in payments if p["amount_paid"] > 0)
            due_payment = next(p for p in payments if p["amount_paid"] == 0)
            self.assertEqual(paid_payment["status"], "PAID")
            self.assertEqual(due_payment["status"], "DUE")

            # Verify commission exists
            comm = await self.conn.fetchrow("SELECT commission_id, status FROM commissions WHERE contract_id = $1", contract_id)
            self.assertEqual(comm["status"], "PENDING")

            # Step 3: Trigger CANCEL action on contract
            cancel_res = await WorkflowEngine.advance_contract_lifecycle(
                conn=self.conn,
                contract_id=contract_id,
                action="CANCEL",
                payload={"notes": "Cancelled per client mutual agreement"},
                user_id=self.agent_id
            )
            self.assertEqual(cancel_res["action"], "CANCEL")

            # Verify contract status
            c_status = await self.conn.fetchval("SELECT status FROM contracts WHERE contract_id = $1", contract_id)
            self.assertEqual(c_status, "CANCELLED")

            # Verify due payment is CANCELLED, while deposit remains PAID
            paid_after = await self.conn.fetchval("SELECT status FROM payments WHERE payment_id = $1", paid_payment["payment_id"])
            due_after = await self.conn.fetchval("SELECT status FROM payments WHERE payment_id = $1", due_payment["payment_id"])
            self.assertEqual(paid_after, "PAID")
            self.assertEqual(due_after, "CANCELLED")

            # Verify commission is CANCELLED
            comm_after = await self.conn.fetchval("SELECT status FROM commissions WHERE commission_id = $1", comm["commission_id"])
            self.assertEqual(comm_after, "CANCELLED")

            # Verify contract tasks are cancelled
            cancelled_tasks = await self.conn.fetch(
                """
                SELECT status FROM tasks 
                WHERE opportunity_id = $1 AND template_id IN ('TASK_CONTRACT_RECONCILIATION', 'TASK_CONTRACT_HANDOVER')
                """,
                opp_id
            )
            for t in cancelled_tasks:
                self.assertEqual(t["status"], "CANCELLED")

            # Verify unit status restored to AVAILABLE
            u_status = await self.conn.fetchval("SELECT status FROM units WHERE unit_id = $1", unit_id)
            self.assertEqual(u_status, "AVAILABLE")

        finally:
            await tr.rollback()


if __name__ == "__main__":
    unittest.main()
