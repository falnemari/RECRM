import unittest
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta, date

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

import asyncpg
from app.config import settings
from app.schemas.management import (
    TenancyCreateIn,
    WorkOrderCreateIn,
    ManagementContractCreateIn,
    OwnerYieldDistributionCalculateIn,
    OwnerYieldDistributionCreateIn,
    OwnerYieldDistributionPayoutIn
)
from app.schemas.marketing import (
    CampaignCreateIn,
    CampaignTrackingUrlGenerateIn,
    CampaignLeadAttachIn
)
from app.routers.management import (
    get_management_summary,
    list_tenancies,
    create_tenancy,
    create_work_order,
    approve_work_order,
    complete_work_order,
    create_management_contract,
    calculate_owner_yield_preview,
    create_owner_distribution,
    approve_owner_distribution,
    record_owner_distribution_payout,
    get_owner_distribution_statement_html
)
from app.routers.marketing import (
    create_campaign,
    get_campaign,
    generate_campaign_tracking_url,
    attach_lead_to_campaign_body,
    get_marketing_summary
)


class TestStage2Operations(unittest.IsolatedAsyncioTestCase):
    """
    Comprehensive Test Suite for Stage 2 Transition (المرحلة الثانية):
    1. Property & Facility Management (إدارة الأملاك والمرافق) & Saudi Ejar Tenancies
    2. Maintenance Tickets & Work Orders (الصيانة والتشغيل وتذاكر العمل) with 15% VAT & Cost Bearer
    3. Owners Relations & Yield Distributions (علاقات الملاك وتوزيعات العوائد الدورية)
    4. Marketing Campaign Automation & Digital Portals (أتمتة الحملات التسويقية وقنوات الإعلانات الرقمية)
    """

    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(settings.asyncpg_dsn)
        self.org_id = await self.conn.fetchval("SELECT organization_id FROM organizations LIMIT 1") or "organization-1"
        self.agent_id = await self.conn.fetchval(
            """
            SELECT u.user_id FROM users u 
            JOIN user_roles ur ON u.user_id = ur.user_id 
            JOIN roles r ON ur.role_id = r.role_id 
            WHERE r.role_code IN ('SALES_AGENT', 'SYS_ADMIN', 'PROPERTY_MANAGER') AND u.status = 'ACTIVE' 
            LIMIT 1
            """
        ) or "user-51"

        # Unique suffix for test isolation
        self.ts = uuid.uuid4().hex[:8]
        self.owner_id = f"test-st2-owner-{self.ts}"
        self.tenant_id = f"test-st2-tenant-{self.ts}"
        self.unit_id = f"test-st2-unit-{self.ts}"
        self.vendor_id = f"test-st2-vendor-{self.ts}"
        self.lead_id = f"test-st2-lead-{self.ts}"
        self.opp_id = f"test-st2-opp-{self.ts}"

        # 1. Seed Owner and Tenant
        await self.conn.execute(
            """
            INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status)
            VALUES ($1, $2, 'INDIVIDUAL', 'Sulaiman', 'Al-Owner', '+966551002001', 'ACTIVE'),
                   ($3, $2, 'INDIVIDUAL', 'Nasser', 'Al-Tenant', '+966551002002', 'ACTIVE')
            """,
            self.owner_id, self.org_id, self.tenant_id
        )

        # 2. Seed Unit
        bld_id = await self.conn.fetchval("SELECT building_id FROM buildings LIMIT 1") or "bld-1"
        pt_id = await self.conn.fetchval("SELECT property_type_id FROM property_types LIMIT 1") or "pt-1"
        await self.conn.execute(
            """
            INSERT INTO units (
                unit_id, building_id, property_type_id, unit_number, status, rent_price, owner_customer_id
            ) VALUES ($1, $2, $3, $4, 'AVAILABLE', 50000.0, $5)
            """,
            self.unit_id, bld_id, pt_id, f"U-ST2-{self.ts}", self.owner_id
        )

        # 3. Seed Vendor
        await self.conn.execute(
            """
            INSERT INTO vendors (vendor_id, organization_id, vendor_name, phone, status)
            VALUES ($1, $2, 'Al-Safwah Maintenance Est', '+966559988776', 'ACTIVE')
            """,
            self.vendor_id, self.org_id
        )

    async def asyncTearDown(self):
        # Strict cleanup of all test records to prevent test bloat
        try:
            # Clean activities and tasks first
            await self.conn.execute("DELETE FROM activities WHERE customer_id IN ($1, $2) OR lead_id = $3", self.owner_id, self.tenant_id, self.lead_id)
            await self.conn.execute("DELETE FROM tasks WHERE customer_id IN ($1, $2) OR lead_id = $3", self.owner_id, self.tenant_id, self.lead_id)
            await self.conn.execute("DELETE FROM document_access_log WHERE document_id IN (SELECT document_id FROM documents WHERE customer_id IN ($1, $2) OR unit_id = $3)", self.owner_id, self.tenant_id, self.unit_id)
            await self.conn.execute("DELETE FROM documents WHERE customer_id IN ($1, $2) OR unit_id = $3", self.owner_id, self.tenant_id, self.unit_id)

            # Marketing cleanups
            await self.conn.execute("DELETE FROM lead_events WHERE lead_id = $1", self.lead_id)
            await self.conn.execute("DELETE FROM campaign_leads WHERE lead_id = $1", self.lead_id)
            await self.conn.execute("DELETE FROM campaigns WHERE name LIKE $1", f"%Test-ST2-{self.ts}%")
            await self.conn.execute("DELETE FROM opportunities WHERE opportunity_id = $1", self.opp_id)
            await self.conn.execute("DELETE FROM leads WHERE lead_id = $1", self.lead_id)

            # Property Management cleanups
            await self.conn.execute("DELETE FROM owner_yield_distributions WHERE owner_customer_id = $1", self.owner_id)
            await self.conn.execute(
                "DELETE FROM maintenance_work_orders WHERE ticket_id IN (SELECT ticket_id FROM maintenance_tickets WHERE unit_id = $1)",
                self.unit_id
            )
            await self.conn.execute("DELETE FROM maintenance_tickets WHERE unit_id = $1", self.unit_id)
            await self.conn.execute("DELETE FROM vendors WHERE vendor_id = $1", self.vendor_id)
            await self.conn.execute("DELETE FROM rent_collections WHERE tenancy_id IN (SELECT tenancy_id FROM tenancies WHERE unit_id = $1)", self.unit_id)
            await self.conn.execute("DELETE FROM tenancies WHERE unit_id = $1", self.unit_id)
            await self.conn.execute("DELETE FROM managed_units WHERE unit_id = $1", self.unit_id)
            await self.conn.execute("DELETE FROM management_contracts WHERE customer_id = $1", self.owner_id)
            await self.conn.execute("DELETE FROM units WHERE unit_id = $1", self.unit_id)
            await self.conn.execute("DELETE FROM customers WHERE customer_id IN ($1, $2)", self.owner_id, self.tenant_id)
        except Exception as e:
            print(f"Error during asyncTearDown: {e}")
        finally:
            await self.conn.close()

    async def test_01_property_management_and_ejar_tenancies(self):
        """
        Verify Domain 1: Property & Facility Management
        - Creating management contract with managed unit.
        - Creating tenancy with Saudi Ejar contract number and type.
        - Confirming occupancy rate and managed units count in Management Summary.
        """
        # 1. Create Management Contract
        contract_payload = ManagementContractCreateIn(
            customer_id=self.owner_id,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            fee_type="PERCENT",
            fee_rate=5.0,
            unit_ids=[self.unit_id],
            status="ACTIVE"
        )
        contract_res = await create_management_contract(contract_payload, conn=self.conn)
        self.assertEqual(contract_res.data.customer_id, self.owner_id)
        self.assertEqual(contract_res.data.managed_units_count, 1)

        # 2. Create Tenancy with Saudi Ejar Metadata
        ejar_no = f"EJAR-TEST-{self.ts}"
        tenancy_payload = TenancyCreateIn(
            unit_id=self.unit_id,
            tenant_customer_id=self.tenant_id,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=365),
            rent_amount=50000.0,
            payment_frequency="ANNUAL",
            deposit_amount=2500.0,
            ejar_contract_number=ejar_no,
            contract_type="RESIDENTIAL",
            ejar_status="ACTIVE",
            security_deposit_status="HELD"
        )
        tenancy_res = await create_tenancy(tenancy_payload, x_user_id=self.agent_id, conn=self.conn)
        self.assertEqual(tenancy_res.data.ejar_contract_number, ejar_no)
        self.assertEqual(tenancy_res.data.contract_type, "RESIDENTIAL")
        self.assertEqual(tenancy_res.data.security_deposit_status, "HELD")

        # 3. Query Tenancies List
        list_res = await list_tenancies(page=1, page_size=50, search=ejar_no, conn=self.conn)
        self.assertGreaterEqual(list_res.meta.total, 1)
        found_tenancy = next((t for t in list_res.data if t.ejar_contract_number == ejar_no), None)
        self.assertIsNotNone(found_tenancy)
        self.assertEqual(found_tenancy.rent_amount, 50000.0)

        # 4. Check Management Summary KPIs
        summary_res = await get_management_summary(conn=self.conn)
        self.assertGreater(summary_res.data.total_managed_units, 0)
        self.assertGreater(summary_res.data.occupancy_rate, 0.0)

    async def test_02_maintenance_tickets_and_vat_work_orders(self):
        """
        Verify Domain 2: Maintenance Tickets & Work Orders
        - Create maintenance ticket for unit.
        - Create Work Order with cost_bearer = OWNER, 15% VAT auto-calculation.
        - Approve Work Order.
        - Complete Work Order -> verify ticket status transitions to RESOLVED.
        """
        # 1. Create Maintenance Ticket
        ticket_id = f"tkt-st2-{self.ts}"
        await self.conn.execute(
            """
            INSERT INTO maintenance_tickets (ticket_id, unit_id, reported_by_customer_id, category, priority, status, description)
            VALUES ($1, $2, $3, 'PLUMBING', 'HIGH', 'OPEN', 'تسريب مياه في دورة المياه الرئيسية')
            """,
            ticket_id, self.unit_id, self.tenant_id
        )

        # 2. Dispatch Work Order with 15% VAT and cost_bearer = OWNER
        wo_payload = WorkOrderCreateIn(
            ticket_id=ticket_id,
            vendor_id=self.vendor_id,
            assigned_user_id=self.agent_id,
            cost_bearer="OWNER",
            quoted_amount=2000.0,
            status="REQUESTED",
            notes="معالجة كسر أنبوب الصرف واستبدال القطع المتضررة"
        )
        wo_res = await create_work_order(ticket_id=ticket_id, payload=wo_payload, conn=self.conn)
        wo_id = wo_res.data.work_order_id
        self.assertEqual(wo_res.data.cost_bearer, "OWNER")
        self.assertEqual(wo_res.data.quoted_amount, 2000.0)
        self.assertEqual(wo_res.data.vat_amount, 300.0)   # 15% of 2000
        self.assertEqual(wo_res.data.total_amount, 2300.0) # 2000 + 300

        # Ticket status should now have advanced to IN_PROGRESS
        t_status = await self.conn.fetchval("SELECT status FROM maintenance_tickets WHERE ticket_id = $1", ticket_id)
        self.assertEqual(t_status, "IN_PROGRESS")

        # 3. Approve Work Order
        app_res = await approve_work_order(work_order_id=wo_id, approved_amount=2000.0, conn=self.conn)
        self.assertEqual(app_res.data["status"], "APPROVED")

        # 4. Complete Work Order -> Verifying ticket auto-resolution
        comp_res = await complete_work_order(work_order_id=wo_id, conn=self.conn)
        self.assertEqual(comp_res.data["status"], "COMPLETED")

        resolved_status = await self.conn.fetchval("SELECT status FROM maintenance_tickets WHERE ticket_id = $1", ticket_id)
        self.assertEqual(resolved_status, "RESOLVED", "Ticket must transition to RESOLVED when all work orders are completed")

    async def test_03_owner_yield_distribution_calculation_engine(self):
        """
        Verify Domain 3: Owner Relations & Yield Distributions
        - Management fee: 5%
        - Gross rent collected: 50,000 SAR
        - Approved owner maintenance expense: 2,000 SAR
        - Formula Check: Net Yield = 50,000 - 2,500 (5% fee) - 2,000 (wo) = 45,500 SAR
        """
        # 1. Create Management Contract (5% fee)
        mc_id = f"mc-st2-{self.ts}"
        await self.conn.execute(
            """
            INSERT INTO management_contracts (
                management_contract_id, customer_id, contract_number,
                start_date, end_date, fee_type, fee_rate, status
            ) VALUES ($1, $2, $3, CURRENT_DATE - 30, CURRENT_DATE + 335, 'PERCENT', 5.0, 'ACTIVE')
            """,
            mc_id, self.owner_id, f"MC-{self.ts}"
        )
        await self.conn.execute(
            "INSERT INTO managed_units (management_contract_id, unit_id) VALUES ($1, $2)",
            mc_id, self.unit_id
        )

        # 2. Seed Tenancy and Paid Rent Collection of 50,000 SAR
        tenancy_id = f"ten-st2-{self.ts}"
        await self.conn.execute(
            """
            INSERT INTO tenancies (
                tenancy_id, unit_id, tenant_customer_id, contract_number,
                start_date, end_date, rent_amount, payment_frequency, status
            ) VALUES ($1, $2, $3, $4, CURRENT_DATE - 30, CURRENT_DATE + 335, 50000.0, 'ANNUAL', 'ACTIVE')
            """,
            tenancy_id, self.unit_id, self.tenant_id, f"CON-ST2-{self.ts}"
        )
        await self.conn.execute(
            """
            INSERT INTO rent_collections (
                rent_collection_id, tenancy_id, amount_due,
                amount_paid, due_date, paid_at, status
            ) VALUES ($1, $2, 50000.0, 50000.0, CURRENT_DATE - 10, CURRENT_DATE - 5, 'PAID')
            """,
            f"rc-st2-{self.ts}", tenancy_id
        )

        # 3. Seed Completed Maintenance Work Order with cost_bearer = OWNER (2,000 SAR)
        ticket_id = f"tkt-st2-wo-{self.ts}"
        await self.conn.execute(
            """
            INSERT INTO maintenance_tickets (ticket_id, unit_id, category, priority, status, description)
            VALUES ($1, $2, 'ELECTRICAL', 'NORMAL', 'RESOLVED', 'صيانة دورية لقواطع الكهرباء')
            """,
            ticket_id, self.unit_id
        )
        await self.conn.execute(
            """
            INSERT INTO maintenance_work_orders (
                work_order_id, ticket_id, vendor_id, quoted_amount, approved_amount,
                vat_amount, total_amount, status, cost_bearer, completed_at
            ) VALUES ($1, $2, $3, 2000.0, 2000.0, 300.0, 2300.0, 'COMPLETED', 'OWNER', NOW() - INTERVAL '3 days')
            """,
            f"wo-st2-calc-{self.ts}", ticket_id, self.vendor_id
        )

        # 4. Preview Calculation via Engine
        calc_in = OwnerYieldDistributionCalculateIn(
            management_contract_id=mc_id,
            period_start=date.today() - timedelta(days=20),
            period_end=date.today() + timedelta(days=10),
            other_deductions=0.0
        )
        preview_res = await calculate_owner_yield_preview(calc_in, conn=self.conn)
        preview = preview_res.data

        self.assertEqual(preview.gross_rent_collected, 50000.0)
        self.assertEqual(preview.management_fee_rate, 5.0)
        self.assertEqual(preview.management_fee_amount, 2500.0) # 5% of 50000
        self.assertEqual(preview.maintenance_expenses_deducted, 2000.0) # approved amount
        self.assertEqual(preview.net_yield_amount, 45500.0) # 50000 - 2500 - 2000

    async def test_04_owner_yield_distribution_draft_approve_payout_and_statement(self):
        """
        Verify Domain 3 Lifecycle:
        - Create Draft Distribution
        - Approve Distribution
        - Record Bank Payout (status -> PAID)
        - Render Printable Owner Statement HTML
        """
        mc_id = f"mc-st2-dist-{self.ts}"
        await self.conn.execute(
            """
            INSERT INTO management_contracts (
                management_contract_id, customer_id, contract_number,
                start_date, end_date, fee_type, fee_rate, status
            ) VALUES ($1, $2, $3, CURRENT_DATE - 30, CURRENT_DATE + 335, 'PERCENT', 5.0, 'ACTIVE')
            """,
            mc_id, self.owner_id, f"MC-DIST-{self.ts}"
        )
        await self.conn.execute(
            "INSERT INTO managed_units (management_contract_id, unit_id) VALUES ($1, $2)",
            mc_id, self.unit_id
        )

        # 1. Create Distribution Draft
        create_payload = OwnerYieldDistributionCreateIn(
            management_contract_id=mc_id,
            period_start=date.today() - timedelta(days=30),
            period_end=date.today(),
            other_deductions=0.0,
            notes="دفعة عوائد الربع السنوي الأول"
        )
        dist_res = await create_owner_distribution(create_payload, conn=self.conn)
        dist_id = dist_res.data.distribution_id
        self.assertEqual(dist_res.data.status, "DRAFT")

        # 2. Approve Distribution
        app_res = await approve_owner_distribution(distribution_id=dist_id, conn=self.conn)
        self.assertEqual(app_res.data["status"], "APPROVED")

        # 3. Record Bank Payout
        payout_payload = OwnerYieldDistributionPayoutIn(
            payment_reference="TRX-BANK-998811",
            bank_name="Al-Rajhi Bank",
            iban="SA0380000000608010167519",
            notes="تم إيداع العائد بنجاح في الحساب البنكي للمالك"
        )
        payout_res = await record_owner_distribution_payout(dist_id, payout_payload, conn=self.conn)
        self.assertEqual(payout_res.data["status"], "PAID")
        self.assertEqual(payout_res.data["payment_reference"], "TRX-BANK-998811")

        # 4. Render Statement HTML
        html_res = await get_owner_distribution_statement_html(dist_id, conn=self.conn)
        html_str = html_res.body.decode("utf-8")
        self.assertIn("كشف حساب المالك وتوزيع العوائد", html_str)
        self.assertIn("TRX-BANK-998811", html_str)
        self.assertIn("Al-Rajhi Bank", html_str)
        self.assertIn("SA0380000000608010167519", html_str)

    async def test_05_marketing_campaigns_utm_attribution_and_roas(self):
        """
        Verify Domain 4: Marketing Campaigns Automation & Portals
        - Create Campaign on Saudi Portal 'AQAR'.
        - Generate smart UTM tracking URL.
        - Attribute Inbound Lead to Campaign.
        - Link Lead to Closed-Won Deal and verify ROAS calculation.
        """
        # 1. Create Campaign
        camp_payload = CampaignCreateIn(
            name=f"Test-ST2-{self.ts} North Riyadh Villas",
            channel="AQAR",
            budget=10000.0,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=30),
            status="ACTIVE"
        )
        camp_res = await create_campaign(camp_payload, conn=self.conn)
        camp_id = camp_res.data.campaign_id
        self.assertEqual(camp_res.data.channel, "AQAR")
        self.assertEqual(camp_res.data.budget, 10000.0)

        # 2. Generate Smart UTM Tracking URL
        utm_payload = CampaignTrackingUrlGenerateIn(
            base_url="https://recrm.sa/listings.html",
            unit_id=self.unit_id,
            custom_utm_content="front_banner"
        )
        trk_res = await generate_campaign_tracking_url(camp_id, utm_payload, conn=self.conn)
        self.assertIn("utm_source=aqar", trk_res.data.full_url)
        self.assertIn("unit_id=", trk_res.data.full_url)
        self.assertIn("utm_content=front_banner", trk_res.data.full_url)

        # 3. Seed Inbound Lead and Attribute to Campaign
        await self.conn.execute(
            """
            INSERT INTO leads (lead_id, organization_id, customer_id, inquiry_type, status, assigned_user_id)
            VALUES ($1, $2, $3, 'BUY', 'QUALIFIED', $4)
            """,
            self.lead_id, self.org_id, self.tenant_id, self.agent_id
        )

        attr_payload = CampaignLeadAttachIn(lead_id=self.lead_id)
        attr_res = await attach_lead_to_campaign_body(camp_id, attr_payload, conn=self.conn)
        self.assertEqual(attr_res.data.campaign_id, camp_id)
        self.assertEqual(attr_res.data.lead_id, self.lead_id)

        # 4. Create Closed-Won Opportunity for 100,000 SAR
        await self.conn.execute(
            """
            INSERT INTO opportunities (opportunity_id, lead_id, customer_id, stage, expected_value, assigned_user_id)
            VALUES ($1, $2, $3, 'CLOSED_WON', 100000.0, $4)
            """,
            self.opp_id, self.lead_id, self.tenant_id, self.agent_id
        )

        # 5. Fetch Campaign Details and Assert ROAS & CPL
        camp_detail = await get_campaign(camp_id, conn=self.conn)
        self.assertEqual(camp_detail.data.leads_count, 1)
        self.assertEqual(camp_detail.data.qualified_leads_count, 1)
        self.assertEqual(camp_detail.data.won_deals_count, 1)
        self.assertEqual(camp_detail.data.won_deals_value, 100000.0)
        # CPL: 10,000 budget / 1 lead = 10,000 SAR
        self.assertEqual(camp_detail.data.cost_per_lead, 10000.0)
        # ROAS: (100,000 won value / 10,000 budget) * 100 = 1000%
        self.assertEqual(camp_detail.data.roas, 1000.0)

        # 6. Check Marketing Summary
        m_summary = await get_marketing_summary(conn=self.conn)
        self.assertGreaterEqual(m_summary.data.total_won_deals_value, 100000.0)
        self.assertGreater(m_summary.data.overall_roas, 0.0)
        aqar_metric = next((c for c in m_summary.data.channel_breakdown if c.channel == "AQAR"), None)
        self.assertIsNotNone(aqar_metric)
        self.assertGreaterEqual(aqar_metric.total_leads, 1)


if __name__ == "__main__":
    unittest.main()
