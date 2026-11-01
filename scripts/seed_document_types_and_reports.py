import asyncio
import asyncpg
from app.config import settings

DOCUMENT_TYPES = [
    ("document_type-12", "DUE_DILIGENCE_REPORT", "تقرير الفحص النافي للجهالة الفني والاستثماري (Due Diligence Report)", False),
    ("document_type-13", "COUNTER_OFFER_LETTER", "خطاب التفاوض وتعديل السعر مقابل عيوب CapEx (Counter Offer Letter)", False),
    ("document_type-14", "BASELINE_FINANCIAL_SHEET", "صحيفة خط الأساس للأداء المالي (Baseline Financial Performance Sheet)", False),
    ("document_type-15", "INVESTMENT_COMPARATIVE_REPORT", "دراسة الجدوى الاستثمارية والمقارنة متعددة العقارات (Comparative Feasibility Study)", False),
    ("document_type-16", "COMMERCIAL_OFFER", "العرض المالي والتجاري لشراء / استئجار عقار (Commercial Offer Letter)", False),
    ("document_type-17", "OFFER_DECISION", "قرار وتوثيق قبول/رفض العرض المالي (Offer Decision Notice)", False),
    ("document_type-18", "TAQEEM_VALUATION", "تقرير التقييم العقاري المعتمد (Taqeem Accredited Valuation Report)", True),
    ("document_type-19", "TAX_ZAKAT_CLEARANCE", "شهادة المخالصة الضريبية والزكوية (Tax & Zakat Clearance Certificate)", True),
    ("document_type-20", "COMMISSION_SETTLEMENT", "مسير ومطابقة استحقاق وصرف عمولة الوساطة (Brokerage Commission Settlement)", False),
]

CREATE_DDR_SQL = """
CREATE SEQUENCE IF NOT EXISTS seq_investment_due_diligence_reports_id START WITH 100 INCREMENT BY 1;

CREATE TABLE IF NOT EXISTS investment_due_diligence_reports (
    report_id VARCHAR(50) PRIMARY KEY,
    opportunity_id VARCHAR(50) REFERENCES opportunities(opportunity_id) ON DELETE CASCADE,
    unit_id VARCHAR(50) REFERENCES units(unit_id) ON DELETE CASCADE,
    viewing_id VARCHAR(50) REFERENCES viewings(viewing_id) ON DELETE SET NULL,
    inspector_user_id VARCHAR(50) REFERENCES users(user_id) ON DELETE SET NULL,
    inspection_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    structural_condition VARCHAR(50),
    building_age_years INTEGER,
    saudi_building_code_compliant BOOLEAN DEFAULT TRUE,
    hvac_status VARCHAR(50),
    elevators_status VARCHAR(50),
    plumbing_network_status VARCHAR(50),
    electrical_network_status VARCHAR(50),
    roofing_and_insulation_status VARCHAR(50),
    fire_safety_compliance VARCHAR(50),
    estimated_capex_sar NUMERIC(14, 2) DEFAULT 0.00,
    technical_notes TEXT,
    location_traffic_flow VARCHAR(50),
    access_and_egress_quality VARCHAR(50),
    parking_availability VARCHAR(50),
    actual_occupancy_rate NUMERIC(5, 2) DEFAULT 0.00,
    total_units_inspected INTEGER DEFAULT 0,
    occupied_units_count INTEGER DEFAULT 0,
    vacant_units_count INTEGER DEFAULT 0,
    rent_roll_verified BOOLEAN DEFAULT TRUE,
    property_manager_interview_notes TEXT,
    commercial_viability_score NUMERIC(5, 2) DEFAULT 0.00,
    commercial_notes TEXT,
    recommendation VARCHAR(50),
    suggested_price_adjustment_sar NUMERIC(14, 2) DEFAULT 0.00,
    final_verdict_summary TEXT,
    purchase_price_sar NUMERIC(14, 2) DEFAULT 0.00,
    gross_annual_rent_sar NUMERIC(14, 2) DEFAULT 0.00,
    vacancy_allowance_sar NUMERIC(14, 2) DEFAULT 0.00,
    effective_gross_income_sar NUMERIC(14, 2) DEFAULT 0.00,
    operating_expenses_opex_sar NUMERIC(14, 2) DEFAULT 0.00,
    net_operating_income_noi_sar NUMERIC(14, 2) DEFAULT 0.00,
    total_investment_basis_sar NUMERIC(14, 2) DEFAULT 0.00,
    gross_yield_percent NUMERIC(5, 2) DEFAULT 0.00,
    cap_rate_percent NUMERIC(5, 2) DEFAULT 0.00,
    net_yield_percent NUMERIC(5, 2) DEFAULT 0.00,
    cash_invested_sar NUMERIC(14, 2) DEFAULT 0.00,
    cash_on_cash_return_percent NUMERIC(5, 2) DEFAULT 0.00,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
"""

async def main():
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    print("Connected to database.")
    
    # 1. Create table & sequence
    await conn.execute(CREATE_DDR_SQL)
    print("investment_due_diligence_reports table and sequence created.")
    
    # 2. Seed document types
    for dt_id, code, name, exp in DOCUMENT_TYPES:
        await conn.execute("""
            INSERT INTO document_types (document_type_id, code, name, expiry_required)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (code) DO UPDATE SET
                name = EXCLUDED.name,
                expiry_required = EXCLUDED.expiry_required
        """, dt_id, code, name, exp)
    print("document_types seeded successfully.")
    
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())

