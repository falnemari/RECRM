import asyncio
import json
import asyncpg
from app.config import settings

async def main():
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    print("Connected to DB.")
    
    # 1. Insert TASK_INVEST_INSPECTION_REPORT first (points to TASK_INVEST_VALIDATE_FINANCIALS which already exists)
    await conn.execute("""
        INSERT INTO workflow_templates (
            template_id, template_type, standard_title_ar, standard_title_en,
            standard_subject_ar, standard_subject_en,
            owner_role, default_sla_minutes, completion_criteria_ar, completion_criteria_en,
            next_template_id, outcome_transitions, created_at
        ) VALUES (
            'TASK_INVEST_INSPECTION_REPORT', 'TASK',
            'الاستثمار — إعداد وتوثيق تقرير الفحص الفني والاستثماري (Due Diligence)',
            'Investment — Complete Due Diligence & Technical Inspection Report',
            'الاستثمار — إعداد وتوثيق تقرير الفحص الفني والاستثماري (Due Diligence)',
            'Investment — Complete Due Diligence & Technical Inspection Report',
            'INVESTMENT_ADVISOR', 2880,
            'إتمام المعاينة الميدانية وتوثيق كود البناء السعودي وتقدير CapEx والتحقق من عقود الإيجار.',
            'Field inspection, Saudi Building Code audit, CapEx estimation, and rent roll audit completed.',
            'TASK_INVEST_VALIDATE_FINANCIALS', $1::jsonb, NOW()
        )
        ON CONFLICT (template_id) DO UPDATE SET
            standard_title_ar = EXCLUDED.standard_title_ar,
            standard_title_en = EXCLUDED.standard_title_en,
            next_template_id = 'TASK_INVEST_VALIDATE_FINANCIALS',
            outcome_transitions = $1::jsonb
    """, json.dumps({
        "RECOMMENDED": "TASK_INVEST_VALIDATE_FINANCIALS",
        "COMPLETED": "TASK_INVEST_VALIDATE_FINANCIALS",
        "REJECTED": "TASK_INVEST_COMPARE_RETURNS",
        "NOT_RECOMMENDED": "TASK_INVEST_COMPARE_RETURNS"
    }))
    
    # 2. Insert TASK_INVEST_SCHEDULE_INSPECTION (points to TASK_INVEST_INSPECTION_REPORT which now exists)
    await conn.execute("""
        INSERT INTO workflow_templates (
            template_id, template_type, standard_title_ar, standard_title_en,
            standard_subject_ar, standard_subject_en,
            owner_role, default_sla_minutes, completion_criteria_ar, completion_criteria_en,
            next_template_id, outcome_transitions, created_at
        ) VALUES (
            'TASK_INVEST_SCHEDULE_INSPECTION', 'TASK',
            'الاستثمار — جدولة وتنسيق معاينة الفحص الفني والاستثماري',
            'Investment — Schedule Due Diligence Inspection',
            'الاستثمار — جدولة وتنسيق معاينة الفحص الفني والاستثماري',
            'Investment — Schedule Due Diligence Inspection',
            'INVESTMENT_ADVISOR', 1440,
            'جدولة موعد الفحص وتكليف الفاحص المختص وإشعار المالك والعميل المستثمر.',
            'Schedule inspection, assign technical inspector, and notify landlord and investor.',
            'TASK_INVEST_INSPECTION_REPORT', $1::jsonb, NOW()
        )
        ON CONFLICT (template_id) DO UPDATE SET
            standard_title_ar = EXCLUDED.standard_title_ar,
            standard_title_en = EXCLUDED.standard_title_en,
            next_template_id = 'TASK_INVEST_INSPECTION_REPORT',
            outcome_transitions = $1::jsonb
    """, json.dumps({"SCHEDULED": "TASK_INVEST_INSPECTION_REPORT", "CANCELLED": None}))
    
    # 3. Update TASK_INVEST_COMPARE_RETURNS
    await conn.execute("""
        UPDATE workflow_templates
        SET next_template_id = 'TASK_INVEST_SCHEDULE_INSPECTION',
            outcome_transitions = $1::jsonb
        WHERE template_id = 'TASK_INVEST_COMPARE_RETURNS'
    """, json.dumps({
        "COMPARED": "TASK_INVEST_SCHEDULE_INSPECTION",
        "SELECTED": "TASK_INVEST_SCHEDULE_INSPECTION"
    }))
    
    # 4. Seed SOP guidance rows
    await conn.execute("""
        INSERT INTO workflow_sop_guidance (
            guidance_id, stage_code, template_id, stage_name_ar, stage_name_en,
            required_now_ar, required_now_en, current_responsible_ar, current_responsible_en,
            next_action_ar, next_action_en, step_goal_ar, step_goal_en,
            mandatory_conditions_ar, mandatory_conditions_en,
            consequence_ar, consequence_en, display_order, is_active,
            entity_type, procedure_code, responsible_role_code,
            execution_steps_ar, execution_steps_en,
            sample_notes_ar, sample_notes_en, created_at, updated_at
        ) VALUES 
        (
            'sop-task-invest-sched-insp', 'INVESTMENT_QUALIFICATION', 'TASK_INVEST_SCHEDULE_INSPECTION',
            'مرحلة جدولة وفحص العقار الاستثماري', 'Investment Inspection Scheduling',
            'تنسيق موعد زيارة العقار مع فريق الهندسة والفحص الفني وممثل المالك',
            'Coordinate property site inspection date with engineering team and owner rep',
            'مستشار الاستثمار العقاري', 'Investment Advisor',
            'جدولة الموعد وتأكيد الحضور مع كافة الأطراف', 'Schedule inspection and confirm with all parties',
            'التأكد من التنسيق المسبق مع المالك لفتح كافة الوحدات وغرف الخدمات والمعدات',
            'Ensure advance coordination with landlord to access all plant rooms and meters',
            'مراجعة كود البناء السعودي وتوفر مخططات السلامة والدفاع المدني',
            'Review Saudi Building Code compliance and civil defense safety drawings',
            'إصدار جدول الزيارة وإشعار الأطراف المعنية', 'Issues site visit schedule and alerts stakeholders',
            15, true, 'TASK', 'TASK_INVEST_SCHEDULE_INSPECTION', 'INVESTMENT_ADVISOR',
            $1::jsonb, $2::jsonb,
            'تم التنسيق مع المالك وتحديد موعد الزيارة.', 'Site visit scheduled with owner.',
            NOW(), NOW()
        ),
        (
            'sop-task-invest-insp-rep', 'INVESTMENT_QUALIFICATION', 'TASK_INVEST_INSPECTION_REPORT',
            'مرحلة إعداد تقرير الفحص الاستثماري النافي للجهالة', 'Due Diligence & Technical Inspection Report',
            'توثيق الحالة الإنشائية والميكانيكية والمطابقة النظامية وإشغال المستأجرين',
            'Document structural, MEP, statutory compliance, and tenant occupancy state',
            'مستشار الاستثمار العقاري / مهندس الفحص', 'Investment Advisor / Inspector',
            'حفظ التقرير والاعتماد للانتقال للتدقيق المالي', 'Save & approve report to proceed to financial validation',
            'حساب CapEx الدقيق للتفاوض على خصم السعر أو الاستدامة التشغيلية',
            'Calculate precise CapEx for price discount negotiation and cash flow viability',
            'فحص الصك، رخص البناء، شهادة إتمام البناء، وعقود إيجار المستأجرين الموثقة',
            'Audit title deed, building permits, completion certificates, and registered Ejar contracts',
            'تثبيت تقرير الفحص وإتاحة استكمال التدقيق المالي', 'Locks due diligence report and enables financial validation task',
            16, true, 'TASK', 'TASK_INVEST_INSPECTION_REPORT', 'INVESTMENT_ADVISOR',
            $3::jsonb, $4::jsonb,
            'تم فحص العقار وتوثيق تقرير الحالة الهندسية وملاحظات كود البناء.', 'Property inspected, engineering status and SBC compliance documented.',
            NOW(), NOW()
        )
        ON CONFLICT (guidance_id) DO UPDATE SET
            template_id = EXCLUDED.template_id,
            stage_name_ar = EXCLUDED.stage_name_ar,
            stage_name_en = EXCLUDED.stage_name_en,
            required_now_ar = EXCLUDED.required_now_ar,
            required_now_en = EXCLUDED.required_now_en,
            execution_steps_ar = EXCLUDED.execution_steps_ar,
            execution_steps_en = EXCLUDED.execution_steps_en,
            updated_at = NOW();
    """,
    json.dumps([{"title": "التنسيق مع المالك", "step_no": 1, "description": "الاتصال بالمالك أو مدير الأملاك لتحديد موعد الزيارة."}]),
    json.dumps([{"title": "Coordinate with Landlord", "step_no": 1, "description": "Contact landlord or property manager to set visit date."}]),
    json.dumps([{"title": "الفحص الإنشائي", "step_no": 1, "description": "فحص الهيكل الإنشائي والتشققات وتمديدات السباكة والكهرباء."}, {"title": "فحص الإيجار", "step_no": 2, "description": "تدقيق سجلات التحصيل الفعلي وعقود إيجار المنصة."}]),
    json.dumps([{"title": "Structural Audit", "step_no": 1, "description": "Audit structural frame, MEP installations, and cracks."}, {"title": "Rent Roll Audit", "step_no": 2, "description": "Audit platform contracts and historical collections."}])
    )
    
    print("Missing templates seeded successfully!")
    await conn.close()

if __name__ == '__main__':
    asyncio.run(main())
