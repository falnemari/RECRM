"""
Split workflow_templates.completion_criteria into:
  - completion_criteria_ar TEXT
  - completion_criteria_en TEXT
and populate high-quality bilingual acceptance criteria for all 83 templates.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))

from app.database import init_db_pool, close_db_pool

CRITERIA_DATA = {
    # Tasks (39)
    "TASK_COLLECT_SAUDI_FEES": (
        "إصدار فواتير الرسوم والضرائب النظامية (التصرفات العقارية / السعي / إيجار) منفصلة للعميل والمالك وتحصيلها 100% في الحساب البنكي.",
        "All required Saudi fee invoices (RETT / Ejar fee / Brokerage / VAT) generated separately for Customer and Owner and 100% collected in company bank account."
    ),
    "TASK_COMMISSION_SETTLEMENT": (
        "تأكيد تحصيل كامل سعي الوساطة في حساب الشركة البنكي، واعتماد واحتساب عمولة الوسيط المكلف في مسير العمولات.",
        "Brokerage fee collected in company account, and broker commission verified, approved, and cleared for payout."
    ),
    "TASK_CONTRACT_DRAFT": (
        "إعداد وتجهيز مسودة العقد وفق الشروط المعتمدة ونموذج الهيئة العامة للعقار وتحديد الدفعات والالتزامات.",
        "Prepare contract draft complying with REGA standard agreement, terms, payment schedules, and obligations."
    ),
    "TASK_CONTRACT_HANDOVER": (
        "الفحص الميداني للوحدة وتوقيع محضر الاستلام والتسليم الفني مع المشتري/المستأجر وتسليم المفاتيح والملحقات وتصفية العدادات.",
        "Sign technical handover report, verify unit inspection, and transfer keys, remotes, and utility meters to buyer/tenant."
    ),
    "TASK_CONTRACT_INTERNAL_REVIEW": (
        "المراجعة القانونية والاعتماد الداخلي لبنود العقد والتحقق من الصك والوكالات ومطابقة الأسعار والبيانات قبل إرسالها للتوقيع.",
        "Verify legal clauses, deed validity, power of attorney, and pricing before dispatching contract for signatures."
    ),
    "TASK_CONTRACT_RECONCILIATION": (
        "تدقيق سداد الدفعة الأولى وتسوية قيد العربون في الحسابات، واعتماد جدول الأقساط والمطابقة المالية الدفترية.",
        "Verify down payment and deposit, approve receivables schedule, and reconcile bank deposits in general ledger."
    ),
    "TASK_CONTRACT_SIGNATURE": (
        "متابعة توقيع واعتماد كافة الأطراف على العقد إلكترونياً عبر المنصات المعتمدة أو حضورياً وتوثيق النسخة الموقعة.",
        "Follow up with customer and parties for digital or in-person signing and record fully executed agreement."
    ),
    "TASK_INVEST_BASELINE_PERFORMANCE": (
        "توثيق وتثبيت أرقام خط الأساس المالية (سعر الاستحواذ الإجمالي، صافي الإيراد السنوي المتوقع، ومعدل الرسملة والعائد على النقد).",
        "Document and establish financial baseline (acquisition cost, forecast net rent, Cap Rate, and Cash-on-Cash return)."
    ),
    "TASK_INVEST_COMPARE_RETURNS": (
        "إعداد دراسة المقارنة المالية للعوائد للوحدات المرشحة بناءً على افتراضات موحدة للتشغيل والشغور ومعدلات العائد.",
        "Comparable properties evaluated and compared under consistent financial assumptions for NOI, Cap Rate, and Yield."
    ),
    "TASK_INVEST_CONFIRM_OBJECTIVES": (
        "عقد الجلسة الاستشارية وتحديد وتأكيد رأس المال المستهدف، العائد المطلوب، الأفق الزمني، درجة تحمل المخاطر، والإستراتيجية الاستثمارية.",
        "Confirm investor target capital, return objectives, investment horizon, risk tolerance, and investment strategy."
    ),
    "TASK_INVEST_INSPECTION_REPORT": (
        "إتمام الفحص الفني والإنشائي والمعاينة التجارية وتحديد CapEx، ومطابقة الإشغال الفعلي والرنت رول، وإصدار التوصية الاستثمارية المعتمدة.",
        "Submit due diligence report covering structural condition, MEP systems, CapEx estimates, actual occupancy audit, and final investment verdict."
    ),
    "TASK_INVEST_LEAD_FIRST_CONTACT": (
        "الاتصال بالمستثمر خلال 30 دقيقة للتعرف على رغبته الاستثمارية وتحديد موعد الجلسة الاستشارية الأولى.",
        "Contact investor within 30 minutes to confirm investment interest and schedule initial advisory consultation."
    ),
    "TASK_INVEST_MONITOR_ACTUAL_RETURNS": (
        "تدقيق ومقارنة التدفقات النقدية والإيجارات الفعلية المحصلة ومصاريف التشغيل ومقارنتها بخط الأساس المرصود ورصد الانحرافات.",
        "Reconcile actual rental collections and operating expenses against baseline performance and document variances."
    ),
    "TASK_INVEST_PORTFOLIO_REVIEW": (
        "إنجاز المراجعة الدورية لأداء المحفظة الاستثمارية وتقديم تقرير التوصيات الإستراتيجية (استمرار الاحتفاظ / التطوير / التخارج).",
        "Complete periodic portfolio performance review with variance analysis and strategic hold/upgrade/exit recommendations."
    ),
    "TASK_INVEST_PREPARE_ACQUISITION_OFFER": (
        "إعداد وتقديم عرض الاستحواذ المالي والخطاب الاستثماري متضمناً السعر المقترح وشروط الفحص والدفع للبائع.",
        "Prepare and submit formal acquisition proposal and LOI with adjusted pricing, inspection terms, and payment milestones."
    ),
    "TASK_INVEST_SCHEDULE_INSPECTION": (
        "جدولة وتنسيق موعد الفحص الميداني النافي للجهالة مع المستثمر والمستشار الهندسي وإدارة المبنى وإرسال الموقع.",
        "Schedule due diligence inspection timing with investor, engineering team, and property management, and dispatch location."
    ),
    "TASK_INVEST_VALIDATE_FINANCIALS": (
        "تدقيق الافتراضات المالية للإيرادات ومعدلات الشغور والمصاريف التشغيلية ومواءمتها مع تكاليف الصيانة الرأسمالية واختبار الحساسية.",
        "Validate financial assumptions, rent forecasts, vacancy allowances, operating costs, and sensitivity analysis."
    ),
    "TASK_LEAD_ASSIGN": (
        "مراجعة متطلبات الطلب واختيار وتعيين وسيط مبيعات مؤهل ومتخصص في المنطقة الجغرافية ونوع العقار.",
        "Review lead requirements and assign a dedicated qualified sales agent based on territory and property specialization."
    ),
    "TASK_LEAD_COMPLETE_INFO": (
        "التواصل مع العميل واستكمال البيانات الناقصة في الطلب (الميزانية، المدينة، الأحياء، أو تفاصيل الاتصال).",
        "Contact customer to collect and complete missing inquiry details, budget range, preferred neighborhoods, or contact info."
    ),
    "TASK_LEAD_FIRST_CONTACT": (
        "الاتصال بالعميل خلال 15 دقيقة والتحقق من رقم الهاتف وتسجيل نتيجة المكالمة وتحديد الخطوة التالية.",
        "Contact lead within 15 minutes, verify phone number, log call outcome, and determine next step."
    ),
    "TASK_LEAD_FOLLOWUP": (
        "إجراء اتصال متابعة مع العميل وتحديث رغبته واحتياجاته العقارية وتحديد موعد للتواصل القادم.",
        "Conduct follow-up call with client, update requirements and buying interest, and set next follow-up date."
    ),
    "TASK_LEAD_QUALIFY": (
        "استيفاء معايير التأهيل الإلزامية (الميزانية، القدرة التمويلية، نوع العقار، والجاهزية للشراء) وترقية الطلب لفرصة بيعية.",
        "Complete mandatory qualification criteria (budget, financing readiness, property type, and intent) and promote lead to opportunity."
    ),
    "TASK_OFFER_FOLLOWUP": (
        "متابعة العميل لمعرفة قراره النهائي بشأن العرض التجاري المقدم والتفاوض قبل انتهاء فترة صلاحيته.",
        "Follow up with client regarding formal offer decision and conduct negotiations before offer expiration."
    ),
    "TASK_OFFER_MANAGER_APPROVAL": (
        "مراجعة واعتماد أو رفض العرض المالي الذي يتجاوز نسبة الخصم المصرح بها لوسيط المبيعات (أكثر من 5%).",
        "Review and approve or reject commercial offer with discount exceeding standard sales agent authority (> 5%)."
    ),
    "TASK_OFFER_PREPARE": (
        "إعداد وتجهيز العرض التجاري وتحديد القيمة المالية المقترحة وجدول الدفعات والشروط وإرسالها للاعتماد.",
        "Prepare formal commercial offer with pricing, payment terms, and special conditions, and dispatch for approval."
    ),
    "TASK_OFFER_SUBMIT": (
        "تقديم العرض المالي المعتمد للعميل رسمياً واستلام موافقته المبدئية أو ملاحظاته.",
        "Formally deliver approved commercial offer to customer and capture initial acceptance or counter-feedback."
    ),
    "TASK_OPPORTUNITY_MATCH_PROPERTIES": (
        "البحث في مخزون العقارات المتاحة وترشيح وحدتين إلى 3 وحدات مطابقة لميزانية ورغبات العميل وربطها بالفرصة.",
        "Search active inventory, match 2-3 properties meeting client budget and preferences, and link them to opportunity."
    ),
    "TASK_RENT_COLLECTION_MONITORING": (
        "رصد ومتابعة استحقاق دفعات الإيجار الدورية، وتدقيق توريد الأقساط في الحساب البنكي وتسويتها وإصدار الإيصالات.",
        "Monitor rental installments, verify bank deposits, reconcile receivables in GL, and clear broker commissions."
    ),
    "TASK_RENT_LEAD_FIRST_CONTACT": (
        "الاتصال بالعميل واستيفاء معايير ومتطلبات الإيجار (الميزانية، المدينة، عدد الغرف، تاريخ الانتقال، وطريقة الدفع).",
        "Contact rental lead and record tenancy preferences (budget, city, bedrooms, move-in date, payment terms)."
    ),
    "TASK_RENT_MATCH_PROPERTIES": (
        "البحث في مخزون الوحدات الشاغرة للإيجار فقط وترشيح الوحدات المطابقة للمستأجر واقتراحها عليه.",
        "Match vacant rental properties against tenant requirements and present recommendations."
    ),
    "TASK_RENT_PREPARE_TENANCY": (
        "صياغة وإبرام عقد الإيجار الرسمي عبر شبكة (إيجار) المعتمدة، وتدقيق سداد الدفعة الأولى والتأمين وتفعيل العقد.",
        "Create and execute official tenancy agreement on Ejar network, verify deposit and security payment, and activate lease."
    ),
    "TASK_RENT_VIEWING_FOLLOW_UP": (
        "متابعة المستأجر بعد المعاينة الميدانية وتوثيق قراره بالاستئجار أو ترشيح وحدات بديلة.",
        "Follow up with tenant after site visit, capture lease decision, or recommend alternative rental units."
    ),
    "TASK_RESERVATION_DEPOSIT_FOLLOWUP": (
        "التحقق من إيداع مبلغ العربون في الحساب البنكي للشركة وإصدار سند القبض المحاسبي وتثبيت الحجز.",
        "Verify deposit received in company bank account, issue accounting receipt voucher, and lock reservation."
    ),
    "TASK_RESERVATION_DOCUMENTS": (
        "استكمال وتدقيق وثائق الهوية الوطنية أو السجل التجاري وسند الحجز وتعبئة بيانات العميل (KYC).",
        "Collect and verify national ID, commercial registration, reservation form, and required compliance KYC documents."
    ),
    "TASK_RESERVATION_EXPIRY_REVIEW": (
        "مراجعة الحجز قبل انتهاء مهلته النظامية واعتماد التمديد المؤقت أو إلغاء الحجز وتحرير الوحدة للمخزون.",
        "Review expiring reservation to approve authorized extension or cancel lock and release unit back to available inventory."
    ),
    "TASK_RESERVATION_VERIFY_AVAILABILITY": (
        "التحقق التبادلي الصارم من توفر الوحدة وخلوها من أي حجز أو نزاع، وتثبيت قفل الحجز المؤقت في النظام.",
        "Rigorous transactional check confirming unit is vacant and unreserved, and apply temporary reservation lock."
    ),
    "TASK_VIEWING_REPORT": (
        "توثيق تقرير المعاينة الميدانية ورصد انطباع العميل وقراره (مهتم بالشراء / طلب بديل / غير مهتم) وتحديد التوجيه.",
        "Document site visit inspection report, capture client decision (interested / needs alternative / not interested), and set next step."
    ),
    "TASK_VIEWING_RESCHEDULE": (
        "التواصل مع العميل والمالك بعد تعذر الزيارة وتحديد موعد وموقع بديل للمعاينة الميدانية.",
        "Contact client and owner to agree on alternative date and time following cancellation or no-show."
    ),
    "TASK_VIEWING_SCHEDULE": (
        "التنسيق مع العميل وإدارة العقار وتحديد تاريخ ووقت وموقع المعاينة الميدانية وإرسال تأكيد الموعد.",
        "Coordinate with client and property management, schedule site visit date and time, and dispatch location confirmation."
    ),

    # Activities (34)
    "ACT_CONTRACT_CLOSED": (
        "إغلاق الصفقة بنجاح، تحويل وضع الوحدة إلى مباعة، وإدراج عمولة الوسيط في مسير المستحقات.",
        "Close deal as won, update unit to SOLD, and register broker commission pending payout."
    ),
    "ACT_CONTRACT_DRAFT_CREATED": (
        "توثيق صياغة مسودة العقد وإصدار النسخة المعتمدة الأولى للتدقيق.",
        "Document drafting and initial issuance of standard contract agreement."
    ),
    "ACT_CONTRACT_SIGNED": (
        "توثيق اكتمال تواقيع كافة الأطراف على العقد رسمياً وتحديث حالة العقد إلى نافذ.",
        "Document complete execution of contract signatures and update contract to executed."
    ),
    "ACT_FEE_COLLECTED": (
        "توثيق تحصيل وتوريد مبالغ الرسوم أو الضرائب النظامية في الحساب البنكي وإقفال المطالبة.",
        "Fee collected, verified in bank account, and reconciled in ledger."
    ),
    "ACT_INVEST_ACQUISITION_OFFER_PREPARED": (
        "تم تقديم عرض الاستحواذ الاستثماري المعتمد وخطاب النوايا رسمياً للعميل/البائع.",
        "Acquisition offer and LOI formally prepared and submitted to investor/seller."
    ),
    "ACT_INVEST_BASELINE_ESTABLISHED": (
        "تم توثيق واعتماد خط الأساس لمؤشرات الأداء المستهدفة والعائد الصافي ومعدل الرسملة.",
        "Baseline purchase price, forecast net rent, Cap Rate, and expected returns established."
    ),
    "ACT_INVEST_FINANCIALS_VALIDATED": (
        "تم التحقق من الفرضيات المالية ومعدلات الإشغال ومصاريف التشغيل وتدقيق موازنة الأصل.",
        "Rent forecasts, vacancy, operating costs, and financing vetted and validated."
    ),
    "ACT_INVEST_INSPECTION_COMPLETED": (
        "توثيق اكتمال تقرير الفحص الفني والإنشائي والمعاينة التجارية وتحديد الـ CapEx وإصدار التوصية.",
        "Document due diligence inspection completion, CapEx assessment, and investment recommendation."
    ),
    "ACT_INVEST_INSPECTION_SCHEDULED": (
        "تم تأكيد موعد وموقع الفحص الفني والاستثماري الميداني وتنسيق فريق الفحص.",
        "Technical due diligence inspection schedule confirmed and site access coordinated."
    ),
    "ACT_INVEST_LEAD_QUALIFIED": (
        "تم اكتمال تأهيل المستثمر وتوثيق الملاءة المالية ومعايير المحفظة المستهدفة وترقية الطلب.",
        "Investor qualified with confirmed capital, target returns, and investment profile."
    ),
    "ACT_INVEST_OBJECTIVES_CONFIRMED": (
        "تم اعتماد وتأكيد الأهداف الاستثمارية ومزامنة رأس المال والميزانية المستهدفة في الفرصة.",
        "Investor target capital, horizon, yield, and risk tolerance formally documented."
    ),
    "ACT_INVEST_PORTFOLIO_REVIEWED": (
        "تم إنجاز مراجعة أداء المحفظة الاستثمارية ورفع تقرير التوصيات الإستراتيجية.",
        "Periodic review completed with variance analysis and future hold/sell recommendations."
    ),
    "ACT_INVEST_RETURNS_COMPARED": (
        "تم إعداد وتوثيق دراسة مقارنة العوائد الاستثمارية للوحدات المرشحة واختيار الخيار الأفضل.",
        "Comparable properties evaluated and documented under identical financial assumptions."
    ),
    "ACT_INVEST_RETURNS_MONITORED": (
        "تم تدقيق ومقارنة العوائد الإيجارية الفعلية ومقارنتها بخط الأساس ورصد نسبة الانحراف.",
        "Actual rental income and expenses reconciled against baseline performance."
    ),
    "ACT_INVOICE_GENERATED": (
        "إصدار فاتورة ضريبية رسمية بالرسوم أو السعي وإرسالها للمطالب بالسداد.",
        "Official tax invoice generated and dispatched to payer."
    ),
    "ACT_LEAD_ASSIGNED": (
        "توثيق تعيين أو إعادة توجيه الطلب لوسيط مبيعات معتمد لمباشرة الإجراءات.",
        "Log assignment or reassignment of lead to designated sales agent."
    ),
    "ACT_LEAD_CREATED": (
        "تسجيل استلام الطلب وتوجيهه وتعيين المستشار المسؤول في النظام.",
        "Log intake, deduplication, and initial advisor assignment."
    ),
    "ACT_LEAD_FIRST_CONTACT": (
        "تسجيل الاتصال الأولي بالعميل وتوثيق نتيجة المكالمة ومستوى الاهتمام.",
        "Log initial phone call or WhatsApp contact with outcome and interest level."
    ),
    "ACT_LEAD_FOLLOWUP": (
        "توثيق تفاصيل مكالمة أو مراسلة المتابعة وتحديث رغبة العميل وملاحظاته.",
        "Log follow-up conversation details and update client requirements."
    ),
    "ACT_LEAD_QUALIFIED": (
        "اكتمال معايير التأهيل وترقية الطلب رسمياً إلى فرصة عقارية نشطة.",
        "Qualification requirements fulfilled and lead promoted to active opportunity."
    ),
    "ACT_LEAD_ROUTED": (
        "توجيه الطلب لمدير الفرع المعني لفرز الطلب وتعيين الوسيط المختص.",
        "Route lead to branch manager for review and agent assignment."
    ),
    "ACT_OFFER_CREATED": (
        "توثيق إنشاء مسودة العرض المالي وحفظ البنود والتسعير المبدئي.",
        "Log drafting of commercial offer and initial terms."
    ),
    "ACT_OFFER_DECISION": (
        "توثيق قرار العرض المالي (قبول، رفض، أو تقديم عرض مقابل) وأسباب القرار.",
        "Log formal offer decision (accepted, rejected, or countered) with rationales."
    ),
    "ACT_OFFER_SUBMITTED": (
        "توثيق تقديم العرض المالي المعتمد رسمياً للعميل وتاريخ الإرسال.",
        "Log submission of approved formal offer to client."
    ),
    "ACT_OPPORTUNITY_PROPERTIES_PRESENTED": (
        "توثيق عرض الوحدات العقارية المطابقة على العميل وإرسال تفاصيلها.",
        "Log presentation of matched property recommendations to client."
    ),
    "ACT_RENT_LEAD_QUALIFIED": (
        "اكتمال تأهيل طلب الإيجار وتحديد الميزانية والشروط وترقية الطلب لفرصة تأجير.",
        "Rental lead qualified with confirmed budget, move-in date, and promoted to leasing opportunity."
    ),
    "ACT_RENT_PAYMENT_COLLECTED": (
        "تسجيل استلام وتسوية دفعة الإيجار في الحساب البنكي وإصدار سند الاستلام.",
        "Rental payment received, reconciled in bank account, and receipt issued."
    ),
    "ACT_RENT_PROPERTIES_MATCHED": (
        "ترشيح واقتراح الوحدات الشاغرة المطابقة لميزانية ومواصفات المستأجر.",
        "Vacant units matched and presented to rental prospect."
    ),
    "ACT_RESERVATION_AVAILABILITY_VERIFIED": (
        "توثيق نجاح فحص جاهزية وتوفر الوحدة العقارية وخلوها من التعارضات.",
        "Document successful verification of unit availability and clearance."
    ),
    "ACT_RESERVATION_CONFIRMED": (
        "اعتماد الحجز وقفل الوحدة وتحديث حالتها في سجل المخزون إلى محجوزة.",
        "Document reservation confirmation and update unit status to RESERVED in inventory."
    ),
    "ACT_TASK_REOPENED": (
        "توثيق التراجع الذكي عن إنجاز المهمة وإعادة فتحها وإلغاء الآثار المترتبة.",
        "Log task completion reversal and smart undo workflow."
    ),
    "ACT_TENANCY_ACTIVATED": (
        "توثيق تفعيل عقد الإيجار وتسليم الوحدة وقفلها كمؤجرة في النظام.",
        "Tenancy agreement activated, unit handed over, and marked RENTED."
    ),
    "ACT_VIEWING_REPORT_SUBMITTED": (
        "توثيق تقرير المعاينة الميدانية وانطباع العميل وتحديد الإجراء التالي.",
        "Document client feedback and inspection report after site visit."
    ),
    "ACT_VIEWING_SCHEDULED": (
        "تسجيل وتأكيد موعد الزيارة الميدانية وتوثيق بيانات العقار المحدد.",
        "Log confirmed site visit appointment details and designated property."
    ),

    # Communications (10)
    "COMM_CONTRACT_REVIEW_REQUIRED": (
        "إرسال إشعار داخلي للمراجع القانوني والمدير لتدقيق مسودة العقد قبل التوقيع.",
        "Send internal notification to legal reviewer and manager to audit contract draft."
    ),
    "COMM_CONTRACT_SIGNATURE_INSTRUCTIONS": (
        "إرسال رابط منصة التوقيع الرقمي (إيجار / المنصة المعتمدة) وإرشادات التوقيع للعميل.",
        "Send digital signing link and step-by-step instructions to customer."
    ),
    "COMM_INVEST_INSPECTION_CONFIRMATION": (
        "إرسال إشعار تأكيد موعد وموقع الفحص الفني والاستثماري للمستثمر والمالك.",
        "Send inspection schedule and location confirmation to investor and property owner."
    ),
    "COMM_LEAD_INITIAL_CONTACT": (
        "إرسال إشعار استلام الطلب العقاري ورسالة الترحيب الآلية متضمنة رقم الطلب.",
        "Send automated intake notification and welcome message with lead reference."
    ),
    "COMM_OFFER_DECISION_COMMUNICATED": (
        "إرسال إشعار للعميل بقرار العرض المالي وتفاصيل الخطوة القادمة.",
        "Send customer notification regarding commercial offer decision and next steps."
    ),
    "COMM_OFFER_PROPOSAL_SENT": (
        "إرسال مسودة العرض المالي وجدول الدفعات المقترح للعميل عبر القناة المعتمدة.",
        "Send commercial proposal and payment schedule to customer via primary channel."
    ),
    "COMM_OPPORTUNITY_RECOMMENDATIONS": (
        "إرسال كتيب وتفاصيل الوحدات العقارية المطابقة المقترحة للعميل للمعاينة.",
        "Send matched property portfolio and recommendation brochure to client."
    ),
    "COMM_RESERVATION_CONFIRMATION": (
        "إرسال إشعار تأكيد حجز الوحدة العقارية وسند العربون المحاسبي للعميل.",
        "Send reservation confirmation notice and receipt voucher to customer."
    ),
    "COMM_VIEWING_CONFIRMATION": (
        "إرسال رسالة تأكيد موعد المعاينة الميدانية وموقع العقار ورقم تواصل الوسيط للعميل.",
        "Send site viewing confirmation with exact property location and agent contact."
    ),
    "COMM_VIEWING_REMINDER": (
        "إرسال رسالة تذكير آلية للعميل بموعد الزيارة الميدانية قبل الموعد بساعتين.",
        "Send automated appointment reminder to client 2 hours before scheduled viewing."
    ),
}

async def main():
    pool = await init_db_pool()
    async with pool.acquire() as conn:
        print("=== 1. Adding columns completion_criteria_ar and completion_criteria_en ===")
        await conn.execute("""
            ALTER TABLE workflow_templates ADD COLUMN IF NOT EXISTS completion_criteria_ar TEXT;
            ALTER TABLE workflow_templates ADD COLUMN IF NOT EXISTS completion_criteria_en TEXT;
        """)
        print("Columns added successfully.")

        print(f"\n=== 2. Populating bilingual completion criteria for {len(CRITERIA_DATA)} templates ===")
        for tid, (ar_crit, en_crit) in CRITERIA_DATA.items():
            await conn.execute("""
                UPDATE workflow_templates
                SET completion_criteria_ar = $1,
                    completion_criteria_en = $2
                WHERE template_id = $3
            """, ar_crit, en_crit, tid)
        print("Populated all templates.")

        # Drop old column completion_criteria
        print("\n=== 3. Dropping legacy completion_criteria column ===")
        await conn.execute("ALTER TABLE workflow_templates DROP COLUMN IF EXISTS completion_criteria;")
        print("Dropped legacy completion_criteria column.")

        # Verification
        print("\n=== 4. Verification: Sample criteria from workflow_templates ===")
        samples = await conn.fetch("""
            SELECT template_id, template_type, completion_criteria_ar, completion_criteria_en
            FROM workflow_templates
            WHERE template_id IN ('TASK_INVEST_CONFIRM_OBJECTIVES', 'TASK_RENT_MATCH_PROPERTIES', 'TASK_COLLECT_SAUDI_FEES', 'ACT_CONTRACT_CLOSED')
        """)
        for s in samples:
            print(f"[{s['template_type']}] {s['template_id']}:")
            print(f"  AR: {s['completion_criteria_ar']}")
            print(f"  EN: {s['completion_criteria_en']}")

        null_ar = await conn.fetchval("SELECT count(*) FROM workflow_templates WHERE completion_criteria_ar IS NULL OR completion_criteria_ar = ''")
        null_en = await conn.fetchval("SELECT count(*) FROM workflow_templates WHERE completion_criteria_en IS NULL OR completion_criteria_en = ''")
        print(f"\nEmpty check: Empty AR = {null_ar}, Empty EN = {null_en}")
        assert null_ar == 0 and null_en == 0, "There are empty criteria fields!"
        print("ALL 83 TEMPLATES HAVE COMPLETE BILINGUAL COMPLETION CRITERIA!")

    await close_db_pool()

if __name__ == '__main__':
    asyncio.run(main())
