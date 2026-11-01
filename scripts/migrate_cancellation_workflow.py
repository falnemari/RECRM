"""
Migration script for Cancellation & Financial Settlement Workflows.
Seeds workflow_templates and workflow_sop_guidance with:
- TASK_DEAL_FINANCIAL_SETTLEMENT
- TASK_DEAL_INVENTORY_RELEASE
- ACT_DEAL_CANCELLATION_INITIATED
- ACT_DEAL_CANCELLATION_FINALIZED
- ACT_TASK_CANCELLED
"""
import asyncio
import os
import sys
import json

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

import asyncpg
from app.config import settings

async def migrate():
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    print("Connected to database.")

    # 1. Insert or update workflow_templates
    templates = [
        (
            "TASK_DEAL_FINANCIAL_SETTLEMENT",
            "TASK",
            "المالية — تسوية وإلغاء المعاملات المالية (إشعارات دائنة وتصفية العربون والمستحقات)",
            "Finance — Settle and Reconcile Financial Reversals (Credit Notes & Deposits)",
            "ACCOUNTANT",
            2880,
            "مراجعة كافة الفواتير الصادرة للصفقة، إصدار إشعارات دائنة ضريبية للفواتير الملغاة، وتوثيق استرداد أو تسوية مبالغ العربون نظاماً للحساب البنكي.",
            "Review invoices, issue tax credit notes for cancelled invoices, and record deposit refunds/reconciliation."
        ),
        (
            "TASK_DEAL_INVENTORY_RELEASE",
            "TASK",
            "العمليات والمخزون — فك حجز الوحدة العقارية وإعادتها للمخزون المتاح (AVAILABLE)",
            "Operations — Release Unit Reservation Back to Available Inventory",
            "SALES_AGENT",
            720,
            "تأكيد فك الحجز وإلغاء الحجوزات النشطة وإعادة الوحدة لحالة متاح (AVAILABLE) وإلغاء المعاينات والعروض المفتوحة.",
            "Confirm unreserving the unit, cancel active reservations, revert status to AVAILABLE, and cancel open viewings."
        ),
        (
            "ACT_DEAL_CANCELLATION_INITIATED",
            "ACTIVITY",
            "الصفقة — بدء مسار الإلغاء وتفريع مهام التسوية المالية والتشغيلية",
            "Deal — Cancellation Initiated & Settlement Tasks Spawned",
            "SYSTEM",
            0,
            "بدء إجراءات الإلغاء رسمياً وتوليد مهام التسوية المالية والتشغيلية وتجميد الصفقة في مرحلة UNDER_CANCELLATION.",
            "Officially initiate deal cancellation and spawn mandatory financial and inventory settlement tasks."
        ),
        (
            "ACT_DEAL_CANCELLATION_FINALIZED",
            "ACTIVITY",
            "الصفقة — اكتمال كافة التسويات وإلغاء الصفقة نهائياً (CLOSED_LOST)",
            "Deal — All Reversals Completed & Deal Finally Cancelled (CLOSED_LOST)",
            "SYSTEM",
            0,
            "التحقق من إنجاز كافة مهام التسوية وإشعارات الدائن وفك الحجز، وإغلاق الصفقة كملغاة نهائياً.",
            "Verify all settlement tasks, credit notes and inventory release completed, closing deal as CLOSED_LOST."
        ),
        (
            "ACT_TASK_CANCELLED",
            "ACTIVITY",
            "المهمة — إلغاء المهمة وتوثيق سبب الاعتذار أو عدم التوفر",
            "Task — Task Cancelled & Reason Documented",
            "SYSTEM",
            0,
            "إلغاء المهمة وتوثيق مبررات وسبب الإلغاء وسجل المتابعة.",
            "Task cancelled and cancellation reasons and notes preserved."
        )
    ]

    for t in templates:
        await conn.execute(
            """
            INSERT INTO workflow_templates (
                template_id, template_type, standard_title_ar, standard_title_en,
                standard_subject_ar, standard_subject_en,
                owner_role, default_sla_minutes, completion_criteria, created_at
            ) VALUES ($1, $2, $3, $4, $3, $4, $5, $6, $7, NOW())
            ON CONFLICT (template_id) DO UPDATE SET
                template_type = EXCLUDED.template_type,
                standard_title_ar = EXCLUDED.standard_title_ar,
                standard_title_en = EXCLUDED.standard_title_en,
                standard_subject_ar = EXCLUDED.standard_title_ar,
                standard_subject_en = EXCLUDED.standard_title_en,
                owner_role = EXCLUDED.owner_role,
                default_sla_minutes = EXCLUDED.default_sla_minutes,
                completion_criteria = EXCLUDED.completion_criteria
            """,
            t[0], t[1], t[2], t[3], t[4], t[5], t[6]
        )
    print("workflow_templates seeded successfully.")

    # 2. Insert into workflow_sop_guidance
    guidances = [
        (
            "guidance-deal-fin-settlement",
            "UNDER_CANCELLATION",
            "TASK_DEAL_FINANCIAL_SETTLEMENT",
            "قيد إجراءات الإلغاء والتسوية المالية",
            "Under Cancellation & Financial Settlement",
            "حصر الفواتير الصادرة والمدفوعات ومبالغ العربون وإصدار إشعارات دائنة وتسوية المستحقات البنكية",
            "Audit invoices, payments, and deposits, issue tax credit notes, and execute bank refunds",
            "المحاسب المالي / الإدارة المالية",
            "Accountant / Finance Department",
            "إصدار إشعار دائن للفواتير وإجراء التحويل البنكي للمستردات",
            "Issue tax credit notes and execute bank transfer for refunds",
            "حماية المكتب والعميل نظامياً وإبراء الذمة المالية والامتثال لضوابط الفوترة الإلكترونية ZATCA وهيئة العقار",
            "Ensure statutory protection, financial clearance, and compliance with ZATCA Phase 2 & REGA regulations",
            "إلزامية إصدار إشعار دائن ضريبي معتمد للفواتير الصادرة، والتحويل لنفس حساب العميل المصرفي درءاً لغسل الأموال",
            "Mandatory tax credit note issuance, and bank refund strictly to the client original bank account",
            "تجميد إنهاء الصفقة حتى اعتماد التسوية وتصفية المستحقات بالكامل",
            "Deal remains frozen in UNDER_CANCELLATION until financial settlement is certified",
            1,
            "TASK",
            "PROC_DEAL_SETTLEMENT",
            "ACCOUNTANT",
            json.dumps([
                "حصر جميع الفواتير الصادرة للصفقة ومطابقتها وتحديد المبالغ المحصلة والمعلقة.",
                "إصدار إشعار دائن ضريبي معتمد للفواتير غير المستحقة وربطها برقم الفاتورة الأصلية.",
                "تحديد مصير العربون والمدفوعات وفق نظام المعاملات المدنية ولائحة الوساطة العقارية.",
                "تنفيذ الحوالة البنكية المستردة حصراً إلى نفس الحساب المصرفي للعميل وتوثيق رقم المرجع البنكي.",
                "اعتماد التسوية وإغلاق المهمة لتحرير اكتمال إلغاء الصفقة."
            ], ensure_ascii=False),
            json.dumps([
                "Audit all issued deal invoices and tally collected vs pending amounts.",
                "Issue approved tax credit notes referencing original tax invoices.",
                "Determine deposit disposition according to civil transaction rules.",
                "Execute bank refund strictly to the client original account and log reference.",
                "Certify financial settlement and complete task."
            ])
        ),
        (
            "guidance-deal-inv-release",
            "UNDER_CANCELLATION",
            "TASK_DEAL_INVENTORY_RELEASE",
            "قيد إجراءات الإلغاء وتفكيك الحجز",
            "Under Cancellation & Inventory Release",
            "إلغاء حجز الوحدة العقارية وتحويل حالتها إلى (AVAILABLE) وتوثيق الحركة في سجل المخزون",
            "Cancel unit reservation, revert status to AVAILABLE, and log in inventory history",
            "الوسيط العقاري / مسؤول العمليات والمخزون",
            "Sales Agent / Inventory Manager",
            "تأكيد فك الحجز وإلغاء أي مواعيد معاينة أو عروض مالية مرتبطة",
            "Confirm unreserving the unit and cancel linked viewings or proposals",
            "إعادة إتاحة الأصل العقاري للتسويق والبيع وتفادي تجميد الوحدات المتاحة للمشترين والمستأجرين",
            "Re-release property to active market inventory and prevent locking available assets",
            "تحديث حالة الوحدة في المخزون تلقائياً إلى AVAILABLE وإلغاء الحجز",
            "Unit status must transition to AVAILABLE with reservation status CANCELLED",
            "تظل الصفقة معلقة حتى تأكيد فك الحجز لضمان عودة العقار للسوق",
            "Deal cannot finalize cancellation until unit is safely released",
            2,
            "TASK",
            "PROC_INVENTORY_RELEASE",
            "SALES_AGENT",
            json.dumps([
                "التحقق من رقم الوحدة العقارية والحجز المرتبط بالصفقة الملغاة.",
                "إلغاء اتفاقية الحجز المؤقتة وسحب أي عروض معلقة.",
                "فك قفل الوحدة وتحديث حالتها في النظام إلى (متاح AVAILABLE).",
                "تسجيل سبب فك الحجز في سجل حركات وتاريخ حالة العقار.",
                "تأكيد الإنجاز بنجاح لتمكين النظام من استكمال الإلغاء النهائي للصفقة."
            ], ensure_ascii=False),
            json.dumps([
                "Verify unit number and active reservation linked to the cancelled deal.",
                "Cancel temporary reservation agreement and retract pending offers.",
                "Unlock unit and revert status in system back to AVAILABLE.",
                "Record status change reason in unit_status_history.",
                "Confirm completion to unblock final deal cancellation."
            ])
        )
    ]

    for g in guidances:
        await conn.execute(
            """
            INSERT INTO workflow_sop_guidance (
                guidance_id, stage_code, template_id, stage_name_ar, stage_name_en,
                required_now_ar, required_now_en, current_responsible_ar, current_responsible_en,
                next_action_ar, next_action_en, step_goal_ar, step_goal_en,
                mandatory_conditions_ar, mandatory_conditions_en, consequence_ar, consequence_en,
                display_order, is_active, created_at, updated_at, entity_type,
                procedure_code, responsible_role_code, execution_steps_ar, execution_steps_en
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, true, NOW(), NOW(), $19, $20, $21, $22, $23)
            ON CONFLICT (guidance_id) DO UPDATE SET
                stage_code = EXCLUDED.stage_code,
                template_id = EXCLUDED.template_id,
                stage_name_ar = EXCLUDED.stage_name_ar,
                stage_name_en = EXCLUDED.stage_name_en,
                required_now_ar = EXCLUDED.required_now_ar,
                required_now_en = EXCLUDED.required_now_en,
                current_responsible_ar = EXCLUDED.current_responsible_ar,
                current_responsible_en = EXCLUDED.current_responsible_en,
                next_action_ar = EXCLUDED.next_action_ar,
                next_action_en = EXCLUDED.next_action_en,
                step_goal_ar = EXCLUDED.step_goal_ar,
                step_goal_en = EXCLUDED.step_goal_en,
                mandatory_conditions_ar = EXCLUDED.mandatory_conditions_ar,
                mandatory_conditions_en = EXCLUDED.mandatory_conditions_en,
                consequence_ar = EXCLUDED.consequence_ar,
                consequence_en = EXCLUDED.consequence_en,
                display_order = EXCLUDED.display_order,
                updated_at = NOW(),
                entity_type = EXCLUDED.entity_type,
                procedure_code = EXCLUDED.procedure_code,
                responsible_role_code = EXCLUDED.responsible_role_code,
                execution_steps_ar = EXCLUDED.execution_steps_ar,
                execution_steps_en = EXCLUDED.execution_steps_en
            """,
            g[0], g[1], g[2], g[3], g[4], g[5], g[6], g[7], g[8], g[9], g[10], g[11], g[12], g[13], g[14], g[15], g[16], g[17], g[18], g[19], g[20], g[21], g[22]
        )
    print("workflow_sop_guidance seeded successfully.")
    await conn.close()
    print("Migration finished successfully.")

if __name__ == "__main__":
    asyncio.run(migrate())
