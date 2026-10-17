#!/usr/bin/env python3
"""
Workflow Schema Migration for RECRM
Applies the Workflow Template Catalog, Task/Activity/Communication columns,
and anti-duplication indexes across both 'redb' and 're_db'.
"""

import sys
import asyncio
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent / "src" / "backend"
sys.path.insert(0, str(backend_dir))

import asyncpg
from app.config import settings

TARGET_DBS = ["redb", "re_db"]

MIGRATION_SQL = """
-- 1. Workflow Template Catalog Table
CREATE TABLE IF NOT EXISTS workflow_templates (
    template_id VARCHAR(64) PRIMARY KEY,
    template_type VARCHAR(20) NOT NULL, -- 'TASK', 'ACTIVITY', 'COMMUNICATION'
    standard_title_ar VARCHAR(255) NOT NULL,
    standard_title_en VARCHAR(255) NOT NULL,
    standard_subject_ar VARCHAR(255),
    standard_subject_en VARCHAR(255),
    owner_role VARCHAR(50) NOT NULL,
    default_sla_minutes INTEGER DEFAULT 30,
    completion_criteria TEXT,
    escalation_role VARCHAR(50),
    escalation_sla_minutes INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Enhance tasks table
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS template_id VARCHAR(64);
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS parent_task_id VARCHAR(64);
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS escalation_level INTEGER DEFAULT 0;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS escalated_to_user_id VARCHAR(64);
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

-- 3. Enhance activities table
ALTER TABLE activities ADD COLUMN IF NOT EXISTS template_id VARCHAR(64);
ALTER TABLE activities ADD COLUMN IF NOT EXISTS task_id VARCHAR(64);
ALTER TABLE activities ADD COLUMN IF NOT EXISTS outcome VARCHAR(64);
ALTER TABLE activities ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- 4. Enhance communications table
ALTER TABLE communications ADD COLUMN IF NOT EXISTS template_id VARCHAR(64);
ALTER TABLE communications ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();

-- 5. Anti-duplication unique partial index for open tasks
DROP INDEX IF EXISTS idx_prevent_duplicate_open_task;
CREATE UNIQUE INDEX idx_prevent_duplicate_open_task 
ON tasks (
    COALESCE(lead_id, ''), 
    COALESCE(opportunity_id, ''), 
    COALESCE(customer_id, ''), 
    template_id
)
WHERE status IN ('PENDING', 'OPEN', 'IN_PROGRESS');

-- 6. Enhance viewings table for direct lead tracking and audit timestamps
ALTER TABLE viewings ADD COLUMN IF NOT EXISTS lead_id VARCHAR(64) REFERENCES leads(lead_id) ON DELETE SET NULL;
ALTER TABLE viewings ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE viewings ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- 7. Seed Workflow Templates for Stages A, B, C, D, and E
INSERT INTO workflow_templates (
    template_id, template_type, standard_title_ar, standard_title_en,
    standard_subject_ar, standard_subject_en, owner_role, default_sla_minutes,
    completion_criteria, escalation_role, escalation_sla_minutes
) VALUES 
-- Stage A: Lead Intake, Deduplication & Assignment
(
    'TASK_LEAD_FIRST_CONTACT', 'TASK',
    'الطلب — الاتصال الأولي', 'Lead — First Contact',
    NULL, NULL,
    'SALES_AGENT', 30,
    'تسجيل محاولة الاتصال والنتيجة في الأنشطة / Record contact attempt and outcome',
    'BRANCH_MANAGER', 45
),
(
    'TASK_LEAD_ASSIGN', 'TASK',
    'الطلب — توجيه وتعيين وسيط', 'Lead — Assign Sales Agent',
    NULL, NULL,
    'SALES_MANAGER', 15,
    'اختيار وتعيين وسيط مبيعات للطلب / Assign a dedicated sales agent to the lead',
    'GENERAL_MANAGER', 30
),
(
    'TASK_LEAD_COMPLETE_INFO', 'TASK',
    'الطلب — استكمال البيانات الناقصة', 'Lead — Complete Missing Information',
    NULL, NULL,
    'SALES_AGENT', 120,
    'استكمال بيانات الاتصال أو متطلبات العقار الناقصة / Complete missing contact or inquiry details',
    'BRANCH_MANAGER', 240
),
(
    'COMM_LEAD_INITIAL_CONTACT', 'COMMUNICATION',
    'الطلب — إشعار استلام الطلب والترحيب', 'Lead — Welcome Notification',
    'تم استلام طلبك العقاري بنجاح — ري كيرم', 'Your Real Estate Request Has Been Received — RECRM',
    'SYSTEM', 0,
    'إرسال رسالة الترحيب بنجاح للعميل / Welcome message successfully sent',
    NULL, NULL
),
(
    'ACT_LEAD_CREATED', 'ACTIVITY',
    'الطلب — إنشاء وتعيين الطلب', 'Lead — Created & Assigned',
    NULL, NULL,
    'SYSTEM', 0,
    'تسجيل استلام الطلب وتعيينه للمستشار / Log intake and assignment',
    NULL, NULL
),
(
    'ACT_LEAD_ROUTED', 'ACTIVITY',
    'الطلب — توجيه لمدير الفرع', 'Lead — Routed to Branch Manager',
    NULL, NULL,
    'SYSTEM', 0,
    'توجيه الطلب لمدير فرع المدينة لتعيين وسيط / Route lead to branch manager for assignment',
    NULL, NULL
),
(
    'ACT_LEAD_ASSIGNED', 'ACTIVITY',
    'الطلب — تعيين وتوجيه الوسيط', 'Lead — Assigned to Agent',
    NULL, NULL,
    'BRANCH_MANAGER', 0,
    'توثيق تعيين أو إعادة توجيه الطلب لوسيط مبيعات معتمد / Log assignment or reassignment of lead to agent',
    NULL, NULL
),
-- Stage B: First Contact & Qualification
(
    'TASK_LEAD_FOLLOWUP', 'TASK',
    'الطلب — اتصال متابعة', 'Lead — Follow-up Contact',
    NULL, NULL,
    'SALES_AGENT', 180,
    'تسجيل اتصال متابعة وتحديث رغبة العميل / Record follow-up call and client intent',
    'BRANCH_MANAGER', 240
),
(
    'TASK_LEAD_QUALIFY', 'TASK',
    'الطلب — استكمال معايير التأهيل', 'Lead — Complete Qualification',
    NULL, NULL,
    'SALES_AGENT', 1440,
    'تحديد الميزانية، المدينة، نوع العقار وتأكيد الجدية / Define budget, city, property type and intent',
    'BRANCH_MANAGER', 2880
),
(
    'ACT_LEAD_FIRST_CONTACT', 'ACTIVITY',
    'الطلب — تسجيل الاتصال الأولي', 'Lead — First Contact Recorded',
    NULL, NULL,
    'SALES_AGENT', 0,
    'توثيق المكالمة أو رسالة الواتساب بنتيجة مؤكدة / Log call or WhatsApp with outcome',
    NULL, NULL
),
(
    'ACT_LEAD_FOLLOWUP', 'ACTIVITY',
    'الطلب — تسجيل اتصال متابعة', 'Lead — Follow-up Recorded',
    NULL, NULL,
    'SALES_AGENT', 0,
    'توثيق متابعة العميل وتسجيل التحديث / Log follow-up details',
    NULL, NULL
),
(
    'ACT_LEAD_QUALIFIED', 'ACTIVITY',
    'الطلب — اكتمال التأهيل والترقية لفرصة', 'Lead — Qualified & Converted',
    NULL, NULL,
    'SALES_AGENT', 0,
    'تحويل الطلب لفرصة بيعية وعميل دائم / Convert lead to opportunity and permanent customer',
    NULL, NULL
),
-- Stage C: Property Matching & Recommendations
(
    'TASK_OPPORTUNITY_MATCH_PROPERTIES', 'TASK',
    'الفرصة — مطابقة وترشيح العقارات', 'Opportunity — Match Properties',
    NULL, NULL,
    'SALES_AGENT', 240,
    'البحث في المخزون المتاح وترشيح وحدات متوافقة مع ميزانية ومتطلبات العميل / Search inventory and match properties with client preferences',
    'BRANCH_MANAGER', 480
),
(
    'ACT_OPPORTUNITY_PROPERTIES_PRESENTED', 'ACTIVITY',
    'الفرصة — استعراض وترشيح العقارات للعميل', 'Opportunity — Properties Presented',
    NULL, NULL,
    'SALES_AGENT', 0,
    'توثيق عرض الوحدات العقارية المطابقة على العميل / Log presentation of matched properties to client',
    NULL, NULL
),
(
    'COMM_OPPORTUNITY_RECOMMENDATIONS', 'COMMUNICATION',
    'الفرصة — إرسال توصيات الوحدات المقترحة', 'Opportunity — Property Recommendations',
    'خيارات عقارية مقترحة لطلبك العقاري — ري كيرم', 'Recommended Properties for Your Inquiry — RECRM',
    'SALES_AGENT', 0,
    'إرسال تفاصيل الوحدات المرشحة للعميل عبر الواتساب / Send matched property recommendations to customer via WhatsApp',
    NULL, NULL
),
-- Stage D: Property Viewings & Site Visits
(
    'TASK_VIEWING_SCHEDULE', 'TASK',
    'المعاينة — جدولة الزيارة الميدانية', 'Viewing — Schedule Site Visit',
    NULL, NULL,
    'SALES_AGENT', 1440,
    'تحديد تاريخ ووقت المعاينة الميدانية ومطابقة العقار مع العميل / Schedule site visit and match unit with client',
    'BRANCH_MANAGER', 2880
),
(
    'COMM_VIEWING_CONFIRMATION', 'COMMUNICATION',
    'المعاينة — تأكيد موعد وموقع المعاينة', 'Viewing — Confirmation & Location',
    'تأكيد موعد المعاينة الميدانية وموقع العقار — ري كيرم', 'Property Viewing Confirmation & Location Map — RECRM',
    'SYSTEM', 0,
    'إرسال تفاصيل الموعد ورابط الموقع للعميل / Send appointment details and location link to customer',
    NULL, NULL
),
(
    'COMM_VIEWING_REMINDER', 'COMMUNICATION',
    'المعاينة — تذكير بموعد الزيارة الميدانية', 'Viewing — Customer Reminder',
    'تذكير بموعد المعاينة الميدانية اليوم — ري كيرم', 'Reminder: Property Viewing Today — RECRM',
    'SYSTEM', 0,
    'إرسال رسالة تذكير آلية للعميل قبل موعد الزيارة / Send automated viewing appointment reminder to customer',
    NULL, NULL
),
(
    'ACT_VIEWING_SCHEDULED', 'ACTIVITY',
    'المعاينة — تأكيد موعد الزيارة الميدانية', 'Viewing — Site Visit Scheduled',
    NULL, NULL,
    'SALES_AGENT', 0,
    'تسجيل تفاصيل موعد الزيارة والعقار المحدد / Log site visit appointment details',
    NULL, NULL
),
(
    'TASK_VIEWING_REPORT', 'TASK',
    'المعاينة — رفع تقرير وتقييم الزيارة', 'Viewing — Submit Inspection Report',
    NULL, NULL,
    'SALES_AGENT', 120,
    'تسجيل تقييم ورغبة العميل بعد الزيارة (مهتم / بديل / غير مهتم) / Record client feedback and next step after visit',
    'BRANCH_MANAGER', 240
),
(
    'TASK_VIEWING_RESCHEDULE', 'TASK',
    'المعاينة — إعادة جدولة موعد الزيارة', 'Viewing — Reschedule Site Visit',
    NULL, NULL,
    'SALES_AGENT', 240,
    'التواصل مع العميل لتحديد موعد بديل بعد تعذر الزيارة الأولى أو عدم الحضور / Contact customer to reschedule viewing after cancellation or no-show',
    'BRANCH_MANAGER', 480
),
(
    'ACT_VIEWING_REPORT_SUBMITTED', 'ACTIVITY',
    'المعاينة — توثيق تقرير وتقييم الزيارة', 'Viewing — Inspection Report Documented',
    NULL, NULL,
    'SALES_AGENT', 0,
    'توثيق رغبة وملاحظات العميل بعد المعاينة الميدانية / Document client feedback after viewing',
    NULL, NULL
),
-- Stage E: Offers & Negotiation
(
    'TASK_OFFER_SUBMIT', 'TASK',
    'العرض — تقديم العرض المالي للوحدة', 'Offer — Submit Formal Offer',
    NULL, NULL,
    'SALES_AGENT', 720,
    'إدخال مبلغ العرض وشروط السداد للوحدة / Enter offer amount and payment terms',
    'BRANCH_MANAGER', 1440
),
(
    'TASK_OFFER_PREPARE', 'TASK',
    'العرض — إعداد وتقديم العرض التجاري', 'Offer — Prepare Proposal',
    NULL, NULL,
    'SALES_AGENT', 720,
    'إدخال مبلغ العرض وشروط السداد للوحدة وإرسالها للعميل / Enter offer amount and terms and send proposal to customer',
    'BRANCH_MANAGER', 1440
),
(
    'ACT_OFFER_CREATED', 'ACTIVITY',
    'العرض — إنشاء العرض التجاري', 'Offer — Created',
    NULL, NULL,
    'SALES_AGENT', 0,
    'تسجيل إنشاء مسودة العرض المالي / Log creation of commercial offer',
    NULL, NULL
),
(
    'COMM_OFFER_PROPOSAL_SENT', 'COMMUNICATION',
    'العرض — إرسال مسودة العرض للعميل', 'Offer — Proposal Sent',
    'عرض السعر الرسمي للوحدة العقارية — ري كيرم', 'Official Price Proposal for Property — RECRM',
    'SALES_AGENT', 0,
    'إرسال مسودة العرض والتفاصيل للعميل عبر الواتساب أو البريد / Send offer details to client via WhatsApp or email',
    NULL, NULL
),
(
    'TASK_OFFER_FOLLOWUP', 'TASK',
    'العرض — متابعة رد العميل قبل انتهاء الصلاحية', 'Offer — Follow-up Before Expiry',
    NULL, NULL,
    'SALES_AGENT', 1440,
    'متابعة العميل لمعرفة قراره النهائي بشأن العرض قبل انتهاء صلاحيته / Follow up with client regarding their decision before offer expires',
    'BRANCH_MANAGER', 2880
),
(
    'TASK_OFFER_MANAGER_APPROVAL', 'TASK',
    'العرض — اعتماد العرض المالي المخفض', 'Offer — Manager Approval',
    NULL, NULL,
    'BRANCH_MANAGER', 240,
    'مراجعة واعتماد أو رفض العرض الذي يتجاوز نسبة الخصم المسموحة (5%) / Review and approve or reject offer exceeding standard discount authority',
    'SALES_DIRECTOR', 480
),
(
    'ACT_OFFER_SUBMITTED', 'ACTIVITY',
    'العرض — تقديم العرض المالي المعتمد', 'Offer — Formal Offer Submitted',
    NULL, NULL,
    'SALES_AGENT', 0,
    'توثيق تقديم العرض المالي للمالك / Log formal offer submission',
    NULL, NULL
),
(
    'ACT_OFFER_DECISION', 'ACTIVITY',
    'العرض — توثيق قرار العرض المالي', 'Offer — Decision Recorded',
    NULL, NULL,
    'SYSTEM', 0,
    'توثيق قبول أو رفض أو تقديم عرض مقابل للعرض المالي / Log offer decision (accepted, rejected, countered)',
    NULL, NULL
),
(
    'COMM_OFFER_DECISION_COMMUNICATED', 'COMMUNICATION',
    'العرض — إشعار العميل بقرار العرض المالي', 'Offer — Decision Communicated',
    'تحديث بشأن العرض المالي المقدم — ري كيرم', 'Update Regarding Your Property Offer — RECRM',
    'SALES_AGENT', 0,
    'إشعار العميل بقبول أو رفض أو شروط العرض المعتمدة / Notify client of approved offer terms or response',
    NULL, NULL
),
-- Stage F: Reservation & Financial Coordination
(
    'TASK_RESERVATION_VERIFY_AVAILABILITY', 'TASK',
    'الحجز — التحقق من جاهزية وتوفر الوحدة', 'Reservation — Verify Unit Availability',
    NULL, NULL,
    'SALES_AGENT', 120,
    'التحقق التبادلي الصارم من توفر الوحدة وخلوها من أي حجز مسبق / Transactional verification that unit is available and unencumbered',
    'BRANCH_MANAGER', 240
),
(
    'ACT_RESERVATION_AVAILABILITY_VERIFIED', 'ACTIVITY',
    'الحجز — تأكيد جاهزية الوحدة للحجز', 'Reservation — Availability Verified',
    NULL, NULL,
    'SYSTEM', 0,
    'توثيق نجاح فحص جاهزية الوحدة وتأكيد توفرها / Document successful verification of unit availability',
    NULL, NULL
),
(
    'TASK_RESERVATION_DOCUMENTS', 'TASK',
    'الحجز — استكمال المستندات الإلزامية', 'Reservation — Complete Required Documents',
    NULL, NULL,
    'SALES_AGENT', 1440,
    'استكمال ورفع الهوية الوطنية وسجل الحجز والمستندات المطلوبة / Complete and upload national ID, reservation form and required documents',
    'BRANCH_MANAGER', 2880
),
(
    'TASK_RESERVATION_DEPOSIT_FOLLOWUP', 'TASK',
    'الحجز — متابعة سداد وتدقيق العربون', 'Reservation — Deposit Follow-up',
    NULL, NULL,
    'ACCOUNTANT', 2880,
    'التأكد من إيداع مبلغ العربون في الحساب البنكي وتسجيل سند القبض / Verify deposit received in bank account and issue receipt',
    'BRANCH_MANAGER', 4320
),
(
    'COMM_RESERVATION_CONFIRMATION', 'COMMUNICATION',
    'الحجز — إشعار تأكيد الحجز وسند العربون', 'Reservation — Confirmation & Deposit Instructions',
    'تأكيد حجز الوحدة العقارية وبيانات العربون — ري كيرم', 'Unit Reservation Confirmation & Deposit Details — RECRM',
    'SYSTEM', 0,
    'إرسال بيانات الحجز ورقم السند ورابط السداد للعميل / Send reservation details, reference number and payment instructions to customer',
    NULL, NULL
),
(
    'TASK_RESERVATION_EXPIRY_REVIEW', 'TASK',
    'الحجز — مراجعة وإدارة الحجز قبل الانتهاء', 'Reservation — Expiry Review',
    NULL, NULL,
    'BRANCH_MANAGER', 720,
    'مراجعة الحجز الموشك على الانتهاء لطلب تمديد أو تحرير الوحدة / Review expiring reservation to approve extension or release unit back to inventory',
    'SALES_DIRECTOR', 1440
),
(
    'ACT_RESERVATION_CONFIRMED', 'ACTIVITY',
    'الحجز — اعتماد الحجز وقفل الوحدة', 'Reservation — Confirmed',
    NULL, NULL,
    'SYSTEM', 0,
    'توثيق اعتماد حجز الوحدة وتحديث حالتها إلى محجوزة في سجل العقار / Document reservation confirmation and update unit status to RESERVED in inventory',
    NULL, NULL
),
-- Stage G: Contract Preparation, Signing and Closure
(
    'TASK_CONTRACT_DRAFT', 'TASK',
    'العقد — صياغة وإعداد مسودة العقد الرسمي', 'Contract — Prepare Draft',
    NULL, NULL,
    'LEGAL', 1440,
    'إعداد مسودة العقد وفق الشروط المعتمدة ونموذج الهيئة العامة للعقار / Prepare contract draft complying with REGA standard agreement',
    'BRANCH_MANAGER', 2880
),
(
    'ACT_CONTRACT_DRAFT_CREATED', 'ACTIVITY',
    'العقد — إنشاء وإصدار مسودة العقد', 'Contract — Draft Created',
    NULL, NULL,
    'LEGAL', 0,
    'توثيق صياغة مسودة العقد وإصدار النسخة الأولى / Document drafting and initial issuance of contract agreement',
    NULL, NULL
),
(
    'TASK_CONTRACT_INTERNAL_REVIEW', 'TASK',
    'العقد — المراجعة القانونية والاعتماد الداخلي', 'Contract — Internal Review',
    NULL, NULL,
    'LEGAL', 1440,
    'تدقيق بنود العقد والتأكد من مطابقة الأسعار والبيانات قبل إرسالها للتوقيع / Verify legal clauses, pricing and parties information before signature dispatch',
    'BRANCH_MANAGER', 2880
),
(
    'COMM_CONTRACT_REVIEW_REQUIRED', 'COMMUNICATION',
    'العقد — إشعار داخلي: مسودة العقد جاهزة للتدقيق', 'Contract — Review Required',
    'طلب مراجعة واعتماد مسودة عقد بيع/إيجار — ري كيرم', 'Internal Notification: Contract Draft Ready for Review — RECRM',
    'SYSTEM', 0,
    'إرسال إشعار داخلي للمراجع القانوني والمدير لتدقيق المسودة / Send internal notification to legal reviewer and manager',
    NULL, NULL
),
(
    'TASK_CONTRACT_SIGNATURE', 'TASK',
    'العقد — متابعة توقيع العقد من العميل والأطراف', 'Contract — Customer Signature',
    NULL, NULL,
    'SALES_AGENT', 2880,
    'متابعة توقيع العميل إلكترونياً أو حضورياً وتوثيق التوقيع المعتمد / Follow up with customer for digital or in-person signing and record signed agreement',
    'BRANCH_MANAGER', 4320
),
(
    'COMM_CONTRACT_SIGNATURE_INSTRUCTIONS', 'COMMUNICATION',
    'العقد — إرسال إرشادات ورابط توقيع العقد للعميل', 'Contract — Signature Instructions',
    'رابط وإرشادات توقيع العقد النهائي — ري كيرم', 'Final Contract Signature Link & Instructions — RECRM',
    'SALES_AGENT', 0,
    'إرسال رابط منصة إيجار أو منصة التوقيع الرقمي للعميل مع الإرشادات / Send digital signing instructions and link to client',
    NULL, NULL
),
(
    'ACT_CONTRACT_SIGNED', 'ACTIVITY',
    'العقد — توثيق اكتمال توقيع العقد رسمياً', 'Contract — Signed',
    NULL, NULL,
    'SYSTEM', 0,
    'توثيق اكتمال تواقيع كافة الأطراف على العقد وتحديث حالته / Document complete execution of contract signatures',
    NULL, NULL
),
(
    'TASK_CONTRACT_RECONCILIATION', 'TASK',
    'العقد — المطابقة المالية وتسوية جدول الدفعات', 'Contract — Payment and Reconciliation',
    NULL, NULL,
    'ACCOUNTANT', 2880,
    'تدقيق سداد الدفعة الأولى، اعتماد جدول الأقساط، ومطابقة الحسابات البنكية / Verify down payment, generate receivables schedule, and reconcile bank deposits',
    'BRANCH_MANAGER', 4320
),
(
    'TASK_CONTRACT_HANDOVER', 'TASK',
    'العقد — الفحص الفني وتسليم الوحدة للعميل', 'Contract — Finalize Handover',
    NULL, NULL,
    'PROPERTY_MANAGEMENT', 4320,
    'توقيع محضر الاستلام والتسليم الفني وتسليم المفاتيح للمشتري / Sign technical handover report and transfer keys/possession to buyer/tenant',
    'BRANCH_MANAGER', 5760
),
(
    'ACT_CONTRACT_CLOSED', 'ACTIVITY',
    'العقد — إغلاق الصفقة وتحديث وضع الوحدة إلى مباعة', 'Contract — Closed & Deal Won',
    NULL, NULL,
    'SYSTEM', 0,
    'إغلاق الصفقة بنجاح، تحويل الوحدة إلى مباعة، وإدراج عمولة الوسيط في سجل المستحقات / Close deal as won, update unit to SOLD, and register broker commission pending payout',
    NULL, NULL
),
-- General / Reopen & Smart Undo
(
    'ACT_TASK_REOPENED', 'ACTIVITY',
    'المهمة — إعادة فتح وتراجع ذكي', 'Task — Reopened & Smart Undo',
    NULL, NULL,
    'SALES_AGENT', 0,
    'توثيق التراجع عن إكمال المهمة وإعادة فتحها وإلغاء المهام التابعة / Log task completion reversal and smart undo',
    NULL, NULL
)
ON CONFLICT (template_id) DO UPDATE SET
    template_type = EXCLUDED.template_type,
    standard_title_ar = EXCLUDED.standard_title_ar,
    standard_title_en = EXCLUDED.standard_title_en,
    standard_subject_ar = EXCLUDED.standard_subject_ar,
    standard_subject_en = EXCLUDED.standard_subject_en,
    owner_role = EXCLUDED.owner_role,
    default_sla_minutes = EXCLUDED.default_sla_minutes,
    completion_criteria = EXCLUDED.completion_criteria,
    escalation_role = EXCLUDED.escalation_role,
    escalation_sla_minutes = EXCLUDED.escalation_sla_minutes;
"""

async def run_migrations():
    for db in TARGET_DBS:
        print(f"\n🚀 Running migration on database: {db}...")
        try:
            conn = await asyncpg.connect(
                user=settings.DB_USER,
                password=settings.DB_PASSWORD,
                host=settings.DB_HOST,
                port=settings.DB_PORT,
                database=db
            )
            await conn.execute(MIGRATION_SQL)
            count = await conn.fetchval("SELECT count(*) FROM workflow_templates")
            print(f"✅ Migration successful on {db}! ({count} workflow templates registered)")
            await conn.close()
        except Exception as e:
            print(f"❌ Migration error on {db}: {e}")

if __name__ == "__main__":
    asyncio.run(run_migrations())

