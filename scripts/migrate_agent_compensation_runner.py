#!/usr/bin/env python3
"""
Agent Compensation & Statutory Fees Migration
Adds compensation profiles to users (SALARY, COMMISSION, FIXED_CUT, SALARY_PLUS_COMMISSION)
and enriches commissions with net brokerage and government fees auditing.
"""

import sys
import asyncio
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent / "src" / "backend"
sys.path.insert(0, str(backend_dir))

import asyncpg
from app.config import settings

TARGET_DBS = ["re_db", "redb"]

MIGRATION_SQL = """
-- 1. Enhance users table with agent compensation profiles
ALTER TABLE users ADD COLUMN IF NOT EXISTS compensation_type VARCHAR(32) DEFAULT 'COMMISSION';
ALTER TABLE users ADD COLUMN IF NOT EXISTS base_salary NUMERIC(12, 2) DEFAULT 0.00;
ALTER TABLE users ADD COLUMN IF NOT EXISTS sales_commission_rate NUMERIC(5, 2) DEFAULT 25.00;
ALTER TABLE users ADD COLUMN IF NOT EXISTS rent_commission_rate NUMERIC(5, 2) DEFAULT 25.00;
ALTER TABLE users ADD COLUMN IF NOT EXISTS sales_fixed_cut NUMERIC(12, 2) DEFAULT 0.00;
ALTER TABLE users ADD COLUMN IF NOT EXISTS rent_fixed_cut NUMERIC(12, 2) DEFAULT 0.00;

-- 2. Enhance commissions table with transparent financial breakdown
ALTER TABLE commissions ADD COLUMN IF NOT EXISTS compensation_type VARCHAR(32) DEFAULT 'COMMISSION';
ALTER TABLE commissions ADD COLUMN IF NOT EXISTS gross_deal_value NUMERIC(14, 2) DEFAULT 0.00;
ALTER TABLE commissions ADD COLUMN IF NOT EXISTS gross_brokerage_amount NUMERIC(12, 2) DEFAULT 0.00;
ALTER TABLE commissions ADD COLUMN IF NOT EXISTS gov_fees_deducted NUMERIC(12, 2) DEFAULT 0.00;
ALTER TABLE commissions ADD COLUMN IF NOT EXISTS net_commission_base NUMERIC(12, 2) DEFAULT 0.00;
ALTER TABLE commissions ADD COLUMN IF NOT EXISTS calculation_notes TEXT;
"""

async def run_migration_on_db(dbname: str):
    print(f"\n=======================================================")
    print(f"  Applying Agent Compensation Migration to [{dbname}]")
    print(f"=======================================================")
    try:
        conn = await asyncpg.connect(
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            database=dbname
        )
    except Exception as e:
        print(f"  [!] Could not connect to {dbname}: {e}")
        return

    async with conn.transaction():
        await conn.execute(MIGRATION_SQL)
        print("  [✓] Columns added successfully to 'users' and 'commissions'.")

        # Distribute existing agents across diverse compensation profiles for operational realism
        agents = await conn.fetch("""
            SELECT u.user_id, u.full_name, r.name as role_name
            FROM users u
            JOIN user_roles ur ON u.user_id = ur.user_id
            JOIN roles r ON ur.role_id = r.role_id
            WHERE r.name IN ('Assigned Sales Agent', 'Leasing Agent')
            ORDER BY u.user_id;
        """)

        print(f"  [+] Configuring compensation profiles for {len(agents)} agents...")
        for idx, ag in enumerate(agents):
            u_id = ag["user_id"]
            # Alternate among:
            # 0: SALARY (Full-time employee with fixed monthly salary)
            # 1: COMMISSION (Commission split on net brokerage)
            # 2: FIXED_CUT (Fixed lump-sum cut per transaction)
            # 3: SALARY_PLUS_COMMISSION (Hybrid base salary + lower commission cut)
            profile_idx = idx % 4
            if profile_idx == 0:
                # Salaried employee: 8,500 SAR/mo, 0% commission
                await conn.execute("""
                    UPDATE users 
                    SET compensation_type = 'SALARY',
                        base_salary = 8500.00,
                        sales_commission_rate = 0.00,
                        rent_commission_rate = 0.00,
                        sales_fixed_cut = 0.00,
                        rent_fixed_cut = 0.00
                    WHERE user_id = $1
                """, u_id)
            elif profile_idx == 1:
                # Commission split: 30% on sale net brokerage, 25% on rent net brokerage
                await conn.execute("""
                    UPDATE users 
                    SET compensation_type = 'COMMISSION',
                        base_salary = 0.00,
                        sales_commission_rate = 30.00,
                        rent_commission_rate = 25.00,
                        sales_fixed_cut = 0.00,
                        rent_fixed_cut = 0.00
                    WHERE user_id = $1
                """, u_id)
            elif profile_idx == 2:
                # Fixed cut: 2,500 SAR per sale, 800 SAR per rental
                await conn.execute("""
                    UPDATE users 
                    SET compensation_type = 'FIXED_CUT',
                        base_salary = 0.00,
                        sales_commission_rate = 0.00,
                        rent_commission_rate = 0.00,
                        sales_fixed_cut = 2500.00,
                        rent_fixed_cut = 800.00
                    WHERE user_id = $1
                """, u_id)
            else:
                # Hybrid: 4,000 SAR salary + 15% incentive cut
                await conn.execute("""
                    UPDATE users 
                    SET compensation_type = 'SALARY_PLUS_COMMISSION',
                        base_salary = 4000.00,
                        sales_commission_rate = 15.00,
                        rent_commission_rate = 12.00,
                        sales_fixed_cut = 0.00,
                        rent_fixed_cut = 0.00
                    WHERE user_id = $1
                """, u_id)

        # Update existing commission records with breakdown data if missing
        await conn.execute("""
            UPDATE commissions c
            SET 
                gross_deal_value = COALESCE(con.contract_value, 0.00),
                gross_brokerage_amount = ROUND(COALESCE(con.contract_value, 0.00) * 0.025, 2),
                gov_fees_deducted = ROUND((COALESCE(con.contract_value, 0.00) * 0.025) * 0.15, 2),
                net_commission_base = ROUND((COALESCE(con.contract_value, 0.00) * 0.025) - ((COALESCE(con.contract_value, 0.00) * 0.025) * 0.15), 2),
                calculation_notes = 'Calculated on Net Brokerage after deducting 15% VAT and statutory pass-through fees.'
            FROM contracts con
            WHERE c.contract_id = con.contract_id AND (c.net_commission_base = 0.00 OR c.net_commission_base IS NULL);
        """)

        # Verification summary
        stats = await conn.fetch("""
            SELECT compensation_type, count(*) 
            FROM users 
            GROUP BY compensation_type 
            ORDER BY compensation_type;
        """)
        print("\n  [✓] User Compensation Summary:")
        for s in stats:
            print(f"      - {s['compensation_type'] or 'UNASSIGNED'}: {s['count']} users")

    await conn.close()
    print(f"  [✓] Migration completed for [{dbname}].")

async def main():
    for db in TARGET_DBS:
        await run_migration_on_db(db)

if __name__ == "__main__":
    asyncio.run(main())

