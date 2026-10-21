import unittest
import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

import asyncpg
from app.config import settings
from app.services.workflow_engine import WorkflowEngine
from app.routers.finance import list_invoices, get_invoice, collect_invoice, generate_opportunity_fee_invoices
from app.routers.sales import update_opportunity
from app.schemas.contracts import CollectInvoiceIn, GenerateFeeInvoicesIn
from app.schemas.sales import OpportunityUpdate


class TestSaudiFeesAndInvoices(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(settings.asyncpg_dsn)
        self.org_id = await self.conn.fetchval("SELECT organization_id FROM organizations LIMIT 1")
        self.agent_id = await self.conn.fetchval(
            """
            SELECT u.user_id FROM users u 
            JOIN user_roles ur ON u.user_id = ur.user_id 
            JOIN roles r ON ur.role_id = r.role_id 
            WHERE r.role_code = 'SYS_ADMIN' AND u.status = 'ACTIVE' 
            LIMIT 1
            """
        ) or "user-51"

    async def asyncTearDown(self):
        await self.conn.close()

    async def test_rental_fee_invoices_generation_and_gating(self):
        """
        Verify Rental Deal:
        1. Generates Customer invoice (2.5% brokerage + 15% VAT).
        2. Generates Owner invoice (Ejar platform fee 125 SAR residential).
        3. Records activities ACT_INVOICE_GENERATED.
        4. Spawns TASK_COLLECT_SAUDI_FEES for Accountant.
        5. Gating: stage update to WON or tenancy activation is BLOCKED while invoices are PENDING.
        6. Once invoices are collected, gating passes and task is completed.
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            cust_id = "test-cust-fee-rent"
            owner_id = "test-owner-fee-rent"
            unit_id = "test-unit-fee-rent"
            lead_id = "test-lead-fee-rent"
            opp_id = "test-opp-fee-rent"

            # 1. Seed Customer and Owner
            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status)
                VALUES ($1, $2, 'INDIVIDUAL', 'Sultan', 'Al-Tenant', '+966551112233', 'ACTIVE'),
                       ($3, $2, 'INDIVIDUAL', 'Fahad', 'Al-Owner', '+966552223344', 'ACTIVE')
                """,
                cust_id, self.org_id, owner_id
            )

            # 2. Seed Unit (Residential)
            bld_id = await self.conn.fetchval("SELECT building_id FROM buildings LIMIT 1")
            pt_res = await self.conn.fetchval("SELECT property_type_id FROM property_types WHERE category = 'RESIDENTIAL' LIMIT 1")
            await self.conn.execute(
                """
                INSERT INTO units (unit_id, building_id, unit_number, property_type_id, status, rent_price, asking_price, owner_customer_id)
                VALUES ($1, $2, 'U-TEST-RENT-FEE', $3, 'AVAILABLE', 40000.0, 0.0, $4)
                """,
                unit_id, bld_id, pt_res, owner_id
            )

            # 3. Seed Lead and Opportunity (Rental 40,000 SAR)
            await self.conn.execute(
                """
                INSERT INTO leads (lead_id, organization_id, customer_id, inquiry_type, status, assigned_user_id)
                VALUES ($1, $2, $3, 'RENT', 'QUALIFIED', $4)
                """,
                lead_id, self.org_id, cust_id, self.agent_id
            )
            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, lead_id, customer_id, stage, expected_value, assigned_user_id)
                VALUES ($1, $2, $3, 'NEGOTIATION', 40000.0, $4)
                """,
                opp_id, lead_id, cust_id, self.agent_id
            )
            await self.conn.execute(
                "INSERT INTO opportunity_units (opportunity_id, unit_id) VALUES ($1, $2)",
                opp_id, unit_id
            )

            # 4. Generate Saudi Fee Invoices via Router Endpoint
            gen_res = await generate_opportunity_fee_invoices(
                opp_id=opp_id,
                payload=GenerateFeeInvoicesIn(buyer_brokerage_percent=2.5),
                x_user_id=self.agent_id,
                conn=self.conn
            )
            data = gen_res.data
            self.assertFalse(data["already_existed"])
            self.assertEqual(len(data["invoices"]), 2)

            cust_inv = next(i for i in data["invoices"] if i["payer_type"] == "CUSTOMER")
            owner_inv = next(i for i in data["invoices"] if i["payer_type"] == "OWNER")

            # Brokerage: 40,000 * 2.5% = 1,000 SAR. VAT: 15% of 1,000 = 150 SAR. Total = 1,150 SAR.
            self.assertEqual(cust_inv["subtotal"], 1000.0)
            self.assertEqual(cust_inv["vat_amount"], 150.0)
            self.assertEqual(cust_inv["total_amount"], 1150.0)

            # Ejar platform fee for residential: 125.00 SAR
            self.assertEqual(owner_inv["total_amount"], 125.0)

            # Check that TASK_COLLECT_SAUDI_FEES was created
            task_row = await self.conn.fetchrow(
                "SELECT * FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_COLLECT_SAUDI_FEES'",
                opp_id
            )
            self.assertIsNotNone(task_row)
            self.assertEqual(task_row["status"], "PENDING")

            # Check that ACT_INVOICE_GENERATED activities exist
            act_rows = await self.conn.fetch(
                "SELECT * FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_INVOICE_GENERATED'",
                opp_id
            )
            self.assertEqual(len(act_rows), 2)

            # 5. Verify GATING: Trying to update opportunity stage to WON should be blocked
            with self.assertRaises(ValueError) as ctx:
                await WorkflowEngine.verify_saudi_fees_collected(self.conn, opportunity_id=opp_id)
            self.assertIn("الفواتير غير المسددة", str(ctx.exception))

            # Also verify via Router update_opportunity: raises HTTP 400 with detail
            with self.assertRaises(HTTPException) as ctx_api:
                await update_opportunity(
                    opp_id=opp_id,
                    payload=OpportunityUpdate(stage="WON"),
                    conn=self.conn
                )
            self.assertEqual(ctx_api.exception.status_code, 400)
            self.assertIn("الفواتير غير المسددة", ctx_api.exception.detail)

            # 6. Verify GATING: Trying to execute tenancy agreement directly is blocked
            with self.assertRaises(ValueError) as ctx_ten:
                await WorkflowEngine.execute_tenancy_agreement(
                    conn=self.conn,
                    unit_id=unit_id,
                    tenant_customer_id=cust_id,
                    start_date="2026-11-01",
                    rent_amount=40000.0,
                    opportunity_id=opp_id,
                    lead_id=lead_id
                )
            self.assertIn("الفواتير غير المسددة", str(ctx_ten.exception))

            # 7. Collect Customer Invoice via router collect_invoice
            col_cust = await collect_invoice(
                invoice_id=cust_inv["invoice_id"],
                payload=CollectInvoiceIn(payment_method="BANK_TRANSFER", payment_reference="TRX-CUST-9999"),
                x_user_id=self.agent_id,
                conn=self.conn
            )
            self.assertEqual(col_cust.data.status, "PAID")

            # Check ACT_FEE_COLLECTED logged
            act_paid = await self.conn.fetch(
                "SELECT * FROM activities WHERE opportunity_id = $1 AND template_id = 'ACT_FEE_COLLECTED'",
                opp_id
            )
            self.assertEqual(len(act_paid), 1)

            # Still blocked because owner invoice is pending
            with self.assertRaises(ValueError):
                await WorkflowEngine.verify_saudi_fees_collected(self.conn, opportunity_id=opp_id)

            # 8. Collect Owner Invoice
            col_owner = await collect_invoice(
                invoice_id=owner_inv["invoice_id"],
                payload=CollectInvoiceIn(payment_method="MADA", payment_reference="TRX-OWNR-8888"),
                x_user_id=self.agent_id,
                conn=self.conn
            )
            self.assertEqual(col_owner.data.status, "PAID")

            # 9. Verify TASK_COLLECT_SAUDI_FEES automatically completed!
            task_updated = await self.conn.fetchrow(
                "SELECT * FROM tasks WHERE task_id = $1",
                task_row["task_id"]
            )
            self.assertEqual(task_updated["status"], "COMPLETED")

            # 10. Gating now PASSES cleanly
            gating_passed = await WorkflowEngine.verify_saudi_fees_collected(self.conn, opportunity_id=opp_id)
            self.assertTrue(gating_passed)

            # update_opportunity now succeeds
            res_patch_ok = await update_opportunity(
                opp_id=opp_id,
                payload=OpportunityUpdate(stage="WON"),
                conn=self.conn
            )
            self.assertEqual(res_patch_ok.data.stage, "WON")

            # 11. Situation API check: returns invoices and zero unpaid
            sit = await WorkflowEngine.get_entity_situation(self.conn, opportunity_id=opp_id)
            self.assertIn("invoices", sit)
            self.assertEqual(sit["invoices_count"], 2)
            self.assertEqual(sit["unpaid_invoices_count"], 0)
            self.assertFalse(sit["has_unpaid_statutory_fees"])

        finally:
            await tr.rollback()

    async def test_sale_fee_invoices_generation_rett_and_brokerage(self):
        """
        Verify Sale Deal:
        1. Customer: Brokerage commission 2.5% + 15% VAT.
        2. Owner: Real Estate Transaction Tax (RETT) 5% (ZATCA).
        """
        tr = self.conn.transaction()
        await tr.start()
        try:
            cust_id = "test-cust-sale"
            owner_id = "test-owner-sale"
            unit_id = "test-unit-sale"
            opp_id = "test-opp-sale"

            await self.conn.execute(
                """
                INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status)
                VALUES ($1, $2, 'INDIVIDUAL', 'Nasser', 'Al-Buyer', '+966553334455', 'ACTIVE'),
                       ($3, $2, 'INDIVIDUAL', 'Majed', 'Al-Seller', '+966554445566', 'ACTIVE')
                """,
                cust_id, self.org_id, owner_id
            )

            bld_id = await self.conn.fetchval("SELECT building_id FROM buildings LIMIT 1")
            await self.conn.execute(
                """
                INSERT INTO units (unit_id, building_id, unit_number, status, asking_price, owner_customer_id)
                VALUES ($1, $2, 'U-TEST-SALE-FEE', 'AVAILABLE', 1000000.0, $3)
                """,
                unit_id, bld_id, owner_id
            )

            await self.conn.execute(
                """
                INSERT INTO opportunities (opportunity_id, customer_id, stage, expected_value, assigned_user_id)
                VALUES ($1, $2, 'NEGOTIATION', 1000000.0, $3)
                """,
                opp_id, cust_id, self.agent_id
            )
            await self.conn.execute(
                "INSERT INTO opportunity_units (opportunity_id, unit_id) VALUES ($1, $2)",
                opp_id, unit_id
            )

            # Generate fee invoices for 1,000,000 SAR sale
            gen_res = await WorkflowEngine.generate_saudi_fee_invoices(
                conn=self.conn,
                opportunity_id=opp_id,
                transaction_type="SALE",
                deal_value=1000000.0,
                buyer_brokerage_percent=2.5,
                seller_brokerage_percent=0.0
            )

            cust_inv = next(i for i in gen_res["invoices"] if i["payer_type"] == "CUSTOMER")
            owner_inv = next(i for i in gen_res["invoices"] if i["payer_type"] == "OWNER")

            # Buyer: 25,000 brokerage + 3,750 VAT = 28,750 SAR
            self.assertEqual(cust_inv["subtotal"], 25000.0)
            self.assertEqual(cust_inv["vat_amount"], 3750.0)
            self.assertEqual(cust_inv["total_amount"], 28750.0)

            # Seller: RETT 5% on 1,000,000 = 50,000.00 SAR
            self.assertEqual(owner_inv["total_amount"], 50000.0)

            # Verify API endpoints: list_invoices
            res_list = await list_invoices(
                opportunity_id=opp_id,
                x_user_id=self.agent_id,
                conn=self.conn
            )
            self.assertEqual(len(res_list.data), 2)

            # Verify API Collect endpoint
            col_res = await collect_invoice(
                invoice_id=cust_inv["invoice_id"],
                payload=CollectInvoiceIn(payment_method="BANK_TRANSFER", payment_reference="BANK-REF-1234"),
                x_user_id=self.agent_id,
                conn=self.conn
            )
            self.assertEqual(col_res.data.status, "PAID")

        finally:
            await tr.rollback()

