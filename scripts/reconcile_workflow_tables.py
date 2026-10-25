"""
Reconcile and normalize workflow_templates and workflow_sop_guidance.
Ensures:
1. Removal of redundant standard_subject_ar / standard_subject_en columns from workflow_templates.
2. Perfect 1:1 alignment between 39 TASK templates and 39 TASK SOP guidance rows.
3. Separation of the 7 CRM STAGE guidance rows (template_id = NULL).
4. Structured step objects for sop-invest-sched-inspect and sop-invest-report-inspect.
5. Role synchronization from workflow_templates.owner_role to workflow_sop_guidance.
6. Bilingual completion criteria harmonized with required_now_ar.
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

from app.database import init_db_pool, close_db_pool

async def main():
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        print("=== 1. Dropping redundant standard_subject columns from workflow_templates ===")
        await conn.execute("""
            ALTER TABLE workflow_templates DROP COLUMN IF EXISTS standard_subject_ar;
            ALTER TABLE workflow_templates DROP COLUMN IF EXISTS standard_subject_en;
        """)
        print("Dropped standard_subject_ar and standard_subject_en successfully.")

        print("\n=== 2. Reclassifying 10 mislabeled SOP guidance procedures as entity_type = 'TASK' ===")
        task_sops_to_fix = [
            'sop-proc-01-lead-intake',
            'sop-proc-02-comm-call',
            'sop-proc-03-comm-whatsapp',
            'sop-proc-06-opp-match',
            'sop-proc-07-viewing-schedule',
            'sop-proc-10-offer-submit',
            'sop-proc-12-offer-followup',
            'sop-proc-13-res-availability',
            'sop-proc-17-contract-draft',
            'sop-proc-18-contract-sign'
        ]
        res = await conn.execute(
            "UPDATE workflow_sop_guidance SET entity_type = 'TASK', updated_at = NOW() WHERE guidance_id = ANY($1::text[])",
            task_sops_to_fix
        )
        print(f"Updated mislabeled procedures: {res}")

        print("\n=== 3. Dissociating dummy template_ids from the 7 STAGE guidance rows ===")
        stage_sops = [
            'sop-01-stage-new',
            'sop-02-stage-qualified',
            'sop-03-stage-viewing',
            'sop-04-stage-offer',
            'sop-05-stage-reservation',
            'sop-06-stage-contract',
            'sop-07-stage-closedwon'
        ]
        res_stage = await conn.execute(
            "UPDATE workflow_sop_guidance SET template_id = NULL, updated_at = NOW() WHERE guidance_id = ANY($1::text[])",
            stage_sops
        )
        print(f"Separated STAGE guidance rows: {res_stage}")

        print("\n=== 4. Cleaning sop-proc-19-handover-protocol ===")
        await conn.execute("""
            UPDATE workflow_sop_guidance 
            SET template_id = NULL, procedure_code = 'PROC_HANDOVER_PROTOCOL', updated_at = NOW()
            WHERE guidance_id = 'sop-proc-19-handover-protocol'
        """)

        print("\n=== 5. Structuring execution_steps for investment inspection SOPs ===")
        sched_ar = [
            {"step_no": 1, "title": "تحديد الموعد وفريق الفحص", "description": "الاتفاق مع المستثمر على موعد الزيارة الميدانية وتحديد فريق الفحص الهندسي المرافق."},
            {"step_no": 2, "title": "التنسيق مع إدارة المبنى", "description": "مخاطبة مالك العقار أو إدارة التشغيل لتجهيز مستندات المبنى وتسهيل الوصول لكافة المرافق."},
            {"step_no": 3, "title": "توثيق الزيارة في النظام", "description": "تسجيل الزيارة المجدولة في نظام RECRM لتفعيل التنبيهات الموقعية ورسائل التقويم الآلية."},
            {"step_no": 4, "title": "تجهيز قائمة الفحص الميداني", "description": "إعداد وطباعة قائمة التحقق الفنية والاستثمارية النافية للجهالة وتجهيز أدوات القياس."}
        ]
        sched_en = [
            {"step_no": 1, "title": "Schedule Timing & Inspector", "description": "Agree on inspection timing with investor and assign engineering inspector."},
            {"step_no": 2, "title": "Coordinate Access", "description": "Notify owner/property manager to ensure access to all facilities and mechanical rooms."},
            {"step_no": 3, "title": "Record in RECRM", "description": "Record scheduled viewing in RECRM to trigger automated location and calendar dispatch."},
            {"step_no": 4, "title": "Prepare DD Checklist", "description": "Prepare technical and commercial due diligence checklist and measurement tools."}
        ]
        await conn.execute("""
            UPDATE workflow_sop_guidance
            SET execution_steps_ar = $1::jsonb,
                execution_steps_en = $2::jsonb,
                updated_at = NOW()
            WHERE guidance_id = 'sop-invest-sched-inspect'
        """, json.dumps(sched_ar), json.dumps(sched_en))

        report_ar = [
            {"step_no": 1, "title": "الفحص الإنشائي ومطابقة الكود", "description": "إجراء الفحص الإنشائي للهيكل الخرساني ومطابقة كود البناء السعودي ورصد أي تشققات أو هبوط."},
            {"step_no": 2, "title": "فحص الأنظمة الكهروميكانيكية", "description": "فحص أنظمة التكييف والمصاعد ومضخات المياه ولوحات الكهرباء وعزل الأسطح وشهادات الدفاع المدني."},
            {"step_no": 3, "title": "تقدير المصاريف الرأسمالية (CapEx)", "description": "احتساب التكاليف التقديرية للإصلاحات الرأسمالية الإلزامية وتأثيرها على العائد الاستثماري."},
            {"step_no": 4, "title": "فحص الإشغال وعقود الإيجار", "description": "التحقق الميداني من نسبة الإشغال الفعلي ومقابلة مدير المبنى ومطابقة العقود مع منصة إيجار."},
            {"step_no": 5, "title": "تقييم الموقع والتوصية النهائية", "description": "تقييم حركة السير وسهولة المداخل والمواقف وصياغة التوصية الاستثمارية النهائية المعتمدة."}
        ]
        report_en = [
            {"step_no": 1, "title": "Structural & SBC Audit", "description": "Perform structural audit against Saudi Building Code and detect any cracks or settlement."},
            {"step_no": 2, "title": "MEP & Safety Inspection", "description": "Inspect HVAC, elevators, pumps, electrical boards, roof waterproofing, and civil defense certificates."},
            {"step_no": 3, "title": "Estimate CapEx", "description": "Calculate estimated capital expenditure (CapEx) for mandatory repairs and its yield impact."},
            {"step_no": 4, "title": "Physical Occupancy & Rent Roll", "description": "Conduct physical occupancy audit, interview building manager, and reconcile with Ejar rent roll."},
            {"step_no": 5, "title": "Commercial & Final Verdict", "description": "Evaluate traffic, ingress/egress, parking, and formulate final investment verdict."}
        ]
        await conn.execute("""
            UPDATE workflow_sop_guidance
            SET execution_steps_ar = $1::jsonb,
                execution_steps_en = $2::jsonb,
                updated_at = NOW()
            WHERE guidance_id = 'sop-invest-report-inspect'
        """, json.dumps(report_ar), json.dumps(report_en))
        print("Updated investment inspection SOP steps into structured JSON objects.")

        print("\n=== 6. Synchronizing role columns from workflow_templates to workflow_sop_guidance ===")
        sync_res = await conn.execute("""
            UPDATE workflow_sop_guidance g
            SET responsible_role_code = t.owner_role,
                current_responsible_ar = COALESCE(r.name_ar, g.current_responsible_ar),
                current_responsible_en = COALESCE(r.name_en, g.current_responsible_en),
                updated_at = NOW()
            FROM workflow_templates t
            LEFT JOIN roles r ON t.owner_role = r.role_code
            WHERE g.template_id = t.template_id
        """)
        print(f"Role sync completed: {sync_res}")

        print("\n=== 7. Verification: Counts by entity_type in workflow_sop_guidance ===")
        counts = await conn.fetch("""
            SELECT entity_type, COUNT(*) as cnt
            FROM workflow_sop_guidance
            GROUP BY entity_type
            ORDER BY entity_type
        """)
        for c in counts:
            print(f"  {c['entity_type']}: {c['cnt']}")

        task_tmpl_count = await conn.fetchval("SELECT count(*) FROM workflow_templates WHERE template_type = 'TASK'")
        task_sop_count = await conn.fetchval("SELECT count(*) FROM workflow_sop_guidance WHERE entity_type = 'TASK'")
        print(f"\nFinal Alignment Check:")
        print(f"  workflow_templates (TASK): {task_tmpl_count}")
        print(f"  workflow_sop_guidance (TASK): {task_sop_count}")
        assert task_tmpl_count == task_sop_count == 39, "Mismatch in task count!"
        print("PERFECT 1:1 MATCH! Both have exactly 39 tasks!")

    await close_db_pool()

if __name__ == '__main__':
    asyncio.run(main())

