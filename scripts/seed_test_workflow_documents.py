import asyncio
import json
import asyncpg
from app.config import settings

async def main():
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    print("Connected to DB.")

    # 1. Ensure user 'Demo Agent 23' exists
    await conn.execute("""
        INSERT INTO users (user_id, organization_id, branch_id, email, full_name, status, created_at)
        VALUES ('user-23', 'organization-1', 'branch-1', 'agent23@recrm.sa', 'Demo Agent 23', 'ACTIVE', NOW())
        ON CONFLICT (user_id) DO UPDATE SET full_name = 'Demo Agent 23';
    """)

    # 2. Ensure customer 'Maan Othman' exists
    await conn.execute("""
        INSERT INTO customers (customer_id, organization_id, customer_type, first_name, last_name, mobile, status, created_at)
        VALUES ('cust-maan', 'organization-1', 'INDIVIDUAL', 'Maan', 'Othman', '0555123456', 'ACTIVE', NOW())
        ON CONFLICT (customer_id) DO UPDATE SET first_name = 'Maan', last_name = 'Othman';
    """)

    # 3. Ensure unit '104' exists
    pt_id = await conn.fetchval("SELECT property_type_id FROM property_types LIMIT 1")
    await conn.execute("""
        INSERT INTO units (unit_id, unit_number, property_type_id, status, asking_price, created_at)
        VALUES ('unit-104', '104', $1, 'AVAILABLE', 1200000, NOW())
        ON CONFLICT (unit_id) DO UPDATE SET unit_number = '104';
    """, pt_id)

    # 4. Ensure lead-114 exists
    await conn.execute("""
        INSERT INTO leads (lead_id, organization_id, customer_id, branch_id, assigned_user_id, status, inquiry_type, created_at)
        VALUES ('lead-114', 'organization-1', 'cust-maan', 'branch-1', 'user-23', 'QUALIFIED', 'INVESTMENT', NOW())
        ON CONFLICT (lead_id) DO UPDATE SET customer_id = 'cust-maan', inquiry_type = 'INVESTMENT';
    """)

    # 5. Ensure opportunity-734 exists
    await conn.execute("""
        INSERT INTO opportunities (opportunity_id, lead_id, customer_id, stage, expected_value, created_at)
        VALUES ('opportunity-734', 'lead-114', 'cust-maan', 'PROPOSAL', 12000000, NOW())
        ON CONFLICT (opportunity_id) DO UPDATE SET lead_id = 'lead-114', customer_id = 'cust-maan';
    """)

    # Helper to get document_type_id from code
    dt_rows = await conn.fetch("SELECT document_type_id, code FROM document_types")
    dt_map = {r["code"]: r["document_type_id"] for r in dt_rows}

    # 6. Seed document-1579
    ddr_meta = {
        "inspector_name": "Demo Agent 23",
        "investor_name": "Maan Othman",
        "customer_name": "Maan Othman",
        "estimated_capex_sar": 7500.0,
        "purchase_price": 1500000.0,
        "asking_price": 1500000.0,
        "gross_annual_rent": 140000.0,
        "vacancy_allowance": 7000.0,
        "operating_expenses_opex": 7000.0,
        "net_operating_income_noi": 126000.0,
        "cap_rate": 8.4,
        "cap_rate_percent": 8.4,
        "cash_invested": 1612500.0,
        "cash_on_cash_return": 7.81,
        "occupied_units": 7,
        "total_units": 7,
        "occupancy_rate": "95.0%",
        "property_manager_notes": "ملتزمين",
        "notes": "دراسة الجدوى والتحليل المالي الاستثماري"
    }
    await conn.execute("""
        INSERT INTO documents (
            document_id, organization_id, document_type_id, customer_id, unit_id, lead_id, opportunity_id,
            file_name, storage_uri, file_hash, version_no, status, uploaded_by_user_id, metadata, created_at
        ) VALUES (
            'document-1579', 'organization-1', $1, 'cust-maan', 'unit-104', 'lead-114', 'opportunity-734',
            'تقرير_فحص_نافي_للجهالة_1579.pdf', '/vault/ddr/1579.pdf', 'hash-1579', 1, 'ACTIVE', 'user-23',
            $2::jsonb, NOW()
        )
        ON CONFLICT (document_id) DO UPDATE SET
            metadata = EXCLUDED.metadata,
            uploaded_by_user_id = 'user-23',
            customer_id = 'cust-maan',
            lead_id = 'lead-114',
            opportunity_id = 'opportunity-734';
    """, dt_map["DUE_DILIGENCE_REPORT"], json.dumps(ddr_meta))

    # 7. Seed documents for lead-114
    lead114_docs = [
        ("doc-lead114-1", "DUE_DILIGENCE_REPORT", "تقرير_فحص_فني_استثماري_lead114.pdf", ddr_meta),
        ("doc-lead114-2", "COUNTER_OFFER_LETTER", "خطاب_تفاوض_وتعديل_السعر_lead114.pdf", {
            "buyer_name": "Maan Othman", "customer_name": "Maan Othman", "offer_amount": 11800000, "discount_requested": 200000
        }),
        ("doc-lead114-3", "COMMERCIAL_OFFER", "عرض_شراء_تجاري_معتمد_lead114.pdf", {
            "buyer_name": "Maan Othman", "customer_name": "Maan Othman", "offer_amount": 12000000
        }),
        ("doc-lead114-4", "BASELINE_FINANCIAL_SHEET", "صحيفة_خط_الأساس_المالي_lead114.pdf", {
            "customer_name": "Maan Othman", "baseline_noi": 1260000, "projected_yield": 8.5
        }),
        ("doc-lead114-5", "TAX_ZAKAT_CLEARANCE", "شهادة_مخالصة_ضريبية_lead114.pdf", {
            "customer_name": "Maan Othman", "tax_number": "300123456700003"
        }),
    ]

    for doc_id, code, fname, meta in lead114_docs:
        uri = f"/vault/test/{doc_id}.pdf"
        hsh = f"hash-{doc_id}"
        await conn.execute("""
            INSERT INTO documents (
                document_id, organization_id, document_type_id, customer_id, unit_id, lead_id, opportunity_id,
                file_name, storage_uri, file_hash, version_no, status, uploaded_by_user_id, metadata, created_at
            ) VALUES (
                $1, 'organization-1', $2, 'cust-maan', 'unit-104', 'lead-114', 'opportunity-734',
                $3, $4, $5, 1, 'ACTIVE', 'user-23',
                $6::jsonb, NOW()
            )
            ON CONFLICT (document_id) DO UPDATE SET
                lead_id = 'lead-114',
                opportunity_id = 'opportunity-734',
                metadata = EXCLUDED.metadata;
        """, doc_id, dt_map[code], fname, uri, hsh, json.dumps(meta))

    # 8. Seed additional documents to reach >= 25 total, >= 5 OFFERS, >= 5 INSPECTIONS, and search keywords
    extra_docs = [
        # Inspection category (DILIGENCE, TAQEEM, BASELINE, SOIL, DEFECT, COMPARATIVE)
        ("doc-insp-01", "TAQEEM_VALUATION", "تقرير فحص وتقييم عقاري معتمد مقيم.pdf", {"property_name": "برج اليرموك"}),
        ("doc-insp-02", "INVESTMENT_COMPARATIVE_REPORT", "دراسة الجدوى الاستثمارية والمقارنة.pdf", {}),
        ("doc-insp-03", "SOIL_ENVIRONMENTAL_REPORT", "تقرير فحص ميكانيكا التربة SBC.pdf", {}),
        ("doc-insp-04", "TAQEEM_VALUATION", "تقرير تقييم عقاري رسمي وحدة 104.pdf", {}),
        
        # Offers category (OFFER, COUNTER, RESERVATION)
        ("doc-off-01", "COMMERCIAL_OFFER", "عرض مالي لشراء عقار تجاري.pdf", {}),
        ("doc-off-02", "COUNTER_OFFER_LETTER", "خطاب التفاوض والعرض المقابل.pdf", {}),
        ("doc-off-03", "COMMERCIAL_OFFER", "إشعار استلام وقبول العرض المالي.pdf", {}),
        ("doc-off-04", "OFFER_DECISION", "إشعار قرار قبول العرض المالي والترسية.pdf", {}),
        ("doc-off-05", "COMMERCIAL_OFFER", "عرض استثماري لوحدة رقم 104.pdf", {}),

        # Search matching 'إشعار' and '104'
        ("doc-search-01", "COMMERCIAL_OFFER", "إشعار رسمي بعرض شراء للوحدة 104.pdf", {}),
        ("doc-search-02", "INVOICE", "إشعار فاتورة ضريبية رسمية.pdf", {}),
    ]

    for doc_id, code, fname, meta in extra_docs:
        dt_id = dt_map.get(code, dt_map["COMMERCIAL_OFFER"])
        uri = f"/vault/test/{doc_id}.pdf"
        hsh = f"hash-{doc_id}"
        await conn.execute("""
            INSERT INTO documents (
                document_id, organization_id, document_type_id, customer_id, unit_id,
                file_name, storage_uri, file_hash, version_no, status, uploaded_by_user_id, metadata, created_at
            ) VALUES (
                $1, 'organization-1', $2, 'cust-maan', 'unit-104',
                $3, $4, $5, 1, 'ACTIVE', 'user-23',
                $6::jsonb, NOW()
            )
            ON CONFLICT (document_id) DO UPDATE SET
                file_name = EXCLUDED.file_name,
                metadata = EXCLUDED.metadata;
        """, doc_id, dt_id, fname, uri, hsh, json.dumps(meta))

    total = await conn.fetchval("SELECT count(*) FROM documents")
    print(f"Workflow test documents seeded successfully! Total documents: {total}")
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
