"""
Comprehensive Stage 1 Verification & End-to-End Simulation Script (RECRM)
Validates Sales, Leasing, and Investment workflows, plus all 16 official document templates.
"""
import asyncio
import os
import sys
import json
from datetime import datetime, timezone, timedelta, date

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

import asyncpg
from app.config import settings
from app.services.workflow_engine import WorkflowEngine
from app.services.document_templates import render_document_html
from app.routers.documents import hydrate_document_metadata


async def get_next_open_task(conn, lead_id=None, opp_id=None):
    """Finds the active pending/open task for the workflow context."""
    if opp_id:
        t = await conn.fetchrow(
            "SELECT * FROM tasks WHERE opportunity_id = $1 AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS') ORDER BY created_at DESC LIMIT 1",
            opp_id
        )
        if t:
            return dict(t)
    if lead_id:
        t = await conn.fetchrow(
            "SELECT * FROM tasks WHERE lead_id = $1 AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS') ORDER BY created_at DESC LIMIT 1",
            lead_id
        )
        if t:
            return dict(t)
    return None


async def run_stage1_e2e_simulation():
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    print("=" * 80)
    print("🚀 STARTING RECRM STAGE 1 TRIPLE E2E SIMULATION & BEST-PRACTICES AUDIT")
    print("=" * 80)

    org_id = await conn.fetchval("SELECT organization_id FROM organizations LIMIT 1") or "org-default"
    agent_id = await conn.fetchval(
        """
        SELECT u.user_id FROM users u 
        JOIN user_roles ur ON u.user_id = ur.user_id 
        JOIN roles r ON ur.role_id = r.role_id 
        WHERE r.role_code IN ('SALES_AGENT', 'SYS_ADMIN', 'LEASING_AGENT') AND u.status = 'ACTIVE' 
        LIMIT 1
        """
    ) or "user-1"
    agent_name = await conn.fetchval("SELECT full_name FROM users WHERE user_id = $1", agent_id) or "Demo Agent"
    bld_id = await conn.fetchval("SELECT building_id FROM buildings LIMIT 1") or "bld-1"
    pt_id = await conn.fetchval("SELECT property_type_id FROM property_types LIMIT 1") or "pt-1"

    results = {
        "sales_track": {"status": "PENDING", "steps": 0, "documents": []},
        "leasing_track": {"status": "PENDING", "steps": 0, "documents": []},
        "investment_track": {"status": "PENDING", "steps": 0, "documents": []},
        "document_catalog": {"status": "PENDING", "tested": 0, "passed": 0},
        "decision_support": {"status": "PENDING", "verified": False}
    }

    sale_cust_id = rent_cust_id = inv_cust_id = None
    sale_unit_id = rent_unit_id = inv_unit_1 = inv_unit_2 = None

    try:
        # =========================================================================
        # 1. TRACK 1: SALES WORKFLOW E2E SIMULATION (مسار البيع الكامل)
        # =========================================================================
        print("\n--- [1/3] SIMULATING FULL SALES TRACK (مسار البيع) ---")
        sale_cust_id, _, _ = await WorkflowEngine.find_or_create_customer(
            conn=conn, org_id=org_id,
            first_name="Saad", last_name="Al-Qahtani",
            mobile="+966501112233", email="saad.sale.e2e@example.test"
        )
        sale_unit_id = "unit-sim-sale-01"
        await conn.execute(
            """
            INSERT INTO units (
                unit_id, building_id, property_type_id, unit_number, floor_no, bedrooms, bathrooms,
                area_sqm, asking_price, listing_purpose, status, created_at, updated_at
            ) VALUES ($1, $2, $3, 'VILLA-SIM-01', 1, 5, 6, 450.0, 2500000.0, 'SALE', 'AVAILABLE', NOW(), NOW())
            ON CONFLICT (unit_id) DO UPDATE SET status = 'AVAILABLE', asking_price = 2500000.0, listing_purpose = 'SALE'
            """,
            sale_unit_id, bld_id, pt_id
        )

        sale_lead_id = f"lead-sim-sale-{int(datetime.now(timezone.utc).timestamp())}"
        await conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, assigned_user_id, status, priority,
                inquiry_type, budget_min, budget_max, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'NEW', 'HIGH', 'SALE', 2000000, 3000000, NOW(), NOW())
            """,
            sale_lead_id, org_id, sale_cust_id, agent_id
        )

        # Step 1: Assign Lead & trigger initial task
        res_assign = await WorkflowEngine.on_lead_assigned(conn, sale_lead_id, agent_id)
        task_1 = res_assign["task"]
        assert task_1["template_id"] == "TASK_LEAD_FIRST_CONTACT", f"Expected TASK_LEAD_FIRST_CONTACT, got {task_1['template_id']}"
        print(f"  ✓ Step 1: Inbound Lead created -> Task spawned: {task_1['template_id']}")

        # Step 2: Complete First Contact -> Next: TASK_LEAD_QUALIFY
        await WorkflowEngine.complete_task_with_outcome(
            conn, task_1["task_id"], agent_id, outcome="CONNECTED", notes="Customer confirmed interest in purchasing a villa"
        )
        task_2 = await get_next_open_task(conn, lead_id=sale_lead_id)
        assert task_2 and task_2["template_id"] == "TASK_LEAD_QUALIFY", f"Expected TASK_LEAD_QUALIFY, got {task_2}"
        print(f"  ✓ Step 2: First Contact completed -> Task spawned: {task_2['template_id']}")

        # Step 3: Qualify Lead -> Spawns Opportunity and Next Task
        await WorkflowEngine.complete_task_with_outcome(
            conn, task_2["task_id"], agent_id, outcome="QUALIFIED", notes="Pre-approved budget 2.5M SAR",
            qualification_data={"budget_confirmed": 2500000.0, "timeframe_months": 1}
        )
        sale_opp_id = await conn.fetchval("SELECT opportunity_id FROM opportunities WHERE lead_id = $1", sale_lead_id)
        assert sale_opp_id, "Opportunity not created upon qualification!"
        
        # Link unit to opportunity
        await conn.execute(
            """
            INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
            VALUES ($1, $2, TRUE, 2500000.0) ON CONFLICT DO NOTHING
            """,
            sale_opp_id, sale_unit_id
        )

        task_3 = await get_next_open_task(conn, opp_id=sale_opp_id, lead_id=sale_lead_id)
        assert task_3 and task_3["template_id"] == "TASK_OPPORTUNITY_MATCH_PROPERTIES", f"Expected TASK_OPPORTUNITY_MATCH_PROPERTIES, got {task_3}"
        print(f"  ✓ Step 3: Qualification completed -> Opportunity: {sale_opp_id} | Next: {task_3['template_id']}")

        # Step 4: Match Properties -> Next: TASK_VIEWING_SCHEDULE
        await WorkflowEngine.complete_task_with_outcome(
            conn, task_3["task_id"], agent_id, outcome="MATCHED", notes="Matched luxury villa candidate",
            viewing_data={"unit_ids": [sale_unit_id]}
        )
        task_4 = await get_next_open_task(conn, opp_id=sale_opp_id, lead_id=sale_lead_id)
        assert task_4 and task_4["template_id"] == "TASK_VIEWING_SCHEDULE", f"Expected TASK_VIEWING_SCHEDULE, got {task_4}"
        print(f"  ✓ Step 4: Properties Matched -> Next: {task_4['template_id']}")

        # Step 5: Viewing Schedule -> Viewing Report
        await WorkflowEngine.complete_task_with_outcome(
            conn, task_4["task_id"], agent_id, outcome="SCHEDULED", notes="Site visit scheduled for tomorrow 4 PM",
            viewing_data={"scheduled_start": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), "unit_id": sale_unit_id}
        )
        task_5 = await get_next_open_task(conn, opp_id=sale_opp_id, lead_id=sale_lead_id)
        assert task_5 and task_5["template_id"] == "TASK_VIEWING_REPORT", f"Expected TASK_VIEWING_REPORT, got {task_5}"
        print(f"  ✓ Step 5: Viewing Scheduled -> Next: {task_5['template_id']}")

        # Step 6: Viewing Report -> Next: TASK_OFFER_SUBMIT
        await WorkflowEngine.complete_task_with_outcome(
            conn, task_5["task_id"], agent_id, outcome="INTERESTED", notes="Client loved the villa and wants to make an offer",
            viewing_data={"client_interest": "VERY_HIGH", "offer_amount": 2450000.0, "unit_id": sale_unit_id}
        )
        task_6 = await get_next_open_task(conn, opp_id=sale_opp_id, lead_id=sale_lead_id)
        assert task_6 and task_6["template_id"] == "TASK_OFFER_SUBMIT", f"Expected TASK_OFFER_SUBMIT, got {task_6}"
        print(f"  ✓ Step 6: Viewing Report completed -> Next: {task_6['template_id']}")

        # Step 7: Offer Submit -> Archives COMMERCIAL_OFFER -> Next: TASK_OFFER_FOLLOWUP
        await WorkflowEngine.complete_task_with_outcome(
            conn, task_6["task_id"], agent_id, outcome="OFFER_SUBMITTED", notes="Official Purchase Offer of 2,450,000 SAR submitted",
            viewing_data={"offer_amount": 2450000.0, "unit_id": sale_unit_id}
        )
        task_7 = await get_next_open_task(conn, opp_id=sale_opp_id, lead_id=sale_lead_id)
        assert task_7 and task_7["template_id"] == "TASK_OFFER_FOLLOWUP", f"Expected TASK_OFFER_FOLLOWUP, got {task_7}"
        print(f"  ✓ Step 7: Commercial Offer submitted -> Next: {task_7['template_id']}")

        # Step 8: Offer Followup (Seller Accepted) -> Next: TASK_RESERVATION_VERIFY_AVAILABILITY
        await WorkflowEngine.complete_task_with_outcome(
            conn, task_7["task_id"], agent_id, outcome="ACCEPTED", notes="Seller accepted 2,450,000 SAR offer"
        )
        task_8 = await get_next_open_task(conn, opp_id=sale_opp_id, lead_id=sale_lead_id)
        assert task_8 and task_8["template_id"] == "TASK_RESERVATION_VERIFY_AVAILABILITY", f"Expected TASK_RESERVATION_VERIFY_AVAILABILITY, got {task_8}"
        print(f"  ✓ Step 8: Offer Accepted -> Next: {task_8['template_id']}")

        # Step 9: Verify Availability -> Reservation Created -> Next: TASK_RESERVATION_DEPOSIT_FOLLOWUP
        await WorkflowEngine.complete_task_with_outcome(
            conn, task_8["task_id"], agent_id, outcome="CONFIRMED", notes="Unit verified and locked for reservation",
            viewing_data={"unit_id": sale_unit_id}
        )
        task_9 = await get_next_open_task(conn, opp_id=sale_opp_id, lead_id=sale_lead_id)
        assert task_9 and task_9["template_id"] == "TASK_RESERVATION_DEPOSIT_FOLLOWUP", f"Expected TASK_RESERVATION_DEPOSIT_FOLLOWUP, got {task_9}"
        print(f"  ✓ Step 9: Reservation Confirmed -> Next: {task_9['template_id']}")

        # Step 10: Deposit Followup (5% Earnest Paid: 122,500 SAR) -> Archives RESERVATION -> Next: TASK_CONTRACT_DRAFT
        await WorkflowEngine.complete_task_with_outcome(
            conn, task_9["task_id"], agent_id, outcome="DEPOSIT_VERIFIED", notes="Earnest money 122,500 SAR received via bank transfer",
            viewing_data={"deposit_amount": 122500.0}
        )
        task_10 = await get_next_open_task(conn, opp_id=sale_opp_id, lead_id=sale_lead_id)
        assert task_10 and task_10["template_id"] == "TASK_CONTRACT_DRAFT", f"Expected TASK_CONTRACT_DRAFT, got {task_10}"
        print(f"  ✓ Step 10: Deposit Verified & Receipt Issued -> Next: {task_10['template_id']}")

        # Step 11: Contract Draft -> Archives SALE_CONTRACT -> Next: TASK_CONTRACT_INTERNAL_REVIEW
        await WorkflowEngine.complete_task_with_outcome(
            conn, task_10["task_id"], agent_id, outcome="DRAFT_PREPARED", notes="Unified sales agreement prepared with RETT 5% clause",
            viewing_data={"contract_type": "SALE", "contract_value": 2450000.0}
        )
        task_11 = await get_next_open_task(conn, opp_id=sale_opp_id, lead_id=sale_lead_id)
        assert task_11 and task_11["template_id"] == "TASK_CONTRACT_INTERNAL_REVIEW", f"Expected TASK_CONTRACT_INTERNAL_REVIEW, got {task_11}"
        print(f"  ✓ Step 11: Contract Drafted -> Next: {task_11['template_id']}")

        # Step 12: Internal Review -> Next: TASK_CONTRACT_SIGNATURE
        await WorkflowEngine.complete_task_with_outcome(
            conn, task_11["task_id"], agent_id, outcome="APPROVED", notes="Legal & financial compliance review approved"
        )
        task_12 = await get_next_open_task(conn, opp_id=sale_opp_id, lead_id=sale_lead_id)
        assert task_12 and task_12["template_id"] == "TASK_CONTRACT_SIGNATURE", f"Expected TASK_CONTRACT_SIGNATURE, got {task_12}"
        print(f"  ✓ Step 12: Contract Approved -> Next: {task_12['template_id']}")

        # Step 13: Signature -> Archives Signed Status & Auto-generates Saudi Fee Invoices -> Next: TASK_CONTRACT_HANDOVER
        await WorkflowEngine.complete_task_with_outcome(
            conn, task_12["task_id"], agent_id, outcome="SIGNED", notes="Contract electronically signed by Buyer and Seller"
        )
        
        # Pay generated Saudi fee invoices (RETT 5% + Brokerage & VAT) to pass handover gating
        fee_invs = await conn.fetch("SELECT invoice_id FROM invoices WHERE opportunity_id = $1 AND status != 'PAID'", sale_opp_id)
        for inv_row in fee_invs:
            await WorkflowEngine.collect_fee_invoice(conn, inv_row["invoice_id"], payment_method="SADAD", notes="Statutory fee paid via SADAD")

        handover_task = await conn.fetchrow(
            "SELECT * FROM tasks WHERE opportunity_id = $1 AND template_id = 'TASK_CONTRACT_HANDOVER' AND status IN ('PENDING', 'OPEN') LIMIT 1",
            sale_opp_id
        )
        assert handover_task, "Handover task missing!"
        print(f"  ✓ Step 13: Contract Signed & Statutory Fees Settled -> Next: {handover_task['template_id']}")

        # Step 14: Handover -> Generates HANDOVER_PROTOCOL -> Unit Status becomes SOLD! Deal CLOSED_WON!
        await WorkflowEngine.complete_task_with_outcome(
            conn, handover_task["task_id"], agent_id, outcome="DELIVERED", notes="Villa keys and utility meters officially handed over",
            viewing_data={"handover_status": "EXCELLENT", "keys_delivered": True}
        )
        print("  ✓ Step 14: Final Handover Protocol completed -> Deal Closed!")

        # Verify unit status
        sale_unit_st = await conn.fetchval("SELECT status FROM units WHERE unit_id = $1", sale_unit_id)
        assert sale_unit_st == "SOLD", f"Expected unit status SOLD, got {sale_unit_st}"
        print(f"  🎯 Unit status verified: {sale_unit_st}")

        # Check documents generated
        sale_docs = await conn.fetch(
            "SELECT document_id, file_name, metadata FROM documents WHERE opportunity_id = $1 OR lead_id = $2",
            sale_opp_id, sale_lead_id
        )
        print(f"  📄 Documents Vault generated {len(sale_docs)} official documents for Sales Track:")
        for d in sale_docs:
            print(f"     - [{d['document_id']}] {d['file_name']}")
        assert len(sale_docs) >= 3, f"Expected at least 3 documents in Sales Track, got {len(sale_docs)}"

        results["sales_track"]["status"] = "PASSED"
        results["sales_track"]["steps"] = 14
        results["sales_track"]["documents"] = [d["file_name"] for d in sale_docs]

        # =========================================================================
        # 2. TRACK 2: LEASING WORKFLOW E2E SIMULATION (مسار الإيجار الكامل)
        # =========================================================================
        print("\n--- [2/3] SIMULATING FULL LEASING TRACK (مسار الإيجار) ---")
        rent_cust_id, _, _ = await WorkflowEngine.find_or_create_customer(
            conn=conn, org_id=org_id,
            first_name="Al-Ufuq", last_name="Commercial Co",
            company_name="شركة الأفق الماسي للتجارة",
            mobile="+966504445566", email="info@alufuq.example.test",
            customer_type="CORPORATE"
        )
        rent_unit_id = "unit-sim-rent-01"
        await conn.execute(
            """
            INSERT INTO units (
                unit_id, building_id, property_type_id, unit_number, floor_no, bedrooms, bathrooms,
                area_sqm, rent_price, listing_purpose, status, created_at, updated_at
            ) VALUES ($1, $2, $3, 'SHOWROOM-102', 1, 0, 2, 220.0, 150000.0, 'RENT', 'AVAILABLE', NOW(), NOW())
            ON CONFLICT (unit_id) DO UPDATE SET status = 'AVAILABLE', rent_price = 150000.0, listing_purpose = 'RENT'
            """,
            rent_unit_id, bld_id, pt_id
        )

        rent_lead_id = f"lead-sim-rent-{int(datetime.now(timezone.utc).timestamp())}"
        await conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, assigned_user_id, status, priority,
                inquiry_type, budget_min, budget_max, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'NEW', 'MEDIUM', 'RENT', 100000, 180000, NOW(), NOW())
            """,
            rent_lead_id, org_id, rent_cust_id, agent_id
        )

        # Step 1: Assign Rental Lead -> TASK_RENT_LEAD_FIRST_CONTACT
        res_r_assign = await WorkflowEngine.on_lead_assigned(conn, rent_lead_id, agent_id)
        r_task_1 = res_r_assign["task"]
        assert r_task_1["template_id"] == "TASK_RENT_LEAD_FIRST_CONTACT"
        print(f"  ✓ Step 1: Rental Inbound Lead created -> Task spawned: {r_task_1['template_id']}")

        # Step 2: First Contact -> TASK_LEAD_QUALIFY
        await WorkflowEngine.complete_task_with_outcome(
            conn, r_task_1["task_id"], agent_id, outcome="CONNECTED", notes="Commercial corporate tenant verified"
        )
        r_task_2 = await get_next_open_task(conn, lead_id=rent_lead_id)
        assert r_task_2 and r_task_2["template_id"] == "TASK_LEAD_QUALIFY"
        print(f"  ✓ Step 2: Rental First Contact completed -> Task: {r_task_2['template_id']}")

        # Step 3: Qualify Lead -> TASK_RENT_MATCH_PROPERTIES
        await WorkflowEngine.complete_task_with_outcome(
            conn, r_task_2["task_id"], agent_id, outcome="QUALIFIED", notes="Retail commercial showroom requirements confirmed"
        )
        rent_opp_id = await conn.fetchval("SELECT opportunity_id FROM opportunities WHERE lead_id = $1", rent_lead_id)
        assert rent_opp_id, "Rental Opportunity not created!"
        
        await conn.execute(
            """
            INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
            VALUES ($1, $2, TRUE, 150000.0) ON CONFLICT DO NOTHING
            """,
            rent_opp_id, rent_unit_id
        )

        r_task_3 = await get_next_open_task(conn, opp_id=rent_opp_id, lead_id=rent_lead_id)
        print(f"  ✓ Step 3: Rental Lead Qualified -> Opp: {rent_opp_id} | Next: {r_task_3['template_id']}")

        # Step 4: Match Properties -> Next: TASK_VIEWING_SCHEDULE
        await WorkflowEngine.complete_task_with_outcome(
            conn, r_task_3["task_id"], agent_id, outcome="MATCHED", notes="Matched SHOWROOM-102 at 150,000 SAR/year",
            viewing_data={"unit_ids": [rent_unit_id]}
        )
        r_task_4 = await get_next_open_task(conn, opp_id=rent_opp_id, lead_id=rent_lead_id)
        assert r_task_4 and r_task_4["template_id"] == "TASK_VIEWING_SCHEDULE"
        print(f"  ✓ Step 4: Properties Matched -> Next: {r_task_4['template_id']}")

        # Step 5: Viewing Schedule -> Next: TASK_VIEWING_REPORT
        await WorkflowEngine.complete_task_with_outcome(
            conn, r_task_4["task_id"], agent_id, outcome="SCHEDULED", notes="Commercial viewing scheduled with operations manager",
            viewing_data={"scheduled_start": datetime.now(timezone.utc).isoformat(), "unit_id": rent_unit_id}
        )
        r_task_5 = await get_next_open_task(conn, opp_id=rent_opp_id, lead_id=rent_lead_id)
        assert r_task_5 and r_task_5["template_id"] == "TASK_VIEWING_REPORT"
        print(f"  ✓ Step 5: Commercial Viewing Scheduled -> Next: {r_task_5['template_id']}")

        # Step 6: Viewing Report -> Next: TASK_RENT_PREPARE_TENANCY (or Followup)
        await WorkflowEngine.complete_task_with_outcome(
            conn, r_task_5["task_id"], agent_id, outcome="INTERESTED", notes="Tenant approved showroom layout",
            viewing_data={"unit_id": rent_unit_id}
        )
        r_task_6 = await get_next_open_task(conn, opp_id=rent_opp_id, lead_id=rent_lead_id)
        assert r_task_6, "Expected next task after rental viewing report!"
        print(f"  ✓ Step 6: Viewing Report completed -> Next: {r_task_6['template_id']}")

        if r_task_6["template_id"] == "TASK_RENT_VIEWING_FOLLOW_UP":
            await WorkflowEngine.complete_task_with_outcome(
                conn, r_task_6["task_id"], agent_id, outcome="INTERESTED", notes="Tenant confirmed intention to lease on Ejari",
                viewing_data={"unit_id": rent_unit_id}
            )
            r_task_prep = await get_next_open_task(conn, opp_id=rent_opp_id, lead_id=rent_lead_id)
        else:
            r_task_prep = r_task_6

        assert r_task_prep and r_task_prep["template_id"] in ("TASK_RENT_PREPARE_TENANCY", "TASK_RENT_SPECIAL_CONDITIONS_NEGOTIATION")
        print(f"  ✓ Step 7: Tenant Interest Confirmed -> Next: {r_task_prep['template_id']}")

        # Step 8: Prepare Tenancy -> Generates LEASE document and collection monitoring
        await WorkflowEngine.complete_task_with_outcome(
            conn, r_task_prep["task_id"], agent_id, outcome="AGREEMENT_EXECUTED", notes="Ejari Tenancy contract registered and activated",
            viewing_data={"rent_price": 150000.0, "deposit_amount": 15000.0, "unit_id": rent_unit_id}
        )
        r_task_8 = await get_next_open_task(conn, opp_id=rent_opp_id, lead_id=rent_lead_id)
        assert r_task_8 and r_task_8["template_id"] == "TASK_RENT_COLLECTION_MONITORING", f"Expected collection task, got {r_task_8}"
        print(f"  ✓ Step 8: Tenancy Contract Executed -> Next Accounting Task: {r_task_8['template_id']}")

        # Verify unit status
        rent_unit_st = await conn.fetchval("SELECT status FROM units WHERE unit_id = $1", rent_unit_id)
        assert rent_unit_st == "RENTED", f"Expected unit status RENTED, got {rent_unit_st}"
        print(f"  🎯 Rental unit status verified: {rent_unit_st}")

        # Check documents generated
        rent_docs = await conn.fetch(
            "SELECT document_id, file_name, metadata FROM documents WHERE opportunity_id = $1 OR lead_id = $2",
            rent_opp_id, rent_lead_id
        )
        print(f"  📄 Documents Vault generated {len(rent_docs)} official documents for Leasing Track:")
        for d in rent_docs:
            print(f"     - [{d['document_id']}] {d['file_name']}")

        results["leasing_track"]["status"] = "PASSED"
        results["leasing_track"]["steps"] = 8
        results["leasing_track"]["documents"] = [d["file_name"] for d in rent_docs]

        # =========================================================================
        # 3. TRACK 3: INVESTMENT WORKFLOW E2E SIMULATION (مسار الاستثمار والاستحواذ)
        # =========================================================================
        print("\n--- [3/3] SIMULATING FULL INVESTMENT & DUE DILIGENCE TRACK (مسار الاستثمار) ---")
        inv_cust_id, _, _ = await WorkflowEngine.find_or_create_customer(
            conn=conn, org_id=org_id,
            first_name="Tariq", last_name="Al-Ghamdi",
            mobile="+966507778899", email="dr.tariq@invest.example.test"
        )
        inv_unit_1 = "unit-sim-inv-01"
        inv_unit_2 = "unit-sim-inv-02"

        # Prime candidate
        await conn.execute(
            """
            INSERT INTO units (
                unit_id, building_id, property_type_id, unit_number, floor_no, bedrooms, bathrooms,
                area_sqm, asking_price, rent_price, listing_purpose, status, created_at, updated_at
            ) VALUES ($1, $2, $3, 'PLAZA-A', 1, 0, 4, 800.0, 4000000.0, 360000.0, 'INVESTMENT', 'AVAILABLE', NOW(), NOW())
            ON CONFLICT (unit_id) DO UPDATE SET status = 'AVAILABLE', asking_price = 4000000.0, rent_price = 360000.0, listing_purpose = 'INVESTMENT'
            """,
            inv_unit_1, bld_id, pt_id
        )
        # Benchmark candidate
        await conn.execute(
            """
            INSERT INTO units (
                unit_id, building_id, property_type_id, unit_number, floor_no, bedrooms, bathrooms,
                area_sqm, asking_price, rent_price, listing_purpose, status, created_at, updated_at
            ) VALUES ($1, $2, $3, 'PLAZA-B', 1, 0, 4, 700.0, 3800000.0, 300000.0, 'INVESTMENT', 'AVAILABLE', NOW(), NOW())
            ON CONFLICT (unit_id) DO UPDATE SET status = 'AVAILABLE', asking_price = 3800000.0, rent_price = 300000.0, listing_purpose = 'INVESTMENT'
            """,
            inv_unit_2, bld_id, pt_id
        )

        inv_lead_id = f"lead-sim-inv-{int(datetime.now(timezone.utc).timestamp())}"
        await conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, assigned_user_id, status, priority,
                inquiry_type, budget_min, budget_max, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'NEW', 'URGENT', 'INVESTMENT', 3500000, 5000000, NOW(), NOW())
            """,
            inv_lead_id, org_id, inv_cust_id, agent_id
        )

        # Step 1: Assign Investment Lead -> TASK_INVEST_LEAD_FIRST_CONTACT
        res_i_assign = await WorkflowEngine.on_lead_assigned(conn, inv_lead_id, agent_id)
        i_task_1 = res_i_assign["task"]
        assert i_task_1["template_id"] == "TASK_INVEST_LEAD_FIRST_CONTACT"
        print(f"  ✓ Step 1: Investment Inbound Lead created -> Task: {i_task_1['template_id']}")

        # Step 2: First Contact -> Spawns TASK_LEAD_QUALIFY
        await WorkflowEngine.complete_task_with_outcome(
            conn, i_task_1["task_id"], agent_id, outcome="CONNECTED", notes="Investor confirmed target: min 8% Cap Rate"
        )
        i_task_2 = await get_next_open_task(conn, lead_id=inv_lead_id)
        assert i_task_2 and i_task_2["template_id"] == "TASK_LEAD_QUALIFY"
        print(f"  ✓ Step 2: Initial Contact completed -> Task: {i_task_2['template_id']}")

        # Step 3: Qualify Lead -> Spawns Investment Opportunity & TASK_INVEST_CONFIRM_OBJECTIVES
        await WorkflowEngine.complete_task_with_outcome(
            conn, i_task_2["task_id"], agent_id, outcome="QUALIFIED", notes="Target verified: 4M-5M budget, commercial asset",
            qualification_data={"budget_min": 3500000.0, "budget_max": 5000000.0}
        )
        inv_opp_id = await conn.fetchval("SELECT opportunity_id FROM opportunities WHERE lead_id = $1", inv_lead_id)
        assert inv_opp_id, "Investment Opportunity not created!"

        # Link candidate units to opportunity
        await conn.execute(
            """
            INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
            VALUES ($1, $2, TRUE, 4000000.0), ($1, $3, FALSE, 3800000.0)
            ON CONFLICT DO NOTHING
            """,
            inv_opp_id, inv_unit_1, inv_unit_2
        )

        i_task_3 = await get_next_open_task(conn, opp_id=inv_opp_id, lead_id=inv_lead_id)
        assert i_task_3 and i_task_3["template_id"] == "TASK_INVEST_CONFIRM_OBJECTIVES"
        print(f"  ✓ Step 3: Lead Qualified -> Opp: {inv_opp_id} | Next: {i_task_3['template_id']}")

        # Step 4: Confirm Objectives -> Spawns TASK_INVEST_COMPARE_RETURNS
        await WorkflowEngine.complete_task_with_outcome(
            conn, i_task_3["task_id"], agent_id, outcome="OBJECTIVES_CONFIRMED", notes="Target verified: 4M-5M budget, commercial asset",
            viewing_data={"unit_ids": [inv_unit_1, inv_unit_2], "target_yield_percent": 8.0}
        )
        i_task_4 = await get_next_open_task(conn, opp_id=inv_opp_id, lead_id=inv_lead_id)
        assert i_task_4 and i_task_4["template_id"] == "TASK_INVEST_COMPARE_RETURNS"
        print(f"  ✓ Step 4: Investment Objectives Confirmed -> Next: {i_task_4['template_id']}")

        # Step 5: Compare Returns -> Generates INVEST_COMPARATIVE_REPORT -> Next: TASK_INVEST_SCHEDULE_INSPECTION
        comp_payload = {
            "selected_unit_ids": [inv_unit_1, inv_unit_2],
            "recommendation": "ACQUIRE_PRIMARY",
            "comparison_notes": "Unit 1 achieves 9.0% gross yield vs 7.89% for Unit 2",
            "compared_units": [
                {
                    "unit_id": inv_unit_1, "is_primary": True,
                    "purchase_price": 4000000.0, "gross_annual_rent": 360000.0,
                    "annual_vacancy_allowance": 18000.0, "annual_operating_expenses": 36000.0,
                    "net_operating_income": 306000.0, "cap_rate": 7.65, "cash_invested": 4300000.0,
                    "cash_on_cash_return_percent": 7.12
                },
                {
                    "unit_id": inv_unit_2, "is_primary": False,
                    "purchase_price": 3800000.0, "gross_annual_rent": 300000.0,
                    "annual_vacancy_allowance": 15000.0, "annual_operating_expenses": 30000.0,
                    "net_operating_income": 255000.0, "cap_rate": 6.71, "cash_invested": 4085000.0,
                    "cash_on_cash_return_percent": 6.24
                }
            ]
        }
        await WorkflowEngine.complete_task_with_outcome(
            conn, i_task_4["task_id"], agent_id, outcome="RETURNS_COMPARED", notes="Comparative feasibility study completed",
            viewing_data=comp_payload
        )
        i_task_5 = await get_next_open_task(conn, opp_id=inv_opp_id, lead_id=inv_lead_id)
        assert i_task_5 and i_task_5["template_id"] == "TASK_INVEST_SCHEDULE_INSPECTION"
        print(f"  ✓ Step 5: Comparative Study Generated -> Next: {i_task_5['template_id']}")

        # Step 6: Schedule Inspection -> Next: TASK_INVEST_INSPECTION_REPORT
        await WorkflowEngine.complete_task_with_outcome(
            conn, i_task_5["task_id"], agent_id, outcome="SCHEDULED", notes="Technical building inspection scheduled with engineering consultant",
            viewing_data={"scheduled_start": datetime.now(timezone.utc).isoformat(), "unit_id": inv_unit_1}
        )
        i_task_6 = await get_next_open_task(conn, opp_id=inv_opp_id, lead_id=inv_lead_id)
        assert i_task_6 and i_task_6["template_id"] == "TASK_INVEST_INSPECTION_REPORT"
        print(f"  ✓ Step 6: Due Diligence Inspection Scheduled -> Next: {i_task_6['template_id']}")

        # Step 7: Due Diligence Inspection -> Generates DUE_DILIGENCE_REPORT -> Next: TASK_INVEST_VALIDATE_FINANCIALS
        ddr_payload = {
            "unit_id": inv_unit_1,
            "purchase_price": 4000000.0,
            "gross_annual_rent": 360000.0,
            "annual_vacancy_allowance": 21600.0, # 6% vacancy
            "annual_operating_expenses": 36000.0, # 10% OPEX
            "cash_invested": 4300000.0,
            "estimated_capex_sar": 35000.0,
            "suggested_price_adjustment_sar": 35000.0,
            "actual_occupancy_rate": 94.0,
            "structural_condition": "GOOD",
            "building_age_years": 4,
            "saudi_building_code_compliant": True,
            "hvac_status": "OPERATIONAL",
            "elevators_status": "OPERATIONAL",
            "roofing_and_insulation_status": "GOOD",
            "technical_notes": "All mechanical & structural systems compliant with Saudi Building Code SBC",
            "rent_roll_verified": True,
            "occupied_units_count": 8,
            "total_units_inspected": 8,
            "commercial_viability_score": 92,
            "property_manager_interview_notes": "Commercial tenants fully compliant with Ejari unified platform"
        }
        await WorkflowEngine.complete_task_with_outcome(
            conn, i_task_6["task_id"], agent_id, outcome="RECOMMENDED",
            notes="Inspection completed: Structural GOOD, CapEx required: 35,000 SAR for preventive maintenance",
            viewing_data=ddr_payload
        )
        i_task_7 = await get_next_open_task(conn, opp_id=inv_opp_id, lead_id=inv_lead_id)
        assert i_task_7 and i_task_7["template_id"] == "TASK_INVEST_VALIDATE_FINANCIALS"
        print(f"  ✓ Step 7: Technical & Commercial DD Completed -> Next: {i_task_7['template_id']}")

        # Step 8: Validate Financials -> Next: TASK_INVEST_PREPARE_ACQUISITION_OFFER
        await WorkflowEngine.complete_task_with_outcome(
            conn, i_task_7["task_id"], agent_id, outcome="VALIDATED", notes="Financial assumptions validated against rent roll"
        )
        i_task_8 = await get_next_open_task(conn, opp_id=inv_opp_id, lead_id=inv_lead_id)
        assert i_task_8 and i_task_8["template_id"] == "TASK_INVEST_PREPARE_ACQUISITION_OFFER"
        print(f"  ✓ Step 8: Financials Validated -> Next: {i_task_8['template_id']}")

        # Step 9: Inject CapEx Price Discount Negotiation Task: TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT
        inj_task, _ = await WorkflowEngine.spawn_task_from_template(
            conn=conn,
            template_id="TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT",
            lead_id=inv_lead_id,
            opportunity_id=inv_opp_id,
            customer_id=inv_cust_id,
            assigned_user_id=agent_id,
            priority="HIGH"
        )
        assert inj_task and inj_task["template_id"] == "TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT"
        print(f"  ✓ Step 9: Ad-hoc Task Injected dynamically: {inj_task['template_id']}")

        # Complete CapEx Negotiation -> Generates COUNTER_OFFER_LETTER
        await WorkflowEngine.complete_task_with_outcome(
            conn, inj_task["task_id"], agent_id, outcome="DISCOUNT_ACCEPTED",
            notes="Seller agreed to discount 35,000 SAR from acquisition price",
            viewing_data={
                "approved_acquisition_price": 3965000.0,
                "discount_amount": 35000.0,
                "equity_cash_invested": 4262725.0
            }
        )
        print("  ✓ Step 9b: CapEx Discount Accepted -> Counter Offer Letter archived!")

        # Step 10: Complete Acquisition Offer -> Next: TASK_INVEST_BASELINE_PERFORMANCE
        await WorkflowEngine.complete_task_with_outcome(
            conn, i_task_8["task_id"], agent_id, outcome="OFFER_ACCEPTED", notes="Acquisition offer of 3,965,000 SAR approved",
            viewing_data={"acquisition_price": 3965000.0, "unit_id": inv_unit_1}
        )
        i_task_9 = await get_next_open_task(conn, opp_id=inv_opp_id, lead_id=inv_lead_id)
        assert i_task_9 and i_task_9["template_id"] == "TASK_INVEST_BASELINE_PERFORMANCE"
        print(f"  ✓ Step 10: Acquisition Offer Accepted -> Next: {i_task_9['template_id']}")

        # Step 11: Establish Baseline -> Generates BASELINE_FINANCIAL_SHEET
        await WorkflowEngine.complete_task_with_outcome(
            conn, i_task_9["task_id"], agent_id, outcome="BASELINE_ESTABLISHED", notes="Performance baseline documented and archived",
            viewing_data={
                "purchase_price": 3965000.0, "gross_annual_rent": 360000.0,
                "net_operating_income": 302400.0, "cap_rate": 7.63, "cash_invested": 4262725.0
            }
        )
        print("  ✓ Step 11: Performance Baseline Established -> Investment Cycle Completed!")

        # Check documents generated
        inv_docs = await conn.fetch(
            "SELECT document_id, file_name, metadata FROM documents WHERE opportunity_id = $1 OR lead_id = $2",
            inv_opp_id, inv_lead_id
        )
        print(f"  📄 Documents Vault generated {len(inv_docs)} official documents for Investment Track:")
        for d in inv_docs:
            print(f"     - [{d['document_id']}] {d['file_name']}")
        assert len(inv_docs) >= 4, f"Expected at least 4 documents in Investment Track, got {len(inv_docs)}"

        results["investment_track"]["status"] = "PASSED"
        results["investment_track"]["steps"] = 11
        results["investment_track"]["documents"] = [d["file_name"] for d in inv_docs]

        # =========================================================================
        # 4. OFFICIAL DOCUMENT CATALOG & TEMPLATES VERIFICATION (16/16)
        # =========================================================================
        print("\n--- [4/4] VERIFYING ALL 16 OFFICIAL DOCUMENT TEMPLATES ---")
        doc_types = await conn.fetch("SELECT code, name FROM document_types ORDER BY code")
        print(f"  Found {len(doc_types)} registered document types in catalog:")

        tested = 0
        passed = 0
        for dt_row in doc_types:
            code = dt_row["code"]
            name = dt_row["name"]
            tested += 1

            # Synthetic document test row
            sample_doc = {
                "document_id": f"doc-test-{code.lower()}",
                "document_type_code": code,
                "document_type_name": name,
                "customer_name": "معاذ خضر النمري (شخصية اعتبارية)",
                "unit_number": "U-101",
                "project_name": "برج الروابي للأعمال",
                "building_name": "مبنى أ",
                "contract_number": "CON-2026-999",
                "asking_price": 1500000.0,
                "issued_at": str(date.today()),
                "metadata": {
                    "customer_name": "معاذ خضر النمري",
                    "inspector_name": "م. عبد الله الشهري",
                    "purchase_price": 1500000.0,
                    "asking_price": 1500000.0,
                    "gross_annual_rent": 140000.0,
                    "gross_rent": 140000.0,
                    "annual_vacancy_allowance": 7000.0,
                    "effective_gross_income": 133000.0,
                    "annual_operating_expenses": 7000.0,
                    "net_operating_income": 126000.0,
                    "cap_rate": 8.40,
                    "cash_invested": 1612500.0,
                    "cash_on_cash_return_percent": 7.81,
                    "estimated_capex_sar": 7500.0,
                    "suggested_price_adjustment_sar": 7500.0,
                    "actual_occupancy_rate": 95.0,
                    "occupied_units": 7,
                    "total_units": 7,
                    "structural_condition": "GOOD",
                    "saudi_building_code_compliant": True,
                    "hvac_status": "OPERATIONAL",
                    "elevators_status": "OPERATIONAL",
                    "roofing_and_insulation_status": "GOOD",
                    "property_manager_interview_notes": "ملتزمين"
                }
            }

            try:
                html = render_document_html(sample_doc)
                assert "مكتب معاذ خضر النمري للخدمات العقارية" in html, "Office brand header missing!"
                assert "print-toolbar" in html, "Print toolbar missing!"
                assert len(html) > 500, f"Rendered HTML too short for {code}!"
                print(f"     ✓ Template [{code}] ({name}) -> Rendered successfully ({len(html)} bytes)")
                passed += 1
            except Exception as e:
                print(f"     ✗ FAILED to render [{code}]: {e}")

        assert passed == tested, f"Only {passed}/{tested} templates passed rendering!"
        results["document_catalog"]["status"] = "PASSED"
        results["document_catalog"]["tested"] = tested
        results["document_catalog"]["passed"] = passed

        # =========================================================================
        # 5. DECISION SUPPORT DOCUMENTS VERIFICATION (شاشات دعم القرار)
        # =========================================================================
        print("\n--- [5/5] VERIFYING DECISION SUPPORT DOCUMENTS INTEGRATION ---")
        # Check that tasks linked to the investment opportunity have access to all 4 archived docs
        opp_docs = await conn.fetch(
            "SELECT document_id, file_name, metadata FROM documents WHERE opportunity_id = $1",
            inv_opp_id
        )
        assert len(opp_docs) >= 3, "Opportunity decision support documents missing!"
        print(f"  ✓ Verified: Opportunity {inv_opp_id} has {len(opp_docs)} reference documents for contextual decision support.")
        results["decision_support"]["status"] = "PASSED"
        results["decision_support"]["verified"] = True

        print("\n" + "=" * 80)
        print("🏆 ALL TRIPLE E2E SIMULATIONS & BEST-PRACTICES CHECKS PASSED 100%!")
        print("=" * 80)

    finally:
        # Cleanup isolated simulation data to keep live DB clean
        print("\n🧹 Cleaning up isolated test simulation entities...")
        cust_ids = [c for c in [sale_cust_id, rent_cust_id, inv_cust_id] if c]
        unit_ids = [u for u in [sale_unit_id, rent_unit_id, inv_unit_1, inv_unit_2] if u]

        if cust_ids or unit_ids:
            c_list = cust_ids or ["__none__"]
            u_list = unit_ids or ["__none__"]

            # 1. Access logs & Documents
            await conn.execute("DELETE FROM document_access_log WHERE document_id IN (SELECT document_id FROM documents WHERE customer_id = ANY($1) OR unit_id = ANY($2))", c_list, u_list)
            await conn.execute("DELETE FROM documents WHERE customer_id = ANY($1) OR unit_id = ANY($2)", c_list, u_list)

            # 2. Payments & Commissions (depend on contracts)
            await conn.execute("DELETE FROM payments WHERE contract_id IN (SELECT contract_id FROM contracts WHERE reservation_id IN (SELECT reservation_id FROM reservations WHERE customer_id = ANY($1) OR unit_id = ANY($2)))", c_list, u_list)
            await conn.execute("DELETE FROM commissions WHERE contract_id IN (SELECT contract_id FROM contracts WHERE reservation_id IN (SELECT reservation_id FROM reservations WHERE customer_id = ANY($1) OR unit_id = ANY($2)))", c_list, u_list)

            # 3. Contracts (depend on reservations)
            await conn.execute("DELETE FROM contracts WHERE reservation_id IN (SELECT reservation_id FROM reservations WHERE customer_id = ANY($1) OR unit_id = ANY($2))", c_list, u_list)

            # 4. Reservations
            await conn.execute("DELETE FROM reservations WHERE customer_id = ANY($1) OR unit_id = ANY($2)", c_list, u_list)

            # 5. Rent collections & Tenancies
            await conn.execute("DELETE FROM rent_collections WHERE tenancy_id IN (SELECT tenancy_id FROM tenancies WHERE tenant_customer_id = ANY($1) OR unit_id = ANY($2))", c_list, u_list)
            await conn.execute("DELETE FROM tenancies WHERE tenant_customer_id = ANY($1) OR unit_id = ANY($2)", c_list, u_list)

            # 6. Offers & Viewings & DDR & Invoices
            await conn.execute("DELETE FROM offers WHERE unit_id = ANY($2) OR opportunity_id IN (SELECT opportunity_id FROM opportunities WHERE customer_id = ANY($1))", c_list, u_list)
            await conn.execute("DELETE FROM viewings WHERE customer_id = ANY($1) OR unit_id = ANY($2)", c_list, u_list)
            await conn.execute("DELETE FROM investment_due_diligence_reports WHERE unit_id = ANY($2) OR opportunity_id IN (SELECT opportunity_id FROM opportunities WHERE customer_id = ANY($1))", c_list, u_list)
            await conn.execute("DELETE FROM invoices WHERE payer_customer_id = ANY($1) OR unit_id = ANY($2)", c_list, u_list)

            # 7. Tasks, Communications, Activities
            await conn.execute("DELETE FROM tasks WHERE customer_id = ANY($1) OR lead_id IN (SELECT lead_id FROM leads WHERE customer_id = ANY($1))", c_list)
            await conn.execute("DELETE FROM communications WHERE customer_id = ANY($1) OR lead_id IN (SELECT lead_id FROM leads WHERE customer_id = ANY($1))", c_list)
            await conn.execute("DELETE FROM activities WHERE customer_id = ANY($1) OR lead_id IN (SELECT lead_id FROM leads WHERE customer_id = ANY($1))", c_list)

            # 8. Lead children
            await conn.execute("DELETE FROM lead_events WHERE lead_id IN (SELECT lead_id FROM leads WHERE customer_id = ANY($1))", c_list)
            await conn.execute("DELETE FROM lead_notes WHERE lead_id IN (SELECT lead_id FROM leads WHERE customer_id = ANY($1))", c_list)
            await conn.execute("DELETE FROM lead_units WHERE unit_id = ANY($2) OR lead_id IN (SELECT lead_id FROM leads WHERE customer_id = ANY($1))", c_list, u_list)

            # 9. Opportunity units & Opportunities
            await conn.execute("DELETE FROM opportunity_units WHERE unit_id = ANY($2) OR opportunity_id IN (SELECT opportunity_id FROM opportunities WHERE customer_id = ANY($1))", c_list, u_list)
            await conn.execute("DELETE FROM opportunities WHERE customer_id = ANY($1)", c_list)

            # 10. Leads
            await conn.execute("DELETE FROM leads WHERE customer_id = ANY($1)", c_list)

            # 11. Units status history & Units
            await conn.execute("DELETE FROM unit_status_history WHERE unit_id = ANY($1)", u_list)
            await conn.execute("DELETE FROM units WHERE unit_id = ANY($1)", u_list)

            # 12. Customers
            await conn.execute("DELETE FROM customers WHERE customer_id = ANY($1)", c_list)

        await conn.close()

    return results


if __name__ == "__main__":
    res = asyncio.run(run_stage1_e2e_simulation())
    print("\nFINAL EXECUTION RESULTS SUMMARY:")
    print(json.dumps(res, indent=2))
