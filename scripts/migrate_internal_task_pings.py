#!/usr/bin/env python3
"""
migrate_internal_task_pings.py
Applies schema migration for internal operational task reminder pings:
- Creates `internal_task_pings` table and performance indexes.
- Seeds initial verified operational pings linked to demo tasks and collections.
"""

import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import asyncpg

load_dotenv(".env")

async def migrate_internal_pings():
    conn = await asyncpg.connect(
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "fAlnemari@1392"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        database=os.getenv("DB_NAME", "re_db"),
    )

    print("🚀 Starting Internal Task Reminder Pings Migration...")

    async with conn.transaction():
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS internal_task_pings (
                ping_id VARCHAR(36) PRIMARY KEY,
                sender_user_id VARCHAR(36) NOT NULL REFERENCES users(user_id),
                sender_name VARCHAR(120),
                recipient_role VARCHAR(50) NOT NULL,
                recipient_user_id VARCHAR(36) REFERENCES users(user_id),
                recipient_name VARCHAR(120),
                context_type VARCHAR(50) NOT NULL,
                context_id VARCHAR(50) NOT NULL,
                context_snapshot JSONB NOT NULL DEFAULT '{}',
                message_text TEXT NOT NULL,
                urgency_level VARCHAR(20) NOT NULL DEFAULT 'NORMAL',
                is_read BOOLEAN NOT NULL DEFAULT FALSE,
                read_at TIMESTAMP WITH TIME ZONE,
                is_archived BOOLEAN NOT NULL DEFAULT FALSE,
                archived_at TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_internal_pings_recipient ON internal_task_pings(recipient_user_id, is_read);
            CREATE INDEX IF NOT EXISTS idx_internal_pings_sender ON internal_task_pings(sender_user_id);
            CREATE INDEX IF NOT EXISTS idx_internal_pings_context ON internal_task_pings(context_type, context_id);
            CREATE INDEX IF NOT EXISTS idx_internal_pings_archived ON internal_task_pings(is_archived);
            CREATE INDEX IF NOT EXISTS idx_internal_pings_created ON internal_task_pings(created_at);
        """)
        print("  ✓ Created internal_task_pings table and indexes.")

        # Check existing count
        count = await conn.fetchval("SELECT COUNT(*) FROM internal_task_pings;")
        if count == 0:
            now = datetime.now(timezone.utc)
            sample_pings = [
                (
                    "PNG-20261101-000101",
                    "user-5",   # Nawaaf Alzahrani (Sales Manager)
                    "نواف الزهراني (مدير المبيعات)",
                    "SALES_AGENT",
                    "user-51",  # Fahad Kh. Alnemari (General Manager / Current User)
                    "فهد النمري",
                    "TASK",
                    "TSK-102",
                    json.dumps({
                        "rowId": "TSK-102",
                        "title": "الاتصال الأولي بالعميل ومطابقة المتطلبات",
                        "customer": "سلطان بن عبدالعزيز",
                        "amount": "1,250,000 SAR",
                        "assignedUser": "سلطان الغامدي",
                        "category": "TASK",
                        "lead_id": "LEAD-101"
                    }),
                    "تذكير عاجل: نرجو استكمال الاتصال بالعميل وتوثيق رغباته قبل نهاية مهلة الـ 30 دقيقة المعتمدة.",
                    "URGENT",
                    False,
                    None,
                    False,
                    None,
                    now - timedelta(minutes=25)
                ),
                (
                    "PNG-20261101-000102",
                    "user-4",   # Demo Agent 12 (Property Manager)
                    "إدارة الأملاك والتأجير",
                    "PROPERTY_MANAGER",
                    "user-51",  # Fahad Kh. Alnemari
                    "فهد النمري",
                    "RENT_COLLECTION",
                    "CL-504",
                    json.dumps({
                        "rowId": "CL-504",
                        "title": "قسط إيجار ربع سنوي - برج الياسمين",
                        "customer": "شركة الأفق للاستثمار",
                        "amount": "45,000 SAR",
                        "assignedUser": "إدارة الأملاك",
                        "category": "RENT_COLLECTION"
                    }),
                    "تذكير: دفعة الإيجار مستحقة اليوم، يرجى تزويدنا بالإشعار البنكي فور استلامه لإصدار سند القبض.",
                    "NORMAL",
                    False,
                    None,
                    False,
                    None,
                    now - timedelta(hours=3)
                )
            ]

            await conn.executemany("""
                INSERT INTO internal_task_pings (
                    ping_id, sender_user_id, sender_name, recipient_role,
                    recipient_user_id, recipient_name, context_type, context_id,
                    context_snapshot, message_text, urgency_level, is_read,
                    read_at, is_archived, archived_at, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16);
            """, sample_pings)
            print("  ✓ Seeded initial verified operational reminder pings.")
        else:
            print(f"  ✓ internal_task_pings already contains {count} records.")

    await conn.close()
    print("✨ Internal Task Reminder Pings Migration Completed Successfully.")

if __name__ == "__main__":
    asyncio.run(migrate_internal_pings())
