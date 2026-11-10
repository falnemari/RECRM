"""
Sales Pipeline Streamlining Migration Script
Applies the unified sales workflow templates to both redb and re_db:
1. TASK_MATCH_PROPERTIES (unified property matching)
2. TASK_LEAD_FOLLOWUP_QUALIFY (dedicated follow-up qualification)
3. TASK_SALES_LEAD_CONTACT_QUALIFY (consolidates first contact & qualification)
4. Updates TASK_LEAD_ASSIGN with SALES outcome and default next_template_id
"""

import asyncio
import asyncpg
import json
import os
import sys

# Define outcomes for the new templates
MATCH_PROPERTIES_OUTCOMES = {
    "MATCHED": {
        "next_template_id": "TASK_VIEWING_SCHEDULE",
        "label_ar": "🏢 ترشيح الوحدات بنجاح",
        "label_en": "🏢 Properties Matched & Presented",
        "description_ar": "توثيق إرسال مقترحات العقارات وتوليد مهمة جدولة المعاينة الميدانية",
        "description_en": "Record sent property recommendations and spawn site visit scheduling task",
        "style": "success",
        "requires_fields": "match"
    },
    "REVISE_CRITERIA": {
        "next_template_id": None,
        "label_ar": "🔄 تعديل شروط وميزانية البحث",
        "label_en": "🔄 Revise Search Criteria",
        "description_ar": "تحديث وتعديل متطلبات البحث والميزانية مع العميل",
        "description_en": "Update search preferences and budget criteria with client",
        "style": "info",
        "requires_fields": None
    },
    "NONE_FOUND": {
        "next_template_id": None,
        "label_ar": "🔍 لا توجد وحدات مطابقة بالمخزون",
        "label_en": "🔍 No Units Found in Inventory",
        "description_ar": "وضع الطلب في الانتظار للمطابقة التلقائية مع المخزون الجديد",
        "description_en": "Place deal on waitlist for auto-matching with new listings",
        "style": "warning",
        "requires_fields": None
    }
}

LEAD_FOLLOWUP_QUALIFY_OUTCOMES = {
    "CONTACTED_QUALIFIED": {
        "next_template_id": "TASK_MATCH_PROPERTIES",
        "label_ar": "📞 تم الاتصال واستكمال التأهيل بنجاح",
        "label_en": "📞 Successfully Connected & Qualified",
        "description_ar": "تم التواصل في المتابعة واستيفاء معايير التأهيل وترقية الطلب لصفقة بيع نشطة",
        "description_en": "Follow-up successful, gathered qualification criteria and promoted to active opportunity",
        "style": "success",
        "requires_fields": "qual",
        "sort_order": 1
    },
    "CALLBACK_REQUESTED": {
        "next_template_id": "TASK_LEAD_FOLLOWUP_QUALIFY",
        "label_ar": "⏰ طلب معاودة الاتصال",
        "label_en": "⏰ Callback Requested",
        "description_ar": "تحديد موعد جديد لمعاودة الاتصال بالعميل",
        "description_en": "Specify new date and time to call client back",
        "style": "info",
        "requires_fields": "callback",
        "sort_order": 2
    },
    "UNREACHABLE": {
        "next_template_id": "TASK_LEAD_FOLLOWUP_QUALIFY",
        "label_ar": "📵 تعذر الوصول / لا يوجد رد",
        "label_en": "📵 Unreachable / No Answer",
        "description_ar": "تسجيل محاولة متابعة (يغلق الطلب كغير مستجيب تلقائياً بعد 3 محاولات)",
        "description_en": "Record follow-up attempt (auto-closes after 3 unreached attempts)",
        "style": "info",
        "requires_fields": "callback",
        "sort_order": 3
    },
    "NOT_INTERESTED": {
        "next_template_id": None,
        "label_ar": "🚫 غير مهتم",
        "label_en": "🚫 Not Interested",
        "description_ar": "إغلاق الطلب واستبعاده",
        "description_en": "Disqualify and close inquiry",
        "style": "danger",
        "requires_fields": None,
        "sort_order": 4
    }
}

SALES_LEAD_CONTACT_QUALIFY_OUTCOMES = {
    "CONTACTED_QUALIFIED": {
        "next_template_id": "TASK_MATCH_PROPERTIES",
        "label_ar": "📞 تم الاتصال واستكمال التأهيل بنجاح",
        "label_en": "📞 Successfully Connected & Qualified",
        "description_ar": "تم التواصل مع العميل واستيفاء كافة معايير التأهيل والميزانية وترقية الطلب لصفقة بيع نشطة",
        "description_en": "Successfully connected with client, gathered qualification criteria, and promoted to active sale opportunity",
        "style": "success",
        "requires_fields": "qual",
        "sort_order": 1
    },
    "CALLBACK_REQUESTED": {
        "next_template_id": "TASK_LEAD_FOLLOWUP_QUALIFY",
        "label_ar": "⏰ طلب معاودة الاتصال",
        "label_en": "⏰ Callback Requested",
        "description_ar": "تحديد موعد وتوقيت لإعادة الاتصال بالعميل واستكمال التأهيل",
        "description_en": "Specify date and time to follow up and qualify client",
        "style": "info",
        "requires_fields": "callback",
        "sort_order": 2
    },
    "UNREACHABLE": {
        "next_template_id": "TASK_LEAD_FOLLOWUP_QUALIFY",
        "label_ar": "📵 تعذر الوصول / لا يوجد رد",
        "label_en": "📵 Unreachable / No Answer",
        "description_ar": "تسجيل محاولة اتصال أولية وتوليد مهمة متابعة وتأهيل (بحد أقصى 3 محاولات)",
        "description_en": "Record first contact attempt and schedule follow-up qualification (up to 3 attempts max)",
        "style": "info",
        "requires_fields": "callback",
        "sort_order": 3
    },
    "NOT_INTERESTED": {
        "next_template_id": None,
        "label_ar": "🚫 غير مهتم",
        "label_en": "🚫 Not Interested",
        "description_ar": "إغلاق الطلب واستبعاده بناء على رغبة العميل",
        "description_en": "Disqualify and close lead per client request",
        "style": "danger",
        "requires_fields": None,
        "sort_order": 4
    },
    "INVALID_CONTACT": {
        "next_template_id": None,
        "label_ar": "📵 رقم خاطئ / بيانات غير صالحة",
        "label_en": "📵 Invalid Number / Data",
        "description_ar": "استبعاد الطلب لعدم صحة بيانات الاتصال نهائياً",
        "description_en": "Disqualify lead permanently due to invalid contact details",
        "style": "danger",
        "requires_fields": None,
        "sort_order": 5
    }
}

async def apply_to_database(db_name: str):
    print(f"\n==========================================")
    print(f"Applying Streamlined Pipeline to [{db_name}]")
    print(f"==========================================")
    conn = await asyncpg.connect(f"postgresql://postgres:fAlnemari%401392@localhost:5432/{db_name}")

    try:
        # Ensure column is JSON (preserves exact dictionary key ordering)
        await conn.execute("ALTER TABLE workflow_templates ALTER COLUMN outcome_transitions TYPE JSON USING outcome_transitions::json;")

        # 1. Upsert TASK_MATCH_PROPERTIES (depends on TASK_VIEWING_SCHEDULE which already exists)
        await conn.execute("""
            INSERT INTO workflow_templates (
                template_id, template_type, standard_title_ar, standard_title_en,
                standard_subject_ar, standard_subject_en, owner_role,
                default_sla_minutes, escalation_role, escalation_sla_minutes,
                next_template_id, outcome_transitions,
                completion_criteria_ar, completion_criteria_en
            ) VALUES (
                'TASK_MATCH_PROPERTIES', 'TASK',
                'الفرصة — مطابقة وترشيح العقارات', 'Opportunity — Match Properties',
                'مطابقة وترشيح العقارات المناسبة للفرصة', 'Match and present available properties',
                'SALES_AGENT', 240, 'BRANCH_MANAGER', 480,
                'TASK_VIEWING_SCHEDULE', $1::json,
                'مطابقة وترشيح الوحدات العقارية المناسبة من المخزون وإرسالها للعميل تمهيداً لجدولة المعاينة',
                'Match and recommend available properties from inventory and present to client before scheduling viewing'
            )
            ON CONFLICT (template_id) DO UPDATE SET
                standard_title_ar = EXCLUDED.standard_title_ar,
                standard_title_en = EXCLUDED.standard_title_en,
                owner_role = EXCLUDED.owner_role,
                default_sla_minutes = EXCLUDED.default_sla_minutes,
                escalation_sla_minutes = EXCLUDED.escalation_sla_minutes,
                next_template_id = EXCLUDED.next_template_id,
                outcome_transitions = EXCLUDED.outcome_transitions,
                completion_criteria_ar = EXCLUDED.completion_criteria_ar,
                completion_criteria_en = EXCLUDED.completion_criteria_en;
        """, json.dumps(MATCH_PROPERTIES_OUTCOMES))
        print("✓ Upserted: TASK_MATCH_PROPERTIES")

        # 2. Upsert TASK_LEAD_FOLLOWUP_QUALIFY (depends on TASK_MATCH_PROPERTIES)
        # Note: self-reference in outcome transitions (json) does not enforce DB FK, but next_template_id is TASK_MATCH_PROPERTIES
        await conn.execute("""
            INSERT INTO workflow_templates (
                template_id, template_type, standard_title_ar, standard_title_en,
                standard_subject_ar, standard_subject_en, owner_role,
                default_sla_minutes, escalation_role, escalation_sla_minutes,
                next_template_id, outcome_transitions,
                completion_criteria_ar, completion_criteria_en
            ) VALUES (
                'TASK_LEAD_FOLLOWUP_QUALIFY', 'TASK',
                'الطلب — متابعة الاتصال والتأهيل', 'Lead — Follow-up & Qualification',
                'متابعة الاتصال بالعميل واستكمال التأهيل', 'Follow-up call to complete qualification',
                'SALES_AGENT', 180, 'BRANCH_MANAGER', 240,
                'TASK_MATCH_PROPERTIES', $1::json,
                'معاودة الاتصال بالعميل لاستكمال معايير التأهيل وتصعيد المتابعات بحد أقصى 3 محاولات',
                'Follow up with lead to capture qualification criteria with maximum 3 retry attempts'
            )
            ON CONFLICT (template_id) DO UPDATE SET
                standard_title_ar = EXCLUDED.standard_title_ar,
                standard_title_en = EXCLUDED.standard_title_en,
                owner_role = EXCLUDED.owner_role,
                default_sla_minutes = EXCLUDED.default_sla_minutes,
                escalation_sla_minutes = EXCLUDED.escalation_sla_minutes,
                next_template_id = EXCLUDED.next_template_id,
                outcome_transitions = EXCLUDED.outcome_transitions,
                completion_criteria_ar = EXCLUDED.completion_criteria_ar,
                completion_criteria_en = EXCLUDED.completion_criteria_en;
        """, json.dumps(LEAD_FOLLOWUP_QUALIFY_OUTCOMES))
        print("✓ Upserted: TASK_LEAD_FOLLOWUP_QUALIFY")

        # 3. Upsert TASK_SALES_LEAD_CONTACT_QUALIFY (depends on TASK_MATCH_PROPERTIES)
        await conn.execute("""
            INSERT INTO workflow_templates (
                template_id, template_type, standard_title_ar, standard_title_en,
                standard_subject_ar, standard_subject_en, owner_role,
                default_sla_minutes, escalation_role, escalation_sla_minutes,
                next_template_id, outcome_transitions,
                completion_criteria_ar, completion_criteria_en
            ) VALUES (
                'TASK_SALES_LEAD_CONTACT_QUALIFY', 'TASK',
                'الطلب — الاتصال الأولي واستكمال التأهيل', 'Lead — First Contact & Qualification',
                'الاتصال بالعميل واستيفاء معايير التأهيل', 'First contact & qualification interview',
                'SALES_AGENT', 30, 'BRANCH_MANAGER', 45,
                'TASK_MATCH_PROPERTIES', $1::json,
                'الاتصال بالعميل واستيفاء معايير الميزانية والمدينة ونوع العقار، أو تحديد موعد متابعة، أو استبعاد الطلب',
                'Contact lead and capture budget/city/property preferences, or schedule follow-up, or disqualify lead'
            )
            ON CONFLICT (template_id) DO UPDATE SET
                standard_title_ar = EXCLUDED.standard_title_ar,
                standard_title_en = EXCLUDED.standard_title_en,
                owner_role = EXCLUDED.owner_role,
                default_sla_minutes = EXCLUDED.default_sla_minutes,
                escalation_sla_minutes = EXCLUDED.escalation_sla_minutes,
                next_template_id = EXCLUDED.next_template_id,
                outcome_transitions = EXCLUDED.outcome_transitions,
                completion_criteria_ar = EXCLUDED.completion_criteria_ar,
                completion_criteria_en = EXCLUDED.completion_criteria_en;
        """, json.dumps(SALES_LEAD_CONTACT_QUALIFY_OUTCOMES))
        print("✓ Upserted: TASK_SALES_LEAD_CONTACT_QUALIFY")

        # 4. Update TASK_LEAD_ASSIGN
        assign_row = await conn.fetchrow("SELECT outcome_transitions FROM workflow_templates WHERE template_id = 'TASK_LEAD_ASSIGN'")
        if assign_row:
            raw = assign_row["outcome_transitions"]
            assign_outcomes = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
            
            # Add SALES outcome
            assign_outcomes["SALES"] = {
                "next_template_id": "TASK_SALES_LEAD_CONTACT_QUALIFY",
                "label_ar": "👤 تم تعيين وسيط البيع",
                "label_en": "👤 Agent Assigned",
                "description_ar": "إتمام التعيين وتوليد مهمة الاتصال الأولي والتأهيل للوسيط بمهلة SLA قدرها 30 دقيقة",
                "description_en": "Complete assignment and spawn 30-min first contact & qualification SLA task",
                "style": "success",
                "requires_fields": "assign"
            }
            # Keep ASSIGNED for backward compatibility
            assign_outcomes["ASSIGNED"] = {
                "next_template_id": "TASK_SALES_LEAD_CONTACT_QUALIFY",
                "label_ar": "👤 تم تعيين وسيط البيع",
                "label_en": "👤 Agent Assigned",
                "description_ar": "إتمام التعيين وتوليد مهمة الاتصال الأولي والتأهيل للوسيط بمهلة SLA قدرها 30 دقيقة",
                "description_en": "Complete assignment and spawn 30-min first contact & qualification SLA task",
                "style": "success",
                "requires_fields": "assign"
            }
            
            await conn.execute("""
                UPDATE workflow_templates
                SET next_template_id = 'TASK_SALES_LEAD_CONTACT_QUALIFY',
                    outcome_transitions = $1::json
                WHERE template_id = 'TASK_LEAD_ASSIGN'
            """, json.dumps(assign_outcomes))
            print("✓ Updated: TASK_LEAD_ASSIGN (next_template_id: TASK_SALES_LEAD_CONTACT_QUALIFY, outcomes: SALES + ASSIGNED)")

    finally:
        await conn.close()

async def main():
    for db in ["redb", "re_db"]:
        await apply_to_database(db)
    print("\nMigration completed successfully for both redb and re_db!")

if __name__ == "__main__":
    asyncio.run(main())
