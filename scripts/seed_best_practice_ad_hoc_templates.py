import asyncio
import asyncpg
import json
from datetime import datetime, timezone

# 13 Best-Practice Ad-Hoc / On-Demand Task Templates
BEST_PRACTICE_TEMPLATES = [
    # 1. Investment & Acquisition
    {
        "template_id": "TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT",
        "template_type": "TASK",
        "title_ar": "الاستثمار — التفاوض على التعديل السعري وعيوب الفحص (CapEx)",
        "title_en": "Investment — Price Discount & CapEx Defect Negotiation",
        "owner_role": "INVESTMENT_ADVISOR",
        "sla_minutes": 1440,
        "criteria_ar": "توثيق مخاطبة البائع بمبلغ الخصم المطلوب وتفاصيل الـ CapEx وتقرير الفحص، وتسجيل رده الرسمي وتحديث السعر المستهدف.",
        "criteria_en": "Document formal discount notice to seller with CapEx report, record seller response, and update target purchase price.",
        "category": "INVESTMENT",
        "sop": {
            "stage_code": "STAGE_INVEST_NEGOTIATION",
            "stage_name_ar": "الاستثمار — التفاوض على التعديل السعري وعيوب الفحص",
            "stage_name_en": "Investment — Price Discount & CapEx Negotiation",
            "required_now_ar": "مخاطبة البائع أو وكيله بتقرير العيوب الفنية (CapEx) وطلب تخفيض السعر لحماية عائد المستثمر.",
            "required_now_en": "Present CapEx inspection report to seller and negotiate purchase price adjustment to protect investor return.",
            "current_responsible_ar": "مستشار الاستثمار العقاري",
            "current_responsible_en": "Investment Advisor",
            "next_action_ar": "تسجيل نتيجة التفاوض (قبول كامل / تسوية وسطية / تمسك بالسعر) والانتقال لصياغة عرض الاستحواذ النهائي.",
            "next_action_en": "Record negotiation outcome (accepted / compromise / rejected) and proceed to final acquisition offer.",
            "step_goal_ar": "حماية العائد التشغيلي للمستثمر بترحيل تكلفة الإصلاحات الرأسمالية إلى البائع كخصم سعري.",
            "step_goal_en": "Protect net operating yield by passing mandatory capital repairs to seller via price discount.",
            "mandatory_conditions_ar": "إرفاق بنود تقرير الفحص النافي للجهالة، إبراز مؤشر هامش الأمان للمستثمر، وتوثيق رد البائع كتابياً.",
            "mandatory_conditions_en": "Attach due diligence findings, highlight capital buffer metric, and document seller response in writing.",
            "consequence_ar": "تجاهل التفاوض على CapEx يُلزم المستثمر بدفع مصاريف صيانة إضافية تخفض عائده الفعلي عن المستهدف.",
            "consequence_en": "Ignoring CapEx negotiation burdens the buyer with unforeseen remediation costs eroding target yield.",
            "steps_ar": [
                {"step_no": 1, "title": "مراجعة تقرير CapEx والخصم المقترح", "description": "استخراج تفاصيل الإصلاحات الإلزامية وقيمة التعديل السعري المعتمد في تقرير الفحص."},
                {"step_no": 2, "title": "إعداد مذكرة التفاوض الفني", "description": "صياغة خطاب رسمي مدعوم بالصور ومقايسات الإصلاح لتقديمه للبائع أو ممثله."},
                {"step_no": 3, "title": "عقد جلسة التفاوض ومراجعة رد البائع", "description": "مناقشة البائع والوصول إلى قرار نهائي: قبول الخصم، تسوية، أو رفض."},
                {"step_no": 4, "title": "توثيق النتيجة وتحديث النموذج المالي", "description": "إدخال السعر النهائي المتفق عليه وتحديث حسابات العائد وصافي الاستثمار."}
            ],
            "steps_en": [
                {"step_no": 1, "title": "Review CapEx & Discount Basis", "description": "Extract mandatory remediation line items and proposed price discount from DD report."},
                {"step_no": 2, "title": "Draft Technical Negotiation Memo", "description": "Prepare formal negotiation memo supported by photos and estimates for the seller."},
                {"step_no": 3, "title": "Conduct Negotiation & Receive Response", "description": "Engage seller to secure full discount, partial compromise, or record rejection."},
                {"step_no": 4, "title": "Commit Outcome & Update Financials", "description": "Record agreed price and recompute net yield and investor capital buffer."}
            ],
            "sample_notes_ar": "تمت مخاطبة البائع بملاحظات الفحص وطلب خصم CapEx بقيمة 228,000 ريال. وافق البائع على تسوية بخصم 180,000 ريال من سعر الشراء ليصبح السعر المعتمد 11,820,000 ريال.",
            "sample_notes_en": "Seller negotiated on CapEx defects (228k SAR). Agreed on 180k SAR discount, setting adjusted purchase price to 11.82M SAR."
        }
    },
    {
        "template_id": "TASK_INVEST_LEGAL_TITLE_AUDIT",
        "template_type": "TASK",
        "title_ar": "الاستثمار — التدقيق القانوني والتأكد من سلامة الصك والملكية",
        "title_en": "Investment — Title Deed Legal Due Diligence & Audit",
        "owner_role": "LEGAL",
        "sla_minutes": 2880,
        "criteria_ar": "التحقق من سريان الصك الإلكتروني عبر البورصة العقارية/ناجز، خلو العقار من النزاعات، صحة حدود العقار والوقف والوصية.",
        "criteria_en": "Verify active electronic title deed via Real Estate Exchange/Najiz, ensure freedom from disputes, verify boundaries and endowments.",
        "category": "INVESTMENT",
        "sop": {
            "stage_code": "STAGE_INVEST_LEGAL_AUDIT",
            "stage_name_ar": "الاستثمار — التدقيق القانوني للصك والملكية",
            "stage_name_en": "Investment — Title Deed Legal Audit",
            "required_now_ar": "مطابقة بيانات الصك الإلكتروني مع السجل العقاري والتحقق من صلاحية المالك أو الوكالات الشرعية.",
            "required_now_en": "Audit electronic title deed with Real Estate Registry, verify owner identity and active power of attorney.",
            "current_responsible_ar": "المستشار القانوني",
            "current_responsible_en": "Legal Counsel",
            "next_action_ar": "إصدار مذكرة الرأي القانوني بالموافقة على سلامة الملكية أو رصد أي قيود قانونية.",
            "next_action_en": "Issue legal opinion memorandum certifying clean title or detailing encumbrances.",
            "step_goal_ar": "ضمان خلو الأصل العقاري من أية شوائب قانونية أو نزاعات أو موانع تصرف قبل الالتزام المالي.",
            "step_goal_en": "Ensure asset is free of legal disputes, encumbrances, or disposition restrictions prior to commitment.",
            "mandatory_conditions_ar": "الاستعلام اللحظي عبر منصة البورصة العقارية، فحص القيود والرهون، ومطابقة مساحة الصك مع المخطط.",
            "mandatory_conditions_en": "Real-time query via Real Estate Exchange, verify liens/mortgages, and reconcile deed area with subdivision plan.",
            "consequence_ar": "إهمال التدقيق القانوني قد يؤدي إلى بطلان الإفراغ أو تعليق ملكية المشتري في نزاعات قضائية.",
            "consequence_en": "Overlooking legal title audit risks conveyance invalidation or entangling buyer in title litigation.",
            "steps_ar": [
                {"step_no": 1, "title": "التحقق من الصك الإلكتروني", "description": "الاستعلام عن حالة الصك وتاريخه ورقم الهوية المرتبطة به عبر البورصة العقارية."},
                {"step_no": 2, "title": "فحص القيود والرهونات", "description": "التأكد من عدم وجود رهن بنكي غير مفكوك أو حجز تنفيذي أو وقف أو وصية معطلة."},
                {"step_no": 3, "title": "مطابقة الحدود والمساحة", "description": "مطابقة مساحة وأطوال الصك مع المخطط التنظيمي المعتمد من الأمانة."},
                {"step_no": 4, "title": "إصدار خلاصة الرأي القانوني", "description": "توثيق التقرير النهائي واعتماد سلامة الملكية للمضي في الإفراغ."}
            ],
            "steps_en": [
                {"step_no": 1, "title": "Electronic Title Query", "description": "Query deed status, date, and national ID mapping via Real Estate Exchange."},
                {"step_no": 2, "title": "Encumbrance & Mortgage Check", "description": "Verify absence of unreleased mortgages, judicial seizures, or restrictive endowments."},
                {"step_no": 3, "title": "Boundary & Area Reconciliation", "description": "Reconcile deed area and dimensions with approved municipal masterplan."},
                {"step_no": 4, "title": "Issue Legal Opinion Summary", "description": "Document final legal opinion certifying clean title for conveyance."}
            ],
            "sample_notes_ar": "تم التحقق من الصك الإلكتروني رقم 310105009877: الصك سليم ونشط، خالي من الرهونات والقيود، والوكالة الشرعية للبائع سارية ومحدثة.",
            "sample_notes_en": "Electronic title deed verified: Active, clean title without liens, power of attorney valid and verified on Najiz."
        }
    },
    {
        "template_id": "TASK_INVEST_TAX_ZAKAT_ADVISORY",
        "template_type": "TASK",
        "title_ar": "الاستثمار — الاستشارة الضريبية وضريبة التصرفات العقارية (RETT)",
        "title_en": "Investment — Real Estate Transaction Tax (RETT) & Zakat Advisory",
        "owner_role": "ACCOUNTANT",
        "sla_minutes": 1440,
        "criteria_ar": "تحديد الوعاء الضريبي (5% تصرفات عقارية)، التحقق من شروط الإعفاء أو الاسترداد، وحساب الأثر المالي على صافي العائد.",
        "criteria_en": "Assess RETT taxable base (5%), check exemption/refund criteria, and compute financial impact on net investment yield.",
        "category": "INVESTMENT",
        "sop": {
            "stage_code": "STAGE_INVEST_TAX_ADVISORY",
            "stage_name_ar": "الاستثمار — الاستشارة الضريبية وضريبة التصرفات العقارية",
            "stage_name_en": "Investment — RETT & Tax Advisory",
            "required_now_ar": "احتساب ضريبة التصرفات العقارية المستحقة (5%) وتحديد الطرف الملزم نظاماً بالسداد وتوافر أي إعفاءات.",
            "required_now_en": "Calculate statutory RETT (5%), identify statutory paying party, and review applicable exemptions.",
            "current_responsible_ar": "المحاسب المالي",
            "current_responsible_en": "Financial Accountant",
            "next_action_ar": "إدراج المخصص الضريبي ضمن التكلفة الكلية للاستثمار والتأكد من سدادها قبل الإفراغ.",
            "next_action_en": "Include tax allocation in total investment basis and ensure settlement prior to title transfer.",
            "step_goal_ar": "تجنب الغرامات المالية وضمان دقة حساب قاعدة التكلفة الاستثمارية (Total Investment Basis).",
            "step_goal_en": "Avoid tax penalties and ensure exact calculation of total investment acquisition basis.",
            "mandatory_conditions_ar": "التحقق من رقم التسجيل الضريبي أو هوية البائع لدى هيئة الزكاة والضريبة والجمارك وتوليد فاتورة سداد RETT.",
            "mandatory_conditions_en": "Verify ZATCA tax status, check seller ID, and generate statutory RETT SADAD invoice.",
            "consequence_ar": "عدم سداد ضريبة التصرفات العقارية يمنع كاتب العدل من إتمام الإفراغ ويترتب عليه غرامات تأخير 2% شهرياً.",
            "consequence_en": "Failure to pay RETT blocks notarial conveyance and accrues 2% monthly statutory delay penalties.",
            "steps_ar": [
                {"step_no": 1, "title": "تحديد قيمة الصفقة الخاضعة للضريبة", "description": "تحديد المبلغ المتفق عليه بين الطرفين كوعاء لضريبة التصرفات العقارية 5%."},
                {"step_no": 2, "title": "مراجعة حالات الاستثناء والإعفاء", "description": "فحص توافر أي إعفاء نظامي (مثل نقل الملكية بين الأقارب أو الشركات التابعة)."},
                {"step_no": 3, "title": "إصدار رقم سداد ضريبة التصرفات", "description": "التسجيل في بوابة ZATCA وإصدار فاتورة سداد للضريبة تمهيداً للإفراغ."},
                {"step_no": 4, "title": "إدراج الضريبة في الحسبة الاستثمارية", "description": "إضافة مبلغ الضريبة إلى إجمالي رأس المال المستثمر وإعادة احتساب العائد الصافي."}
            ],
            "steps_en": [
                {"step_no": 1, "title": "Establish Taxable Base", "description": "Determine final agreed acquisition price subject to 5% RETT statutory tax."},
                {"step_no": 2, "title": "Audit Exemptions", "description": "Examine statutory exemption criteria (corporate restructuring, family transfers)."},
                {"step_no": 3, "title": "Generate RETT SADAD Invoice", "description": "File transaction on ZATCA portal and issue SADAD payment invoice for conveyance."},
                {"step_no": 4, "title": "Incorporate Tax in Return Model", "description": "Add RETT amount to total acquisition basis and reconcile net yield."}
            ],
            "sample_notes_ar": "تم احتساب ضريبة التصرفات العقارية بنسبة 5% بمبلغ 600,000 ريال على قيمة الاستحواذ 12,000,000 ريال، وتم إصدار رقم سداد ZATCA رقم 9821447.",
            "sample_notes_en": "RETT calculated at 5% (600,000 SAR) on 12M SAR acquisition. ZATCA payment invoice issued."
        }
    },
    {
        "template_id": "TASK_INVEST_TAQEEM_VALUATION",
        "template_type": "TASK",
        "title_ar": "الاستثمار — طلب تقرير تقييم عقاري معتمد (مقيم Taqeem)",
        "title_en": "Investment — Certified Valuation Report (Taqeem Standard)",
        "owner_role": "INVESTMENT_ADVISOR",
        "sla_minutes": 4320,
        "criteria_ar": "تكليف مقيّم معتمد من هيئة 'مقيّمين'، استلام التقرير، ومقارنة القيمة السوقية المعتمدة بسعر الاستحواذ.",
        "criteria_en": "Commission certified Taqeem appraiser, receive valuation report, and benchmark certified market value against acquisition price.",
        "category": "INVESTMENT",
        "sop": {
            "stage_code": "STAGE_INVEST_TAQEEM_VALUATION",
            "stage_name_ar": "الاستثمار — التقييم العقاري المعتمد",
            "stage_name_en": "Investment — Certified Taqeem Valuation",
            "required_now_ar": "طلب تقرير تقييم رسمي صادر من منشأة تقييم مرخصة من الهيئة السعودية للمقيّمين المعتمدين.",
            "required_now_en": "Commission official valuation report from Taqeem accredited firm using standard valuation methods.",
            "current_responsible_ar": "مستشار الاستثمار العقاري",
            "current_responsible_en": "Investment Advisor",
            "next_action_ar": "مقارنة القيمة المقدرة مع سعر العرض للتأكد من عدم وجود مبالغة سعرية.",
            "next_action_en": "Benchmark appraised value against offer price to ensure fair market acquisition.",
            "step_goal_ar": "توفير مرجعية تسعير محايدة ومعتمدة تدعم قرار الاستثمار والجهات التمويلية.",
            "step_goal_en": "Provide independent certified appraisal benchmark supporting investor decision and financiers.",
            "mandatory_conditions_ar": "سريان ترخيص المقيّم، اعتماد أسلوب الدخل (Income Approach) وأسلوب المقارنة بالسوق (Sales Comparison).",
            "mandatory_conditions_en": "Valid Taqeem license, applying Income Capitalization and Sales Comparison valuation methods.",
            "consequence_ar": "الشراء دون تقييم معتمد قد يؤدي إلى دفع علاوة سعرية غير مبررة ورفض البنوك للتمويل.",
            "consequence_en": "Purchasing without certified valuation risks overpaying and rejection by mortgage providers.",
            "steps_ar": [
                {"step_no": 1, "title": "اختيار منشأة تقييم معتمدة", "description": "تكليف مقيّم عقاري معتمد مسجل في نظام 'قيم' التابع لهيئة مقيّمين."},
                {"step_no": 2, "title": "تزويد المقيّم ببيانات العقار", "description": "تسليم الصك والمخططات وبيانات الإشغال وعقود الإيجار لتقييم التدفقات النقدية."},
                {"step_no": 3, "title": "استلام ومراجعة مسودة التقرير", "description": "مراجعة افتراضات معدل الرسملة، ونفقات التشغيل، والقيمة السوقية العادلة."},
                {"step_no": 4, "title": "مطابقة القيمة مع سعر الشراء", "description": "التأكد من أن سعر الاستحواذ أقل من أو يعادل القيمة السوقية المعتمدة."}
            ],
            "steps_en": [
                {"step_no": 1, "title": "Appoint Taqeem Appraiser", "description": "Engage certified valuation firm registered on Qayem portal."},
                {"step_no": 2, "title": "Provide Property Documentation", "description": "Furnish deed, drawings, rent roll, and operating history for DCF/Income modeling."},
                {"step_no": 3, "title": "Review Appraisal Draft", "description": "Audit cap rate assumptions, operating expenses, and final market valuation."},
                {"step_no": 4, "title": "Reconcile Valuation vs Price", "description": "Confirm acquisition price is at or below certified market value."}
            ],
            "sample_notes_ar": "تم استلام تقرير التقييم المعتمد من مكتب تقييم مرخص (مقيّمين): القيمة السوقية العادلة 12,450,000 ريال بأسلوب رسملة الدخل بعائد 8.2%، مما يؤكد جدوى سعر الاستحواذ 12,000,000 ريال.",
            "sample_notes_en": "Certified Taqeem valuation report received: Fair market value assessed at 12.45M SAR (8.2% cap rate), supporting 12M acquisition."
        }
    },
    {
        "template_id": "TASK_INVEST_ENVIRONMENTAL_SOIL_CHECK",
        "template_type": "TASK",
        "title_ar": "الاستثمار — الفحص المساحي وميكانيكا التربة والسلامة البيئية",
        "title_en": "Investment — Boundary Survey, Soil Mechanics & Environmental Safety",
        "owner_role": "INVESTMENT_ADVISOR",
        "sla_minutes": 2880,
        "criteria_ar": "مراجعة الكروكي المساحي ومطابقة الأبعاد والارتدادات، وتقرير التربة أو التصريف والمناسيب الجغرافية.",
        "criteria_en": "Review cadastral survey, verify boundary dimensions/setbacks, and inspect soil mechanics or flood drainage levels.",
        "category": "INVESTMENT",
        "sop": {
            "stage_code": "STAGE_INVEST_SURVEY_SOIL",
            "stage_name_ar": "الاستثمار — الفحص المساحي والسلامة البيئية",
            "stage_name_en": "Investment — Boundary & Environmental Survey",
            "required_now_ar": "إجراء مسح طبوغرافي ومطابقة إحداثيات ومناسيب الأرض مع كروكي الأمانة.",
            "required_now_en": "Conduct cadastral boundary survey and verify elevation, coordinates, and zoning setbacks.",
            "current_responsible_ar": "مستشار الاستثمار العقاري",
            "current_responsible_en": "Investment Advisor",
            "next_action_ar": "إرفاق التقرير المساحي لملف الفحص النافي للجهالة وتأكيد عدم وجود تعديات على الشوارع أو المجاورين.",
            "next_action_en": "Append survey report to DD dossier confirming no boundary encroachments or zoning violations.",
            "step_goal_ar": "التحقق من سلامة الأبعاد الفعلية للعقار وعدم وقوعه في مجاري سيول أو هبوط تربة.",
            "step_goal_en": "Verify actual site boundaries and confirm absence of flood drainage hazards or soil instability.",
            "mandatory_conditions_ar": "فحص مناسيب الأرض، مطابقة الارتدادات، والتأكد من عدم وجود شوائب تلوث بيئي.",
            "mandatory_conditions_en": "Survey ground elevation, confirm setback compliance, and inspect for environmental contamination.",
            "consequence_ar": "التعدي على الارتدادات أو خطوط التنظيم يعرض المبنى لغرامات بلدية ورفض رخص التشغيل.",
            "consequence_en": "Encroachments or setback violations trigger municipal fines and commercial operating permit refusals.",
            "steps_ar": [
                {"step_no": 1, "title": "المطابقة المساحية الميدانية", "description": "رفع إحداثيات العقار بواسطة جهاز GPS مساحي ومطابقتها مع كروكي الأمانة."},
                {"step_no": 2, "title": "فحص الارتدادات والشوارع", "description": "التأكد من خلو الموقع من أي تعديات على خط التنظيم أو العقارات المجاورة."},
                {"step_no": 3, "title": "مراجعة تقرير التربة وتصريف السيول", "description": "التحقق من سلامة منسوب الشارع وتصريف مياه الأمطار وعدم وجود مياه جوفية مرتفعة."},
                {"step_no": 4, "title": "إصدار شهادة الفحص المساحي", "description": "اعتماد التقرير من مكتب هندسي مساحي معتمد وإرفاقه لملف الاستثمار."}
            ],
            "steps_en": [
                {"step_no": 1, "title": "Field Boundary Survey", "description": "Survey coordinates using geodetic GPS and cross-check with municipal cadastral map."},
                {"step_no": 2, "title": "Setback & Right-of-Way Audit", "description": "Ensure zero encroachments on municipal street setbacks or adjoining properties."},
                {"step_no": 3, "title": "Flood & Drainage Assessment", "description": "Verify ground elevation, stormwater drainage, and absence of high water table issues."},
                {"step_no": 4, "title": "Issue Survey Certification", "description": "Certify report via licensed surveying engineering office for transaction file."}
            ],
            "sample_notes_ar": "تمت المطابقة المساحية: الأبعاد مطابقة للصك تماماً (الواجهة 35م والعمق 40م)، الارتدادات نظامية، ولا توجد أي تعديات مساحية.",
            "sample_notes_en": "Boundary survey completed: Dimensions strictly match deed (35m facade x 40m depth), setbacks fully compliant."
        }
    },

    # 2. Sales & Dispositions
    {
        "template_id": "TASK_SALE_NEGOTIATE_CONCESSIONS",
        "template_type": "TASK",
        "title_ar": "البيع — التفاوض على التخفيض وشروط السداد الإضافية",
        "title_en": "Sale — Price Concession & Extended Payment Negotiation",
        "owner_role": "SALES_AGENT",
        "sla_minutes": 1440,
        "criteria_ar": "توثيق مفاوضات تخفيض السعر وجدولة الدفعات بما يحقق متطلبات المشتري وموافقة المالك كتابياً.",
        "criteria_en": "Document price concession and installment scheduling aligned with buyer needs and written seller agreement.",
        "category": "SALE",
        "sop": {
            "stage_code": "STAGE_SALE_NEGOTIATION",
            "stage_name_ar": "البيع — التفاوض على التخفيض وشروط السداد",
            "stage_name_en": "Sale — Price Concession Negotiation",
            "required_now_ar": "إدارة جولات التفاوض بين البائع والمشتري لتقريب وجهات النظر حول السعر النهائي وجدولة الدفعات.",
            "required_now_en": "Manage buyer-seller negotiation sessions to bridge pricing gap and structure payment schedule.",
            "current_responsible_ar": "وسيط المبيعات",
            "current_responsible_en": "Sales Agent",
            "next_action_ar": "تثبيت السعر المتفق عليه في العرض المالي وتجهيز العقد الابتدائي.",
            "next_action_en": "Lock final agreed price into sales offer and initiate preliminary contract.",
            "step_goal_ar": "الوصول إلى اتفاق سعري ملزم يضمن إتمام الصفقة دون انسحاب أي طرف.",
            "step_goal_en": "Reach binding pricing agreement ensuring transaction completion without party dropouts.",
            "mandatory_conditions_ar": "الحصول على موافقة خطية أو إلكترونية من المالك على السعر المخفض وجدولة الدفعات.",
            "mandatory_conditions_en": "Secure written or electronic seller confirmation on discounted price and payment terms.",
            "consequence_ar": "التأخر في إدارة التفاوض قد يؤدي إلى انسحاب المشتري لشراء عقار منافس.",
            "consequence_en": "Delayed negotiation management risks buyer churn to competing market listings.",
            "steps_ar": [
                {"step_no": 1, "title": "استلام رغبة المشتري ومقترحه", "description": "حصر السعر المستهدف وشروط الدفعات التي يطلبها المشتري."},
                {"step_no": 2, "title": "تقديم المبررات التسويقية للمالك", "description": "عرض العرض المالي مع مؤشرات السوق والصفقات المماثلة لإقناع البائع بالتخفيض."},
                {"step_no": 3, "title": "التوصل إلى اتفاق سعري وسطي", "description": "صياغة التنازلات المتبادلة (مثل تسريع موعد الإفراغ مقابل الخصم)."},
                {"step_no": 4, "title": "توثيق الموافقة وتحديث بيانات الفرصة", "description": "تعديل القيمة المتوقعة للصفقة في النظام وإشعار الأطراف رسمياً."}
            ],
            "steps_en": [
                {"step_no": 1, "title": "Gather Buyer Counter-Offer", "description": "Document target purchase price and preferred installment schedule from buyer."},
                {"step_no": 2, "title": "Present Market Data to Seller", "description": "Share market comps and competitive pricing data to persuade seller on concession."},
                {"step_no": 3, "title": "Broker Win-Win Compromise", "description": "Structure trade-offs (e.g. earlier closing date in exchange for price discount)."},
                {"step_no": 4, "title": "Formalize Seller Approval", "description": "Update expected opportunity value in system and formally notify both parties."}
            ],
            "sample_notes_ar": "تم التفاوض بين البائع والمشتري: خفض المالك السعر من 1,500,000 إلى 1,420,000 ريال مقابل التزام المشتري بسداد الدفعة كاملة خلال 14 يوماً.",
            "sample_notes_en": "Price negotiation concluded: Seller reduced asking price from 1.5M to 1.42M SAR in exchange for 14-day expedited closing."
        }
    },
    {
        "template_id": "TASK_SALE_TITLE_DEED_VERIFICATION",
        "template_type": "TASK",
        "title_ar": "البيع — التحقق من سلامة الصك والرهن العقاري والفرز",
        "title_en": "Sale — Title Deed, Mortgage Release & Subdivision Verification",
        "owner_role": "LEGAL",
        "sla_minutes": 1440,
        "criteria_ar": "التأكد من سريان الصك، فك الرهن البنكي إن وجد، واكتمال محاضر الفرز للوحدات المفرزة لدى بلدي.",
        "criteria_en": "Verify title deed validity, ensure release of prior mortgages, and confirm municipal subdivision records on Balady.",
        "category": "SALE",
        "sop": {
            "stage_code": "STAGE_SALE_TITLE_VERIFY",
            "stage_name_ar": "البيع — التحقق من سلامة الصك والرهن والفرز",
            "stage_name_en": "Sale — Title Deed & Encumbrance Verification",
            "required_now_ar": "مطابقة بيانات الصك مع الهوية والتحقق من عدم وجود رهن قائم أو حظر إفراغ.",
            "required_now_en": "Reconcile title deed data with seller ID and verify absence of active mortgage or conveyance bans.",
            "current_responsible_ar": "المستشار القانوني",
            "current_responsible_en": "Legal Counsel",
            "next_action_ar": "إصدار إفادة الجاهزية للإفراغ أو توجيه البائع لإنهاء فك الرهن من الجهة التمويلية.",
            "next_action_en": "Issue conveyance readiness clearance or guide seller to obtain mortgage discharge letter.",
            "step_goal_ar": "التأكد من الجاهزية القانونية المطلقة للعقار قبل تحصيل العربون وتوقيع العقود.",
            "step_goal_en": "Ensure absolute legal conveyance readiness before collecting earnest money or signing contracts.",
            "mandatory_conditions_ar": "الاستعلام الإلكتروني عبر البورصة العقارية، ومطابقة رقم القطعة والمخطط في منصة بلدي.",
            "mandatory_conditions_en": "Electronic inquiry on Real Estate Exchange and matching parcel/plan number on Balady portal.",
            "consequence_ar": "عدم فحص الرهن والفرز مسبقاً يعطل الصفقة في مرحلة الإفراغ ويؤدي لفسخ العقود وتحميل المكتب المسؤولية.",
            "consequence_en": "Failing to verify encumbrances in advance stalls closing, triggers contract breaches, and risks brokerage liability.",
            "steps_ar": [
                {"step_no": 1, "title": "الاستعلام عن الصك في البورصة العقارية", "description": "التأكد من أن الصك إلكتروني ونشط وخالي من أي موانع نظامية."},
                {"step_no": 2, "title": "التحقق من الرهن وفكه", "description": "في حال وجود رهن بنكي سابق، التأكد من صدور خطاب فك الرهن ومطابقته لدى العدل."},
                {"step_no": 3, "title": "فحص قرار ومحضر الفرز", "description": "للوحدات السكنية المفرزة: التأكد من مطابقة محضر الفرز المعتمد لدى وزارة الإسكان/بلدي."},
                {"step_no": 4, "title": "إصدار تقرير الجاهزية للإفراغ", "description": "توثيق النتيجة ورفع التقرير لملف المعاملة."}
            ],
            "steps_en": [
                {"step_no": 1, "title": "Real Estate Exchange Inquiry", "description": "Verify deed is electronic, active, and free of administrative/judicial holds."},
                {"step_no": 2, "title": "Mortgage Release Verification", "description": "If prior mortgage exists, verify official discharge instrument from lender."},
                {"step_no": 3, "title": "Subdivision Record Audit", "description": "For subdivided residential units: Audit subdivision certificate on Balady/MOMRAH."},
                {"step_no": 4, "title": "Issue Closing Clearance", "description": "Document findings and upload clearance memo to transaction file."}
            ],
            "sample_notes_ar": "تم التحقق من الصك والفرز: الصك مفرز إلكترونياً برقم 310928374823، تم فك الرهن البنكي بنجاح والعقار جاهز للإفراغ الفوري.",
            "sample_notes_en": "Title and subdivision verified: Unit deed subdivided electronically, mortgage released, property 100% ready for conveyance."
        }
    },
    {
        "template_id": "TASK_SALE_MORTGAGE_PREQUALIFICATION",
        "template_type": "TASK",
        "title_ar": "البيع — التنسيق مع جهات التمويل العقاري والتأهيل البنكي",
        "title_en": "Sale — Mortgage Facilitation & Bank Prequalification",
        "owner_role": "SALES_AGENT",
        "sla_minutes": 2880,
        "criteria_ar": "التأكد من الأهلية التمويلية للعميل، واستلام خطاب الموافقة المبدئية أو الحسبة التمويلية المعتمدة من البنك.",
        "criteria_en": "Verify buyer mortgage eligibility and obtain preliminary bank pre-approval letter or financing assessment.",
        "category": "SALE",
        "sop": {
            "stage_code": "STAGE_SALE_MORTGAGE_PREQUAL",
            "stage_name_ar": "البيع — التأهيل والتمويل العقاري",
            "stage_name_en": "Sale — Mortgage Prequalification",
            "required_now_ar": "التواصل مع مستشار التمويل البنكي لتحديد سقف التمويل المتاح للمشتري وقيمة الدفعة الأولى والالتزامات.",
            "required_now_en": "Liaise with mortgage advisor to assess buyer maximum borrowing capacity, down payment, and DSTI ratio.",
            "current_responsible_ar": "وسيط المبيعات",
            "current_responsible_en": "Sales Agent",
            "next_action_ar": "استلام الحسبة البنكية المعتمدة والتأكد من تغطيتها لكامل سعر العقار قبل تحرير السندات.",
            "next_action_en": "Receive certified bank pre-approval ensuring mortgage covers purchase price before formal commitments.",
            "step_goal_ar": "تأمين الجاهزية التمويلية للمشتري وتفادي إلغاء الصفقة لعدم كفاية التمويل.",
            "step_goal_en": "Ensure buyer mortgage readiness and prevent transaction cancellation due to financing shortfall.",
            "mandatory_conditions_ar": "حساب نسبة الاستقطاع الشهري (DBR)، توفر الدفعة الأولى النقدية، واستيفاء اشتراطات صندوق التنمية العقارية إن وجد.",
            "mandatory_conditions_en": "Verify debt service ratio, confirm cash down payment availability, and REDF subsidy status.",
            "consequence_ar": "توقيع العقود دون تأهيل تمويلي للمشتري قد يؤدي إلى حجز العقار عبثاً ثم تعثر الإفراغ وفقدان العربون.",
            "consequence_en": "Executing contracts without mortgage pre-qualification ties up property and risks deal collapse.",
            "steps_ar": [
                {"step_no": 1, "title": "جمع البيانات المالية للمشتري", "description": "حصر الراتب الصافي، جهة العمل، الالتزامات الائتمانية في سمة، وقيمة الدفعة الأولى."},
                {"step_no": 2, "title": "التنسيق مع البنوك المعتمدة", "description": "رفع طلب الحسبة لدى البنوك الشريكة للمقارنة بين نسب الفائدة ومرابحة التمويل."},
                {"step_no": 3, "title": "استلام خطاب الأهلية المبدئي", "description": "الحصول على موافقة تمويلية مبدئية تؤكد تغطية البنك لقيمة العقار المطلوبة."},
                {"step_no": 4, "title": "تأكيد خطة السداد مع البائع", "description": "إشعار البائع بآلية الشراء عن طريق التمويل العقاري والجدول الزمني للتقييم والإفراغ."}
            ],
            "steps_en": [
                {"step_no": 1, "title": "Collect Financial Profile", "description": "Gather net income, employer tier, SIMAH commitments, and available cash equity."},
                {"step_no": 2, "title": "Engage Partner Banks", "description": "Submit file to partner mortgage desks to benchmark APR rates and loan amounts."},
                {"step_no": 3, "title": "Obtain Prequalification Letter", "description": "Receive preliminary bank approval letter confirming sufficient loan ceiling."},
                {"step_no": 4, "title": "Align Closing Timeline with Seller", "description": "Brief seller on bank financing timeline for appraisal, title check, and bank transfer."}
            ],
            "sample_notes_ar": "تم الحصول على خطاب تأهيل مبدئي من مصرف الراجحي بتمويل 1,200,000 ريال، والعميل سيسدد 250,000 ريال نقداً كدفعة أولى وسعي المكتب والضريبة.",
            "sample_notes_en": "Mortgage pre-approval secured from Al Rajhi Bank for 1.2M SAR. Buyer providing 250k SAR down payment and closing costs."
        }
    },
    {
        "template_id": "TASK_SALE_DEFECTS_DISCLOSURE",
        "template_type": "TASK",
        "title_ar": "البيع — إعداد وتوقيع إقرار الإفصاح عن عيوب العقار",
        "title_en": "Sale — Property Condition & Defects Disclosure Statement",
        "owner_role": "SALES_AGENT",
        "sla_minutes": 1440,
        "criteria_ar": "حصر وإفصاح المالك عن أية عيوب جوهرية أو خفية والتوقيع على إقرار الإفصاح النظامي لحماية أطراف الصفقة.",
        "criteria_en": "Record seller disclosure of latent/material defects and sign statutory disclosure form protecting both transaction parties.",
        "category": "SALE",
        "sop": {
            "stage_code": "STAGE_SALE_DEFECTS_DISCLOSURE",
            "stage_name_ar": "البيع — إقرار الإفصاح عن العيوب",
            "stage_name_en": "Sale — Property Defects Disclosure",
            "required_now_ar": "تعبئة نموذج الإفصاح العقاري المعتمد وتوقيعه من البائع قبل توقيع عقد المبايعة النهائي.",
            "required_now_en": "Complete statutory property disclosure statement signed by seller prior to final sales agreement.",
            "current_responsible_ar": "وسيط المبيعات",
            "current_responsible_en": "Sales Agent",
            "next_action_ar": "إطلاع المشتري على نموذج الإفصاح وأخذ توقيعه بالعلم والقبول وإرفاقه كملحق للعقد.",
            "next_action_en": "Present signed disclosure to buyer for formal acknowledgement and attach as contract addendum.",
            "step_goal_ar": "حماية الوسيط والمشتري من النزاعات القضائية الناتجة عن دعاوى العيوب الخفية وغش المبيع.",
            "step_goal_en": "Protect broker and buyer against latent defect litigation and misrepresentation claims.",
            "mandatory_conditions_ar": "تغطية العيوب الإنشائية، التسريبات، التعديلات غير المرخصة، وأي نزاعات أو مطالبات سابقة.",
            "mandatory_conditions_en": "Cover structural flaws, water leaks, unpermitted additions, and prior municipal citations.",
            "consequence_ar": "إغفال نموذج الإفصاح يمنح المشتري الحق في فسخ البيع ومقاضاة البائع والوسيط للتعويض عن العيوب الخفية.",
            "consequence_en": "Omitting disclosure statement grants buyer grounds for contract rescission and damages claims.",
            "steps_ar": [
                {"step_no": 1, "title": "استعراض بنود الإفصاح مع البائع", "description": "مراجعة الأسئلة النظامية الخاصة بالتسريبات، التصدعات، الأعمال الكهربائية، وعمر المعدات."},
                {"step_no": 2, "title": "توثيق الملاحظات إن وجدت", "description": "تسجيل أي عيوب صريحة أو أعمال صيانة سابقة قام بها المالك وتكلفتها."},
                {"step_no": 3, "title": "توقيع البائع على الإقرار", "description": "أخذ توقيع المالك على النموذج النظامي المعتمد من الهيئة العامة للعقار."},
                {"step_no": 4, "title": "إطلاع المشتري وتوقيعه بالعلم", "description": "تسليم نسخة للمشتري وتوقيعه عليها بالعلم والقبول قبل تحويل العربون."}
            ],
            "steps_en": [
                {"step_no": 1, "title": "Review Disclosure Questionnaire", "description": "Review statutory questionnaire covering leaks, settlement, MEP systems, and equipment age."},
                {"step_no": 2, "title": "Document Disclosed Defects", "description": "Record known defects, structural repairs, or historical maintenance performed by owner."},
                {"step_no": 3, "title": "Execute Seller Signature", "description": "Secure seller signature on REGA-compliant property condition disclosure form."},
                {"step_no": 4, "title": "Obtain Buyer Acknowledgment", "description": "Provide copy to buyer and obtain signed acceptance before earnest deposit is processed."}
            ],
            "sample_notes_ar": "تم توقيع إقرار الإفصاح عن العيوب من البائع: أفصح المالك عن إجراء عزل مائي لسطح الملحق في 2024 بضمان 10 سنوات، ووقع المشتري بالعلم والقبول.",
            "sample_notes_en": "Defects disclosure statement executed: Seller disclosed 2024 roof waterproofing under 10-year warranty. Buyer signed acceptance."
        }
    },

    # 3. Leasing & Rentals
    {
        "template_id": "TASK_RENT_TENANT_SCREENING_CREDIT",
        "template_type": "TASK",
        "title_ar": "الإيجار — الاستعلام عن السلوك الإيجاري والتعثر المالي للمستأجر",
        "title_en": "Rental — Tenant Screening & Ejar / Credit History Check",
        "owner_role": "LEASING_AGENT",
        "sla_minutes": 720,
        "criteria_ar": "التحقق من السجل الائتماني والالتزام بالسداد عبر منصة إيجار/سمة، والتأكد من خلو المستأجر من السوابق الإيجارية المتعثرة.",
        "criteria_en": "Check rental credit record on Ejar/Simah and verify tenant is free of delinquent rental disputes.",
        "category": "RENT",
        "sop": {
            "stage_code": "STAGE_RENT_TENANT_SCREENING",
            "stage_name_ar": "الإيجار — فحص السلوك الإيجاري والائتماني",
            "stage_name_en": "Rental — Tenant Screening & Credit Check",
            "required_now_ar": "إجراء استعلام نظامي عن المستأجر للتحقق من سجله في منصة إيجار وخلوه من مطالبات التنفيذ المالية.",
            "required_now_en": "Conduct statutory inquiry on tenant checking Ejar track record and absence of enforcement orders.",
            "current_responsible_ar": "وسيط التأجير",
            "current_responsible_en": "Leasing Agent",
            "next_action_ar": "إصدار تقرير الأهلية الإيجارية للمؤجر والمضي في إعداد مسودة العقد أو الاعتذار للمستأجر.",
            "next_action_en": "Issue rental eligibility memo to landlord and proceed with contract drafting or politely decline.",
            "step_goal_ar": "حماية المؤجر من مخاطر المماطلة وتراكم الإيجارات وتكاليف الإخلاء القضائي.",
            "step_goal_en": "Protect landlord against default, rent arrears, and costly judicial eviction proceedings.",
            "mandatory_conditions_ar": "موافقة المستأجر على الاستعلام الائتماني، إثبات الدخل أو السجل التجاري، وخلوه من قضايا تنفيذ إيجارية نشطة.",
            "mandatory_conditions_en": "Tenant consent for credit inquiry, proof of income or commercial registration, and zero active Ejar defaults.",
            "consequence_ar": "تأجير العقار لمستأجر متعثر يكبد المالك خسائر توقف الدخل لعدة أشهر وإشغال العقار دون مقابل.",
            "consequence_en": "Leasing to a delinquent tenant causes months of rental income loss and vacant holding costs.",
            "steps_ar": [
                {"step_no": 1, "title": "طلب موافقة الاستعلام الائتماني", "description": "إرسال طلب موافقة التحقق المالي للمستأجر عبر منصة إيجار أو سمة."},
                {"step_no": 2, "title": "فحص السجل الإيجاري السابق", "description": "التحقق من عدد العقود السابقة ونسبة الالتزام بالسداد ومواعيد الدفعات."},
                {"step_no": 3, "title": "التحقق من الملاءة المالية والوظيفة", "description": "مطابقة خطاب تعريف الراتب أو السجل التجاري للتأكد من قدرته على سداد الدفعات."},
                {"step_no": 4, "title": "إشعار المؤجر بالنتيجة", "description": "تقديم ملخص نتائج الفحص للمالك والحصول على موافقته النهائية على التأجير."}
            ],
            "steps_en": [
                {"step_no": 1, "title": "Obtain Screening Consent", "description": "Send statutory credit verification consent request to tenant via Ejar or SIMAH."},
                {"step_no": 2, "title": "Audit Rental Track Record", "description": "Review prior rental contracts, payment timeliness, and absence of non-payment disputes."},
                {"step_no": 3, "title": "Verify Employment & Solvency", "description": "Verify salary certificate or commercial registration ensuring adequate debt-to-income coverage."},
                {"step_no": 4, "title": "Submit Screening Summary to Owner", "description": "Present verification summary to landlord to secure formal onboarding approval."}
            ],
            "sample_notes_ar": "تم الاستعلام عن المستأجر في منصة إيجار: سجله ممتاز، 4 عقود سابقة مسددة بالكامل في مواعيدها بدون أي مطالبات تنفيذ، والدخل الشهري يعادل 4 أضعاف القسط الإيجاري.",
            "sample_notes_en": "Tenant screened via Ejar: Outstanding rating, 4 prior contracts paid in full with zero disputes, income is 4x rental installment."
        }
    },
    {
        "template_id": "TASK_RENT_SPECIAL_CONDITIONS_NEGOTIATION",
        "template_type": "TASK",
        "title_ar": "الإيجار — التفاوض على فترات السماح والشروط الاستثنائية",
        "title_en": "Rental — Grace Period & Custom Lease Conditions Negotiation",
        "owner_role": "LEASING_AGENT",
        "sla_minutes": 1440,
        "criteria_ar": "الاتفاق على فترة السماح لأعمال الديكور والتشطيب، وتوثيق أية شروط خاصة تخص الصيانة والخدمات المشتركة.",
        "criteria_en": "Agree on fit-out grace period and document special terms regarding maintenance, fit-out, and shared utilities.",
        "category": "RENT",
        "sop": {
            "stage_code": "STAGE_RENT_CUSTOM_TERMS",
            "stage_name_ar": "الإيجار — التفاوض على فترات السماح والشروط الخاصة",
            "stage_name_en": "Rental — Grace Period & Special Terms Negotiation",
            "required_now_ar": "التفاوض وتحديد فترة السماح المجانية للتجهيز والديكور وتوزيع تكاليف الصيانة الاستهلاكية والجوهرية.",
            "required_now_en": "Negotiate rent-free fit-out grace period and delineate structural vs routine maintenance responsibilities.",
            "current_responsible_ar": "وسيط التأجير",
            "current_responsible_en": "Leasing Agent",
            "next_action_ar": "إدراج الشروط المتفق عليها ضمن الملاحظات والبنود المخصصة في عقد إيجار الإلكتروني الموحد.",
            "next_action_en": "Embed agreed terms into customized clauses of Unified Electronic Ejar contract.",
            "step_goal_ar": "صياغة علاقة تعاقدية متوازنة تمنع الخلافات التشغيلية أثناء فترة الإيجار.",
            "step_goal_en": "Structure balanced contractual terms preventing operational friction during lease term.",
            "mandatory_conditions_ar": "موافقة المؤجر الخطية على مدة السماح، وتحديد تاريخ سريان الإيجار الفعلي وتاريخ استحقاق الدفعة الأولى.",
            "mandatory_conditions_en": "Landlord written consent on grace period, specifying actual lease start and initial payment due dates.",
            "consequence_ar": "عدم توثيق فترة السماح صراحة يسبب نزاعات حول بداية سريان العقد وتاريخ استحقاق الإيجار.",
            "consequence_en": "Failing to document grace period triggers billing disputes regarding rent commencement dates.",
            "steps_ar": [
                {"step_no": 1, "title": "حصر متطلبات المستأجر الخاصة", "description": "تحديد مدة السماح المطلوبة للتجهيز (مثال: شهرين للنشاط التجاري أو أسبوعين للسكني)."},
                {"step_no": 2, "title": "مواءمة الشروط مع المالك", "description": "عرض خطة التجهيزات على المالك والتأكد من عدم الإضرار بالهيكل الإنشائي للعقار."},
                {"step_no": 3, "title": "تحديد مسؤوليات الصيانة والخدمات", "description": "الاتفاق على تكاليف الصيانة الدورية مقابل الصيانة الإنشائية واستهلاك المياه والكهرباء."},
                {"step_no": 4, "title": "إدراج البنود في مسودة العقد", "description": "صياغة الشروط الإضافية بدقة وفق اللائحة التنفيذية لنظام الوساطة ومنصة إيجار."}
            ],
            "steps_en": [
                {"step_no": 1, "title": "Gather Fit-Out Requirements", "description": "Identify requested rent-free period (e.g. 60 days commercial fit-out or 2 weeks residential)."},
                {"step_no": 2, "title": "Align Terms with Landlord", "description": "Present fit-out schedule to landlord ensuring structural integrity of building."},
                {"step_no": 3, "title": "Delineate Maintenance Roles", "description": "Clarify routine vs structural maintenance and allocate common utility service fees."},
                {"step_no": 4, "title": "Incorporate in Contract Draft", "description": "Draft custom conditions strictly aligned with REGA Unified Ejar regulations."}
            ],
            "sample_notes_ar": "تم الاتفاق على منح المستأجر فترة سماح مدتها 45 يوماً لأعمال الديكور تبدأ من 1 نوفمبر، ويبدأ احتساب الإيجار الفعلي من 16 ديسمبر مع التزام المستأجر بعدم تعديل الواجهات الخارجية.",
            "sample_notes_en": "Agreed on 45-day rent-free fit-out period starting Nov 1. Lease billing commences Dec 16. Tenant agrees not to modify facade."
        }
    },
    {
        "template_id": "TASK_RENT_COMMERCIAL_LICENSING_CHECK",
        "template_type": "TASK",
        "title_ar": "الإيجار — التحقق من مطابقة اشتراطات الرخص والنشاط التجاري",
        "title_en": "Rental — Municipal Commercial Licensing & Zoning Compatibility",
        "owner_role": "LEASING_AGENT",
        "sla_minutes": 1440,
        "criteria_ar": "التحقق من إمكانية استخراج رخصة النشاط التجاري للوحدة لدى الأمانة والدفاع المدني دون عوائق تخطيطية.",
        "criteria_en": "Verify eligibility for commercial municipal licensing and Civil Defense permits for intended business activity.",
        "category": "RENT",
        "sop": {
            "stage_code": "STAGE_RENT_COMMERCIAL_ZONING",
            "stage_name_ar": "الإيجار — مطابقة التراخيص والنشاط التجاري",
            "stage_name_en": "Rental — Commercial Licensing & Zoning Check",
            "required_now_ar": "التحقق من تصنيف استخدام المبنى في رخصة البناء ومطابقة كود النشاط التجاري لدى بلدي والسلامة.",
            "required_now_en": "Verify building permit occupancy classification and audit intended commercial activity code on Balady.",
            "current_responsible_ar": "وسيط التأجير",
            "current_responsible_en": "Leasing Agent",
            "next_action_ar": "إفادة المستأجر بجاهزية الموقع لإصدار الرخصة الفورية أو تحديد المتطلبات التعديلية اللازمة.",
            "next_action_en": "Advise tenant on instant licensing eligibility or detail required structural/MEP modifications.",
            "step_goal_ar": "تفادي استئجار عقار تجاري يتعذر تشغيله نظامياً بسبب عوائق بلدية أو تنظيمية.",
            "step_goal_en": "Prevent leasing commercial premises that cannot be licensed due to municipal or zoning barriers.",
            "mandatory_conditions_ar": "التحقق من عرض الشارع التجاري، توفر مواقف سيارات نظامية، ورخصة سلامة الدفاع المدني للمبنى.",
            "mandatory_conditions_en": "Verify commercial street width, parking compliance, and building Civil Defense safety license.",
            "consequence_ar": "تأجير الوحدة لنشاط غير مسموح يؤدي لرفض رخصة بلدي وإلغاء العقد وتحمل الوسيط تعويضات التجهيز.",
            "consequence_en": "Leasing unit for unpermitted use triggers municipal rejection, contract voiding, and fit-out compensation claims.",
            "steps_ar": [
                {"step_no": 1, "title": "مراجعة رخصة بناء العقار", "description": "التحقق من أن رخصة البناء تنص على الاستخدام التجاري أو المعارض."},
                {"step_no": 2, "title": "مطابقة النشاط في دليل بلدي", "description": "مطابقة كود النشاط التجاري المستهدف مع اشتراطات الشارع ونوع المبنى."},
                {"step_no": 3, "title": "فحص اشتراطات الدفاع المدني", "description": "التأكد من توفر مخارج الطوارئ ومضخات الحريق وشهادة سلامة سارية."},
                {"step_no": 4, "title": "توثيق النتيجة في ملف الإيجار", "description": "إصدار تقرير الجاهزية للرخصة البلدية وتوقيع المستأجر بالاستلام."}
            ],
            "steps_en": [
                {"step_no": 1, "title": "Review Building Permit", "description": "Verify building permit expressly designates commercial showroom or retail use."},
                {"step_no": 2, "title": "Check Activity on Balady", "description": "Cross-check commercial activity code against municipal street zoning matrix."},
                {"step_no": 3, "title": "Civil Defense Safety Check", "description": "Confirm emergency exits, fire suppression systems, and active safety certification."},
                {"step_no": 4, "title": "Document Licensing Memo", "description": "Issue licensing clearance memo and secure tenant written acknowledgment."}
            ],
            "sample_notes_ar": "تم التحقق من رخصة البناء والمخطط: الشارع تجاري بعرض 40م، النشاط المستهدف (صيدلية) مطابق ومسموح به لدى أمانة الرياض، ونظام السلامة معتمد.",
            "sample_notes_en": "Zoning & licensing verified: Street width 40m commercial, intended pharmacy activity permitted by Municipality, Civil Defense compliant."
        }
    },
    {
        "template_id": "TASK_RENT_SECURITY_DEPOSIT_RECEIPT",
        "template_type": "TASK",
        "title_ar": "الإيجار — توثيق واستلام مبلغ تأمين الأضرار والضمان",
        "title_en": "Rental — Security & Damage Deposit Receipt & Safeguarding",
        "owner_role": "ACCOUNTANT",
        "sla_minutes": 1440,
        "criteria_ar": "استلام سند إيداع مبلغ الضمان المسترد وإصدار سند قبض وتوثيق شروط استرداده عند الإخلاء.",
        "criteria_en": "Receive security deposit, issue official receipt voucher, and specify refund inspection terms upon move-out.",
        "category": "RENT",
        "sop": {
            "stage_code": "STAGE_RENT_SECURITY_DEPOSIT",
            "stage_name_ar": "الإيجار — تأمين الضمان والأضرار",
            "stage_name_en": "Rental — Security Deposit Safeguarding",
            "required_now_ar": "استلام مبلغ تأمين الأضرار من المستأجر وإيداعه في حساب أمانات الضمان وتوثيق سند القبض.",
            "required_now_en": "Collect damage security deposit from tenant, deposit into escrow account, and issue official voucher.",
            "current_responsible_ar": "المحاسب المالي",
            "current_responsible_en": "Financial Accountant",
            "next_action_ar": "ربط سند الضمان بملف العقد ومحضر المعاينة والاستلام تمهيداً للمطابقة عند انتهاء الإيجار.",
            "next_action_en": "Link deposit voucher to contract file and move-in inspection report for move-out reconciliation.",
            "step_goal_ar": "تأمين حقوق المالك في إصلاح أي أضرار تشغيلية أو فواتير استهلاك معلقة عند إخلاء الوحدة.",
            "step_goal_en": "Secure landlord rights against post-tenancy damages and unpaid utility bills upon move-out.",
            "mandatory_conditions_ar": "إيداع المبلغ في الحساب البنكي المعتمد، إرفاق إشعار التحويل البنكي، وتحديد شروط استرداده خطياً.",
            "mandatory_conditions_en": "Deposit funds into authorized escrow bank account, attach transfer slip, and detail refund criteria in writing.",
            "consequence_ar": "عدم تحصيل التأمين يترك المالك بدون غطاء مالي في حال ترك المستأجر للعقار بأضرار أو فواتير متراكمة.",
            "consequence_en": "Omitting security deposit exposes landlord to unrecoverable damage repair costs and unpaid utility balances.",
            "steps_ar": [
                {"step_no": 1, "title": "احتساب مبلغ الضمان", "description": "تحديد قيمة التأمين المتفق عليها في العقد (عادة شهر إيجار أو مبلغ مقطوع)."},
                {"step_no": 2, "title": "استلام التحويل وإصدار سند قبض", "description": "التأكد من دخول المبلغ في الحساب البنكي وإصدار سند قبض مالي رسمي مسجل فيه 'تأمين مسترد'."},
                {"step_no": 3, "title": "ربط التأمين بمحضر استلام الوحدة", "description": "إرفاق صور حالة العقار قبل التسليم لضمان المقارنة العادلة عند انتهاء العقد."},
                {"step_no": 4, "title": "إشعار أطراف العقد بالاكتمال", "description": "إرسال نسخة من سند القبض للمستأجر والمالك وتثبيت القيد المحاسبي."}
            ],
            "steps_en": [
                {"step_no": 1, "title": "Calculate Deposit Sum", "description": "Verify deposit amount agreed in lease terms (typically one month rent or fixed bond)."},
                {"step_no": 2, "title": "Confirm Wire & Issue Receipt", "description": "Verify bank credit and issue formal financial receipt voucher designated as 'Refundable Security Deposit'."},
                {"step_no": 3, "title": "Link to Move-In Inspection", "description": "Attach baseline move-in condition photos to guarantee fair comparison upon move-out."},
                {"step_no": 4, "title": "Notify Parties & Record Ledger", "description": "Transmit receipt copy to tenant and landlord and book accounting liability entry."}
            ],
            "sample_notes_ar": "تم استلام مبلغ تأمين الأضرار وقدره 5,000 ريال بحوالة بنكية على مصرف الإنماء، وإصدار سند قبض رقم RC-4482، وتم ربطه بمحضر التسليم.",
            "sample_notes_en": "Refundable security deposit of 5,000 SAR received via bank transfer. Receipt voucher RC-4482 issued and linked to move-in report."
        }
    }
]

async def seed_best_practices():
    conn = await asyncpg.connect(user='postgres', password='fAlnemari@1392', host='127.0.0.1', port=5432, database='re_db')
    print("Connected to DB successfully.")
    
    # 1. Insert or update workflow_templates
    for tmpl in BEST_PRACTICE_TEMPLATES:
        t_id = tmpl["template_id"]
        t_type = tmpl["template_type"]
        t_ar = tmpl["title_ar"]
        t_en = tmpl["title_en"]
        role = tmpl["owner_role"]
        sla = tmpl["sla_minutes"]
        crit_ar = tmpl["criteria_ar"]
        crit_en = tmpl["criteria_en"]

        await conn.execute("""
            INSERT INTO workflow_templates (
                template_id, template_type, standard_title_ar, standard_title_en,
                owner_role, default_sla_minutes, escalation_role, escalation_sla_minutes,
                created_at, completion_criteria_ar, completion_criteria_en
            ) VALUES ($1, $2, $3, $4, $5, $6, 'BRANCH_MANAGER', $6 * 2, NOW(), $7, $8)
            ON CONFLICT (template_id) DO UPDATE SET
                standard_title_ar = EXCLUDED.standard_title_ar,
                standard_title_en = EXCLUDED.standard_title_en,
                owner_role = EXCLUDED.owner_role,
                default_sla_minutes = EXCLUDED.default_sla_minutes,
                completion_criteria_ar = EXCLUDED.completion_criteria_ar,
                completion_criteria_en = EXCLUDED.completion_criteria_en
        """, t_id, t_type, t_ar, t_en, role, sla, crit_ar, crit_en)
        print(f"Seeded template: {t_id}")

        # 2. Insert or update workflow_sop_guidance
        sop = tmpl.get("sop")
        if sop:
            guidance_id = f"sop-{t_id.lower().replace('_', '-')}"
            await conn.execute("""
                INSERT INTO workflow_sop_guidance (
                    guidance_id, stage_code, template_id, stage_name_ar, stage_name_en,
                    required_now_ar, required_now_en, current_responsible_ar, current_responsible_en,
                    next_action_ar, next_action_en, step_goal_ar, step_goal_en,
                    mandatory_conditions_ar, mandatory_conditions_en, consequence_ar, consequence_en,
                    display_order, is_active, entity_type, procedure_code, responsible_role_code,
                    execution_steps_ar, execution_steps_en, sample_notes_ar, sample_notes_en,
                    created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5,
                    $6, $7, $8, $9,
                    $10, $11, $12, $13,
                    $14, $15, $16, $17,
                    50, TRUE, 'TASK', $3, $18,
                    $19, $20, $21, $22,
                    NOW(), NOW()
                )
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
                    execution_steps_ar = EXCLUDED.execution_steps_ar,
                    execution_steps_en = EXCLUDED.execution_steps_en,
                    sample_notes_ar = EXCLUDED.sample_notes_ar,
                    sample_notes_en = EXCLUDED.sample_notes_en,
                    updated_at = NOW()
            """,
            guidance_id, sop["stage_code"], t_id, sop["stage_name_ar"], sop["stage_name_en"],
            sop["required_now_ar"], sop["required_now_en"], sop["current_responsible_ar"], sop["current_responsible_en"],
            sop["next_action_ar"], sop["next_action_en"], sop["step_goal_ar"], sop["step_goal_en"],
            sop["mandatory_conditions_ar"], sop["mandatory_conditions_en"], sop["consequence_ar"], sop["consequence_en"],
            role,
            json.dumps(sop["steps_ar"], ensure_ascii=False),
            json.dumps(sop["steps_en"], ensure_ascii=False),
            sop["sample_notes_ar"], sop["sample_notes_en"]
            )
            print(f"  -> Seeded SOP guidance: {guidance_id}")

    # Count total
    total_tmpls = await conn.fetchval("SELECT COUNT(*) FROM workflow_templates WHERE template_type = 'TASK'")
    total_sops = await conn.fetchval("SELECT COUNT(*) FROM workflow_sop_guidance")
    print(f"\nCompleted successfully! Total TASK templates: {total_tmpls}, Total SOP rows: {total_sops}")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(seed_best_practices())
