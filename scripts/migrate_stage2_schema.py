#!/usr/bin/env python3
"""
migrate_stage2_schema.py
Safely applies database schema updates for Stage 2 Operations:
1. Tenancies: Ejar contract number, contract type, ejar status, security deposit status.
2. Maintenance Work Orders: cost bearer, vat amount, total amount, invoice ref, notes.
3. Owner Yield Distributions: new table and sequence for owner periodic yield accounting.
4. Campaigns: UTM tracking parameters, target property/city, impression/click metrics.
"""

import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv(".env")

async def migrate_stage2():
    conn = await asyncpg.connect(
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "fAlnemari@1392"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "re_db"),
    )

    print("🚀 Starting Stage 2 Schema Migration...")

    async with conn.transaction():
        # 1. Tenancies Ejar integration
        await conn.execute("""
            ALTER TABLE tenancies 
            ADD COLUMN IF NOT EXISTS ejar_contract_number VARCHAR(64),
            ADD COLUMN IF NOT EXISTS ejar_status VARCHAR(32) DEFAULT 'ACTIVE',
            ADD COLUMN IF NOT EXISTS contract_type VARCHAR(32) DEFAULT 'RESIDENTIAL',
            ADD COLUMN IF NOT EXISTS security_deposit_status VARCHAR(32) DEFAULT 'HELD';
        """)
        print("  ✓ Updated tenancies table with Ejar metadata columns.")

        # 2. Maintenance Work Orders: Cost Bearer & VAT
        await conn.execute("""
            ALTER TABLE maintenance_work_orders 
            ADD COLUMN IF NOT EXISTS cost_bearer VARCHAR(32) DEFAULT 'OWNER',
            ADD COLUMN IF NOT EXISTS vat_amount NUMERIC(12,2) DEFAULT 0.0,
            ADD COLUMN IF NOT EXISTS total_amount NUMERIC(12,2) DEFAULT 0.0,
            ADD COLUMN IF NOT EXISTS invoice_ref VARCHAR(64),
            ADD COLUMN IF NOT EXISTS notes TEXT;
        """)
        print("  ✓ Updated maintenance_work_orders table with cost_bearer and VAT columns.")

        # 3. Owner Yield Distributions
        await conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS seq_owner_yield_distributions_id START WITH 1;
            
            CREATE TABLE IF NOT EXISTS owner_yield_distributions (
                distribution_id VARCHAR(64) PRIMARY KEY,
                organization_id VARCHAR(64) NOT NULL DEFAULT 'organization-1',
                management_contract_id VARCHAR(64) NOT NULL REFERENCES management_contracts(management_contract_id) ON DELETE CASCADE,
                owner_customer_id VARCHAR(64) NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
                period_start DATE NOT NULL,
                period_end DATE NOT NULL,
                gross_rent_collected NUMERIC(14,2) NOT NULL DEFAULT 0.0,
                management_fee_rate NUMERIC(6,2) NOT NULL DEFAULT 5.0,
                management_fee_amount NUMERIC(14,2) NOT NULL DEFAULT 0.0,
                maintenance_expenses_deducted NUMERIC(14,2) NOT NULL DEFAULT 0.0,
                other_deductions NUMERIC(14,2) NOT NULL DEFAULT 0.0,
                net_yield_amount NUMERIC(14,2) NOT NULL DEFAULT 0.0,
                status VARCHAR(32) NOT NULL DEFAULT 'DRAFT', -- DRAFT, APPROVED, PAID, CANCELLED
                payment_reference VARCHAR(128),
                bank_name VARCHAR(128),
                iban VARCHAR(64),
                paid_at TIMESTAMPTZ,
                notes TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        print("  ✓ Created owner_yield_distributions table and sequence.")

        # 4. Campaigns UTM and Digital Ad Channels
        await conn.execute("""
            ALTER TABLE campaigns 
            ADD COLUMN IF NOT EXISTS utm_source VARCHAR(64),
            ADD COLUMN IF NOT EXISTS utm_medium VARCHAR(64),
            ADD COLUMN IF NOT EXISTS utm_campaign VARCHAR(128),
            ADD COLUMN IF NOT EXISTS target_property_id VARCHAR(64),
            ADD COLUMN IF NOT EXISTS target_city_id VARCHAR(64),
            ADD COLUMN IF NOT EXISTS impressions_count INT DEFAULT 0,
            ADD COLUMN IF NOT EXISTS clicks_count INT DEFAULT 0,
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
        """)
        print("  ✓ Updated campaigns table with UTM tracking and ad channel metrics.")

        # 5. Campaign Leads conversion metrics
        await conn.execute("""
            ALTER TABLE campaign_leads 
            ADD COLUMN IF NOT EXISTS utm_source VARCHAR(64),
            ADD COLUMN IF NOT EXISTS utm_medium VARCHAR(64),
            ADD COLUMN IF NOT EXISTS conversion_stage VARCHAR(32) DEFAULT 'NEW',
            ADD COLUMN IF NOT EXISTS deal_value NUMERIC(14,2) DEFAULT 0.0;
        """)
        print("  ✓ Updated campaign_leads table with conversion tracking columns.")

        # 6. Add OWNER_STATEMENT to document_types if missing
        existing_doc_type = await conn.fetchval("SELECT document_type_id FROM document_types WHERE code = 'OWNER_STATEMENT'")
        if not existing_doc_type:
            new_dt_id = await conn.fetchval("SELECT 'document_type-' || (COALESCE(MAX(SUBSTRING(document_type_id FROM '[0-9]+')::int), 0) + 1) FROM document_types")
            await conn.execute("""
                INSERT INTO document_types (document_type_id, code, name, expiry_required)
                VALUES ($1, 'OWNER_STATEMENT', 'كشف حساب المالك وتوزيع العوائد التأجيرية', false)
            """, new_dt_id)
            print(f"  ✓ Registered OWNER_STATEMENT document type ({new_dt_id}).")

    await conn.close()
    print("✅ Stage 2 Schema Migration Completed Successfully!")

if __name__ == "__main__":
    asyncio.run(migrate_stage2())
