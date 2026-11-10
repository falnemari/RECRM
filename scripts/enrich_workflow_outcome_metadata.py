import asyncio
import asyncpg
import json
import os
import sys

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "backend")))
from app.config import settings

# Rich metadata mapping for task outcome transitions
# Each outcome has:
# - next_template_id: template string or None
# - label_ar: Arabic label with icon
# - label_en: English label with icon
# - description_ar: detailed explanation of outcome and workflow behavior
# - description_en: English description
# - style: success | warning | danger | info | primary
# - requires_fields: callback | qual | viewing_schedule | viewing_report | offer | None

RICH_TASK_OUTCOMES = {
    "TASK_SALES_LEAD_CONTACT_QUALIFY": {
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
    },
    "TASK_LEAD_FOLLOWUP_QUALIFY": {
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
    },
    "TASK_MATCH_PROPERTIES": {
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
    },
    "TASK_LEAD_FIRST_CONTACT": {
        "CONNECTED": {
            "next_template_id": "TASK_LEAD_QUALIFY",
            "label_ar": "📞 تم التواصل بنجاح",
            "label_en": "📞 Connected",
            "description_ar": "ترقية حالة الطلب إلى (CONTACTED) وتوليد مهمة التأهيل تلقائياً",
            "description_en": "Promote lead to CONTACTED and automatically generate qualification task",
            "style": "success",
            "requires_fields": None
        },
        "NO_ANSWER": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "📵 لم يرد / تعذر الوصول",
            "label_en": "📵 No Answer / Busy",
            "description_ar": "جدولة متابعة تلقائية (سقف 3 محاولات ثم إغلاق كغير مستجيب)",
            "description_en": "Schedule automatic follow-up (up to 3 attempts before closing as unreachable)",
            "style": "warning",
            "requires_fields": None
        },
        "CALLBACK_REQUESTED": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "⏰ طلب معاودة الاتصال لاحقاً",
            "label_en": "⏰ Callback Requested",
            "description_ar": "تحديد موعد وتوقيت إعادة الاتصال بالعميل",
            "description_en": "Specify date and time to call the client back",
            "style": "warning",
            "requires_fields": "callback"
        },
        "INVALID_CONTACT": {
            "next_template_id": None,
            "label_ar": "📵 رقم خاطئ / تعذر الاتصال نهائياً",
            "label_en": "📵 Invalid Contact / Wrong Number",
            "description_ar": "استبعاد الطلب لعدم صحة بيانات الاتصال",
            "description_en": "Disqualify lead due to invalid contact details",
            "style": "danger",
            "requires_fields": None
        },
        "NOT_INTERESTED": {
            "next_template_id": None,
            "label_ar": "🚫 غير مهتم بالطلب",
            "label_en": "🚫 Not Interested",
            "description_ar": "استبعاد الطلب وتحديث حالته إلى ملغى",
            "description_en": "Disqualify lead and archive inquiry",
            "style": "danger",
            "requires_fields": None
        },
        "BUSY": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "📵 الخط مشغول",
            "label_en": "📵 Line Busy",
            "description_ar": "جدولة إعادة محاولة الاتصال لاحقاً",
            "description_en": "Schedule retry call later",
            "style": "warning",
            "requires_fields": None
        },
        "QUALIFIED": {
            "next_template_id": "TASK_LEAD_QUALIFY",
            "label_ar": "⭐ تم التواصل وتأكيد الرغبة",
            "label_en": "⭐ Connected & Interested",
            "description_ar": "الانتقال مباشرة لمهمة استيفاء معايير التأهيل",
            "description_en": "Proceed to lead qualification criteria",
            "style": "success",
            "requires_fields": None
        },
        "DISQUALIFIED": {
            "next_template_id": None,
            "label_ar": "❌ استبعاد الطلب",
            "label_en": "❌ Disqualify Lead",
            "description_ar": "استبعاد الطلب نهائياً لعدم الأهلية أو رغبة العميل",
            "description_en": "Disqualify inquiry permanently",
            "style": "danger",
            "requires_fields": None
        },
        "UNREACHABLE": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "📵 تعذر الوصول للعميل",
            "label_en": "📵 Unreachable",
            "description_ar": "تسجيل محاولة الاتصال وتوليد مهمة متابعة",
            "description_en": "Record contact attempt and spawn follow-up task",
            "style": "warning",
            "requires_fields": None
        }
    },
    "TASK_RENT_LEAD_FIRST_CONTACT": {
        "CONNECTED": {
            "next_template_id": "TASK_LEAD_QUALIFY",
            "label_ar": "📞 تم التواصل بنجاح وتأكيد رغبة الإيجار",
            "label_en": "📞 Connected — Rental Confirmed",
            "description_ar": "ترقية حالة الطلب وتوليد مهمة تأهيل المستأجر",
            "description_en": "Promote lead and spawn tenant qualification task",
            "style": "success",
            "requires_fields": None
        },
        "NO_ANSWER": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "📵 لم يرد / تعذر الوصول",
            "label_en": "📵 No Answer / Busy",
            "description_ar": "جدولة متابعة هاتفية لاستكمال متطلبات الإيجار",
            "description_en": "Schedule follow-up to complete rental requirements",
            "style": "warning",
            "requires_fields": None
        },
        "CALLBACK_REQUESTED": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "⏰ طلب معاودة الاتصال لاحقاً",
            "label_en": "⏰ Callback Requested",
            "description_ar": "تحديد موعد وتوقيت إعادة الاتصال بالمستأجر",
            "description_en": "Specify date and time to call tenant back",
            "style": "warning",
            "requires_fields": "callback"
        },
        "NOT_INTERESTED": {
            "next_template_id": None,
            "label_ar": "🚫 غير مهتم بالاستئجار",
            "label_en": "🚫 Not Interested in Renting",
            "description_ar": "استبعاد طلب الإيجار وأرشفته",
            "description_en": "Disqualify and archive rental inquiry",
            "style": "danger",
            "requires_fields": None
        },
        "DISQUALIFIED": {
            "next_template_id": None,
            "label_ar": "❌ استبعاد لعدم مطابقة المعايير",
            "label_en": "❌ Disqualified Tenant",
            "description_ar": "إغلاق الطلب لعدم توافق ميزانية أو شروط الإيجار",
            "description_en": "Close inquiry due to unmatched rent budget or criteria",
            "style": "danger",
            "requires_fields": None
        },
        "BUSY": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "📵 الخط مشغول",
            "label_en": "📵 Line Busy",
            "description_ar": "جدولة إعادة الاتصال",
            "description_en": "Schedule retry call",
            "style": "warning",
            "requires_fields": None
        },
        "QUALIFIED": {
            "next_template_id": "TASK_LEAD_QUALIFY",
            "label_ar": "⭐ مؤهل للإيجار",
            "label_en": "⭐ Qualified Tenant",
            "description_ar": "استيفاء شروط التأهيل والانتقال للمطابقة",
            "description_en": "Advance to property matching",
            "style": "success",
            "requires_fields": None
        },
        "UNREACHABLE": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "📵 تعذر الوصول",
            "label_en": "📵 Unreachable",
            "description_ar": "جدولة متابعة لاحقة",
            "description_en": "Schedule follow-up",
            "style": "warning",
            "requires_fields": None
        }
    },
    "TASK_INVEST_LEAD_FIRST_CONTACT": {
        "CONNECTED": {
            "next_template_id": "TASK_INVEST_CONFIRM_OBJECTIVES",
            "label_ar": "📞 تم التواصل وتأكيد الرغبة الاستثمارية",
            "label_en": "📞 Connected — Investment Interest Confirmed",
            "description_ar": "ترقية الطلب لفرصة استثمارية وتوليد مهمة تأكيد الأهداف",
            "description_en": "Promote to investment deal and spawn objectives confirmation task",
            "style": "success",
            "requires_fields": None
        },
        "NO_ANSWER": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "📵 لم يرد المستثمر",
            "label_en": "📵 No Answer",
            "description_ar": "جدولة متابعة اتصال لاحقة مع المستثمر",
            "description_en": "Schedule follow-up call with investor",
            "style": "warning",
            "requires_fields": None
        },
        "CALLBACK_REQUESTED": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "⏰ طلب المستثمر معاودة الاتصال",
            "label_en": "⏰ Investor Callback Requested",
            "description_ar": "تحديد وقت مناسب للتحدث مع المستثمر",
            "description_en": "Set appointment to consult with investor",
            "style": "warning",
            "requires_fields": "callback"
        },
        "NOT_INTERESTED": {
            "next_template_id": None,
            "label_ar": "🚫 غير مهتم بالفرص الاستثمارية",
            "label_en": "🚫 Not Interested in Investment",
            "description_ar": "استبعاد الطلب الاستثماري وأرشفته",
            "description_en": "Archive investment inquiry",
            "style": "danger",
            "requires_fields": None
        },
        "DISQUALIFIED": {
            "next_template_id": None,
            "label_ar": "❌ استبعاد لعدم الملاءمة الاستثمارية",
            "label_en": "❌ Disqualified",
            "description_ar": "استبعاد الطلب لعدم توفر متطلبات الاستثمار",
            "description_en": "Disqualify investment lead",
            "style": "danger",
            "requires_fields": None
        },
        "BUSY": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "📵 الهاتف مشغول",
            "label_en": "📵 Busy",
            "description_ar": "إعادة المحاولة لاحقاً",
            "description_en": "Retry later",
            "style": "warning",
            "requires_fields": None
        },
        "QUALIFIED": {
            "next_template_id": "TASK_INVEST_CONFIRM_OBJECTIVES",
            "label_ar": "⭐ مستثمر مؤهل",
            "label_en": "⭐ Qualified Investor",
            "description_ar": "تأكيد جاهزية رأس المال والانتقال للأهداف الاستثمارية",
            "description_en": "Confirm capital readiness and proceed to investment objectives",
            "style": "success",
            "requires_fields": None
        },
        "UNREACHABLE": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "📵 تعذر الوصول",
            "label_en": "📵 Unreachable",
            "description_ar": "جدولة محاولة متابعة",
            "description_en": "Schedule follow-up attempt",
            "style": "warning",
            "requires_fields": None
        }
    },
    "TASK_LEAD_FOLLOWUP": {
        "CONNECTED": {
            "next_template_id": "TASK_LEAD_QUALIFY",
            "label_ar": "📞 نجاح التواصل في المتابعة",
            "label_en": "📞 Follow-up Connected",
            "description_ar": "التواصل بنجاح مع العميل وتوليد مهمة استيفاء التأهيل",
            "description_en": "Successfully contacted client and spawn qualification task",
            "style": "success",
            "requires_fields": None
        },
        "NO_ANSWER": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "📵 لم يرد (متابعة أخرى)",
            "label_en": "📵 No Answer (Retry)",
            "description_ar": "جدولة متابعة لاحقة حتى بلوغ الحد الأقصى للمحاولات",
            "description_en": "Schedule subsequent follow-up until max retries reached",
            "style": "warning",
            "requires_fields": None
        },
        "BUSY": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "📵 الخط مشغول",
            "label_en": "📵 Line Busy",
            "description_ar": "إعادة المحاولة في وقت لاحق",
            "description_en": "Retry later",
            "style": "warning",
            "requires_fields": None
        },
        "QUALIFIED": {
            "next_template_id": "TASK_LEAD_QUALIFY",
            "label_ar": "⭐ مؤهل وجاد",
            "label_en": "⭐ Qualified & Ready",
            "description_ar": "الانتقال فوراً لاستكمال بيانات التأهيل والترقية",
            "description_en": "Proceed to lead qualification and pipeline promotion",
            "style": "success",
            "requires_fields": None
        },
        "DISQUALIFIED": {
            "next_template_id": None,
            "label_ar": "❌ استبعاد الطلب",
            "label_en": "❌ Disqualify Lead",
            "description_ar": "إغلاق الطلب نهائياً لعدم رغبة العميل",
            "description_en": "Permanently close inquiry",
            "style": "danger",
            "requires_fields": None
        },
        "NOT_INTERESTED": {
            "next_template_id": None,
            "label_ar": "🚫 غير مهتم",
            "label_en": "🚫 Not Interested",
            "description_ar": "اعتذار العميل وإغلاق الطلب",
            "description_en": "Client declined, close inquiry",
            "style": "danger",
            "requires_fields": None
        },
        "UNREACHABLE": {
            "next_template_id": None,
            "label_ar": "📵 تعذر الوصول نهائياً (استبعاد تلقائي)",
            "label_en": "📵 Permanently Unreachable",
            "description_ar": "إغلاق الطلب كغير مستجيب بعد استنفاد محاولات الاتصال",
            "description_en": "Close inquiry as unreachable after exhausting attempts",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_LEAD_QUALIFY": {
        "QUALIFIED": {
            "next_template_id": "TASK_VIEWING_SCHEDULE",
            "label_ar": "⭐ استكمال التأهيل بنجاح وتحويل لصفقة",
            "label_en": "⭐ Lead Qualified & Converted",
            "description_ar": "استيفاء معايير التأهيل وترقية الطلب لصفقة نشطة وتوليد مهمة ترشيح العقارات أو المعاينة",
            "description_en": "Criteria met, promote lead to active opportunity and spawn property matching or viewing",
            "style": "success",
            "requires_fields": "qual"
        },
        "QUALIFIED_RENT": {
            "next_template_id": "TASK_RENT_MATCH_PROPERTIES",
            "label_ar": "🔑 مؤهل لطلب إيجار",
            "label_en": "🔑 Qualified for Rental",
            "description_ar": "تحويل لمسار الإيجار وتوليد مهمة ترشيح الوحدات السكنية/التجارية",
            "description_en": "Promote to rental pipeline and spawn unit matching",
            "style": "info",
            "requires_fields": "qual"
        },
        "QUALIFIED_INVESTMENT": {
            "next_template_id": "TASK_INVEST_CONFIRM_OBJECTIVES",
            "label_ar": "💼 مؤهل لفرصة استثمارية",
            "label_en": "💼 Qualified for Investment",
            "description_ar": "تحويل لمسار الاستثمار وتوليد مهمة تأكيد الأهداف والعوائد",
            "description_en": "Promote to investment pipeline and spawn objectives confirmation",
            "style": "primary",
            "requires_fields": "qual"
        },
        "FOLLOWUP_NEEDED": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "⏳ يحتاج متابعة إضافية",
            "label_en": "⏳ Needs Additional Follow-up",
            "description_ar": "جدولة اتصال متابعة جديد لاستكمال متطلبات وميزانية العميل",
            "description_en": "Schedule new follow-up call to verify budget and requirements",
            "style": "warning",
            "requires_fields": None
        },
        "NO_ANSWER": {
            "next_template_id": "TASK_LEAD_FOLLOWUP",
            "label_ar": "📵 تعذر الاتصال أثناء التأهيل",
            "label_en": "📵 No Answer during Qualification",
            "description_ar": "إعادة محاولة المتابعة لاستكمال التأهيل",
            "description_en": "Retry qualification call",
            "style": "warning",
            "requires_fields": None
        },
        "DISQUALIFIED": {
            "next_template_id": None,
            "label_ar": "❌ استبعاد الطلب لعدم الملاءمة",
            "label_en": "❌ Disqualified / Opportunity Lost",
            "description_ar": "استبعاد الطلب لعدم الجدية أو الملاءمة المالية أو انسحاب العميل",
            "description_en": "Disqualify lead due to lack of serious interest, financial mismatch or lost to competitor",
            "style": "danger",
            "requires_fields": None
        },
        "NOT_INTERESTED": {
            "next_template_id": None,
            "label_ar": "🚫 غير مهتم بالخيارات المتاحة",
            "label_en": "🚫 Not Interested",
            "description_ar": "أرشفة الطلب لعدم رغبة العميل بالشراء أو الإيجار",
            "description_en": "Archive inquiry as customer is not interested",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_LEAD_ASSIGN": {
        "SALES": {
            "next_template_id": "TASK_SALES_LEAD_CONTACT_QUALIFY",
            "label_ar": "👤 تم تعيين وسيط البيع",
            "label_en": "👤 Agent Assigned",
            "description_ar": "إتمام التعيين وتوليد مهمة الاتصال الأولي والتأهيل للوسيط بمهلة SLA قدرها 30 دقيقة",
            "description_en": "Complete assignment and spawn 30-min first contact & qualification SLA task",
            "style": "success",
            "requires_fields": "assign"
        },
        "ASSIGNED": {
            "next_template_id": "TASK_SALES_LEAD_CONTACT_QUALIFY",
            "label_ar": "👤 تم تعيين وسيط البيع",
            "label_en": "👤 Agent Assigned",
            "description_ar": "إتمام التعيين وتوليد مهمة الاتصال الأولي والتأهيل للوسيط بمهلة SLA قدرها 30 دقيقة",
            "description_en": "Complete assignment and spawn 30-min first contact & qualification SLA task",
            "style": "success",
            "requires_fields": "assign"
        },
        "RENT": {
            "next_template_id": "TASK_RENT_LEAD_FIRST_CONTACT",
            "label_ar": "🔑 تعيين لوسيط تأجير معتمد",
            "label_en": "🔑 Assign to Rental Agent",
            "description_ar": "إسناد المعاملة لمسؤول مسار الإيجارات بالفرع",
            "description_en": "Assign deal to rental specialist in branch",
            "style": "info",
            "requires_fields": "assign"
        },
        "INVESTMENT": {
            "next_template_id": "TASK_INVEST_LEAD_FIRST_CONTACT",
            "label_ar": "💼 تعيين لمستشار استثمار عقاري",
            "label_en": "💼 Assign to Investment Advisor",
            "description_ar": "إسناد المعاملة لمستشار الصفقات الاستثمارية",
            "description_en": "Assign deal to investment specialist",
            "style": "primary",
            "requires_fields": "assign"
        }
    },
    "TASK_OPPORTUNITY_MATCH_PROPERTIES": {
        "MATCHED": {
            "next_template_id": "TASK_VIEWING_SCHEDULE",
            "label_ar": "🏢 تم ترشيح الوحدات المطابقة وإرسالها للعميل",
            "label_en": "🏢 Properties Matched & Presented",
            "description_ar": "توثيق إرسال مقترحات العقارات وتوليد مهمة جدولة المعاينة الميدانية",
            "description_en": "Record sent property recommendations and spawn site visit scheduling task",
            "style": "success",
            "requires_fields": "match"
        },
        "NONE_FOUND": {
            "next_template_id": None,
            "label_ar": "🔍 لم يُعثر على وحدات مطابقة حالياً بالمخزون",
            "label_en": "🔍 No Matching Inventory Found",
            "description_ar": "وضع الطلب في قائمة الانتظار للمطابقة التلقائية مع الإدخالات الجديدة",
            "description_en": "Place deal on waitlist for auto-matching with new listings",
            "style": "warning",
            "requires_fields": None
        },
        "REVISE_CRITERIA": {
            "next_template_id": None,
            "label_ar": "🔄 تعديل شروط وميزانية البحث",
            "label_en": "🔄 Revise Search Criteria",
            "description_ar": "إعادة التواصل مع العميل لتوسيع نطاق الحي أو الميزانية",
            "description_en": "Coordinate with client to adjust location or budget criteria",
            "style": "info",
            "requires_fields": None
        }
    },
    "TASK_RENT_MATCH_PROPERTIES": {
        "MATCHED": {
            "next_template_id": "TASK_VIEWING_SCHEDULE",
            "label_ar": "🏢 تم ترشيح الوحدات الإيجارية وإرسالها للعميل",
            "label_en": "🏢 Rental Properties Matched & Sent",
            "description_ar": "عرض الوحدات الشاغرة وتوليد مهمة جدولة المعاينة الميدانية",
            "description_en": "Present available rental units and spawn site visit scheduling task",
            "style": "success",
            "requires_fields": "match"
        },
        "NONE_FOUND": {
            "next_template_id": None,
            "label_ar": "🔍 لا توجد وحدات إيجار شاغرة مطابقة حالياً",
            "label_en": "🔍 No Vacant Rental Units Found",
            "description_ar": "حفظ المتطلبات في قائمة الانتظار",
            "description_en": "Keep requirements on pending list",
            "style": "warning",
            "requires_fields": None
        }
    },
    "TASK_VIEWING_SCHEDULE": {
        "SCHEDULED": {
            "next_template_id": "TASK_VIEWING_REPORT",
            "label_ar": "👁️ تم الاتفاق وتأكيد موعد المعاينة الميدانية",
            "label_en": "👁️ Site Visit Scheduled & Confirmed",
            "description_ar": "تسجيل موعد المعاينة، وتوليد مهمة تقرير المعاينة وترقية الصفقة لـ (VIEWING)",
            "description_en": "Book site visit, advance deal to VIEWING, and generate viewing report task",
            "style": "success",
            "requires_fields": "viewing_schedule"
        },
        "RESCHEDULED": {
            "next_template_id": "TASK_VIEWING_RESCHEDULE",
            "label_ar": "⏳ تعذر التنسيق / إعادة الجدولة",
            "label_en": "⏳ Reschedule Needed",
            "description_ar": "جدولة موعد متابعة لاحق للتنسيق مع العميل والمالك",
            "description_en": "Schedule follow-up date to coordinate with buyer and owner",
            "style": "warning",
            "requires_fields": None
        },
        "CANCELLED": {
            "next_template_id": None,
            "label_ar": "🚫 إلغاء المعاينة من طرف العميل",
            "label_en": "🚫 Viewing Cancelled by Client",
            "description_ar": "إلغاء المعاينة وتوثيق أسباب الاعتذار",
            "description_en": "Cancel site visit and record reason",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_VIEWING_RESCHEDULE": {
        "SCHEDULED": {
            "next_template_id": "TASK_VIEWING_REPORT",
            "label_ar": "👁️ تم تأكيد الموعد البديل للمعاينة",
            "label_en": "👁️ Rescheduled Visit Confirmed",
            "description_ar": "حجز الموعد الجديد وتوليد مهمة تقرير الزيارة",
            "description_en": "Confirm new visit slot and spawn report task",
            "style": "success",
            "requires_fields": "viewing_schedule"
        },
        "CANCELLED": {
            "next_template_id": None,
            "label_ar": "🚫 إلغاء المعاينة نهائياً",
            "label_en": "🚫 Permanently Cancelled",
            "description_ar": "اعتذار العميل وإغلاق موعد الزيارة",
            "description_en": "Client cancelled visit",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_VIEWING_REPORT": {
        "INTERESTED": {
            "next_template_id": "TASK_OFFER_SUBMIT",
            "label_ar": "⭐ العميل مهتم ويرغب بتقديم عرض مالي",
            "label_en": "⭐ Interested — Ready to Submit Offer",
            "description_ar": "ترقية الصفقة لمرحلة التفاوض (NEGOTIATION) وتوليد مهمة تقديم العرض المالي بمهلة 12 ساعة وتثبيت قيمة السوم",
            "description_en": "Promote deal to NEGOTIATION and generate 12-hour offer submission task and lock offer amount",
            "style": "success",
            "requires_fields": "offer"
        },
        "NEEDS_ANOTHER_UNIT": {
            "next_template_id": "TASK_VIEWING_SCHEDULE",
            "label_ar": "🔄 العقار لم يناسبه ويرغب بمعاينة وحدة بديلة",
            "label_en": "🔄 Needs Alternative Unit",
            "description_ar": "بقاء الصفقة في مرحلة المعاينة وتوليد مهمة جدولة معاينة جديدة لوحدة بديلة",
            "description_en": "Keep deal in viewing stage and spawn new viewing schedule task for alternative unit",
            "style": "info",
            "requires_fields": None
        },
        "REQUESTS_ANOTHER_VIEWING": {
            "next_template_id": "TASK_VIEWING_SCHEDULE",
            "label_ar": "👁️ يرغب بزيارة إضافية للمعاينة",
            "label_en": "👁️ Requests Additional Viewing",
            "description_ar": "جدولة زيارة ثانية لنفس العقار بصحبة العائلة أو مستشار",
            "description_en": "Schedule follow-up viewing appointment for the same property",
            "style": "info",
            "requires_fields": None
        },
        "NOT_INTERESTED": {
            "next_template_id": None,
            "label_ar": "🚫 لم يعجب العقار العميل (صرف النظر)",
            "label_en": "🚫 Not Interested in Property",
            "description_ar": "تسجيل أسباب عدم الإعجاب وتحديث نتيجة الزيارة",
            "description_en": "Record rejection reasons and update visit logs",
            "style": "danger",
            "requires_fields": None
        },
        "NO_SHOW": {
            "next_template_id": "TASK_VIEWING_RESCHEDULE",
            "label_ar": "❌ لم يحضر العميل للموعد (No Show)",
            "label_en": "❌ Client No-Show",
            "description_ar": "توثيق عدم الحضور وتوليد مهمة متابعة لإعادة الجدولة لمرة واحدة",
            "description_en": "Log no-show and generate follow-up task to reschedule once",
            "style": "warning",
            "requires_fields": None
        },
        "CANCELLED": {
            "next_template_id": None,
            "label_ar": "🚫 اعتذار وإلغاء الزيارة",
            "label_en": "🚫 Visit Cancelled",
            "description_ar": "إلغاء المعاينة",
            "description_en": "Cancel viewing appointment",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_RENT_VIEWING_FOLLOW_UP": {
        "INTERESTED": {
            "next_template_id": "TASK_RENT_PREPARE_TENANCY",
            "label_ar": "⭐ رغبة المستأجر في استئجار الوحدة",
            "label_en": "⭐ Ready to Rent Unit",
            "description_ar": "الانتقال لمرحلة صياغة وإبرام عقد الإيجار الرسمي",
            "description_en": "Proceed to rental agreement drafting and execution",
            "style": "success",
            "requires_fields": None
        },
        "NEEDS_ANOTHER_UNIT": {
            "next_template_id": "TASK_RENT_MATCH_PROPERTIES",
            "label_ar": "🔄 يرغب بعرض وحدات إيجارية بديلة",
            "label_en": "🔄 Needs Alternative Rental Unit",
            "description_ar": "العودة لقائمة الوحدات الشاغرة لترشيح بديل",
            "description_en": "Return to available inventory to match alternative unit",
            "style": "info",
            "requires_fields": None
        },
        "REQUESTS_ANOTHER_VIEWING": {
            "next_template_id": "TASK_RENT_VIEWING_SCHEDULE",
            "label_ar": "👁️ طلب زيارة إضافية للمستأجر",
            "label_en": "👁️ Requests Additional Viewing",
            "description_ar": "جدولة زيارة إضافية للمستأجر بصحبة مرافق أو مستشار",
            "description_en": "Schedule another viewing appointment for tenant",
            "style": "info",
            "requires_fields": None
        },
        "NOT_INTERESTED": {
            "next_template_id": None,
            "label_ar": "🚫 صرف النظر عن الاستئجار",
            "label_en": "🚫 Not Interested in Renting",
            "description_ar": "إغلاق المعاملة",
            "description_en": "Close rental transaction",
            "style": "danger",
            "requires_fields": None
        },
        "NO_SHOW": {
            "next_template_id": "TASK_VIEWING_RESCHEDULE",
            "label_ar": "❌ تعذر حضور المستأجر للمعاينة",
            "label_en": "❌ Tenant No-Show",
            "description_ar": "جدولة موعد بديل",
            "description_en": "Schedule alternative slot",
            "style": "warning",
            "requires_fields": None
        }
    },
    "TASK_OFFER_PREPARE": {
        "SUBMITTED": {
            "next_template_id": "TASK_OFFER_FOLLOWUP",
            "label_ar": "📤 تقديم العرض مباشرة للمالك",
            "label_en": "📤 Submit Directly to Owner",
            "description_ar": "العرض ضمن الصلاحية وتوليد مهمة متابعة قرار المالك",
            "description_en": "Offer within authority limits, spawn owner follow-up task",
            "style": "success",
            "requires_fields": None
        },
        "REQUIRES_APPROVAL": {
            "next_template_id": "TASK_OFFER_MANAGER_APPROVAL",
            "label_ar": "⚠️ يتطلب موافقة مدير الفرع (خصم سعري كبير)",
            "label_en": "⚠️ Requires Manager Approval",
            "description_ar": "العرض يقل عن السعر المستهدف بأكثر من 5% ويحتاج موافقة إدارية",
            "description_en": "Discount exceeds threshold, escalates to branch manager approval",
            "style": "warning",
            "requires_fields": None
        }
    },
    "TASK_OFFER_SUBMIT": {
        "SUBMITTED": {
            "next_template_id": "TASK_OFFER_FOLLOWUP",
            "label_ar": "📤 تم تسليم العرض المالي للمالك وتوثيقه",
            "label_en": "📤 Offer Submitted to Property Owner",
            "description_ar": "إرسال العرض وتوليد مهمة متابعة استلام الرد بمهلة 24 ساعة",
            "description_en": "Send offer and spawn 24-hour owner decision follow-up task",
            "style": "success",
            "requires_fields": None
        },
        "REQUIRES_APPROVAL": {
            "next_template_id": "TASK_OFFER_MANAGER_APPROVAL",
            "label_ar": "⚠️ العرض مشروط بتسهيلات تتطلب اعتماد المدير",
            "label_en": "⚠️ Conditional Offer Needs Approval",
            "description_ar": "تصعيد العرض لمراجعة المدير لاعتماد الشروط الاستثنائية",
            "description_en": "Escalate to manager to approve special terms",
            "style": "warning",
            "requires_fields": None
        }
    },
    "TASK_OFFER_MANAGER_APPROVAL": {
        "APPROVED": {
            "next_template_id": "TASK_OFFER_FOLLOWUP",
            "label_ar": "✅ اعتماد العرض من المدير وتقديمه للمالك",
            "label_en": "✅ Approved by Manager & Submitted",
            "description_ar": "الموافقة على شروط العرض وتوليد مهمة متابعة قرار المالك",
            "description_en": "Manager approved terms, spawn owner response follow-up",
            "style": "success",
            "requires_fields": None
        },
        "REJECTED": {
            "next_template_id": "TASK_OFFER_PREPARE",
            "label_ar": "❌ رفض العرض وإعادته للتعديل",
            "label_en": "❌ Rejected by Manager — Revise",
            "description_ar": "رفض التسهيلات وإعادة العرض للوسيط لرفع السعر المقدم",
            "description_en": "Reject concessions and return to agent to revise price",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_OFFER_FOLLOWUP": {
        "OFFER_ACCEPTED": {
            "next_template_id": "TASK_RESERVATION_VERIFY_AVAILABILITY",
            "label_ar": "🎉 قبول المالك للعرض وتثبيت الاتفاق",
            "label_en": "🎉 Offer Accepted by Owner",
            "description_ar": "ترقية الصفقة لمرحلة الحجز (RESERVATION) وتوليد مهمة التحقق من جاهزية الوحدة وسداد العربون",
            "description_en": "Advance deal to RESERVATION and spawn unit availability verification and deposit task",
            "style": "success",
            "requires_fields": None
        },
        "COUNTER_OFFER": {
            "next_template_id": "TASK_SALE_NEGOTIATE_CONCESSIONS",
            "label_ar": "⚖️ تفاوض وعرض مالي مضاد من المالك",
            "label_en": "⚖️ Owner Counter Offer Received",
            "description_ar": "استلام عرض مضاد وتوليد مهمة التفاوض على التخفيض وشروط السداد مع المشتري",
            "description_en": "Counter offer received, spawn concessions and terms negotiation task with buyer",
            "style": "warning",
            "requires_fields": None
        },
        "REJECTED": {
            "next_template_id": "TASK_OPPORTUNITY_MATCH_PROPERTIES",
            "label_ar": "❌ رفض المالك للعرض أو انتهاء مهلته",
            "label_en": "❌ Offer Rejected or Expired",
            "description_ar": "إغلاق المفاوضات على هذه الوحدة والعودة لمطابقة وترشيح عقارات بديلة للعميل",
            "description_en": "Close negotiations on this property and return to matching alternative units",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_SALE_NEGOTIATE_CONCESSIONS": {
        "CONCESSION_AGREED": {
            "next_template_id": "TASK_RESERVATION_VERIFY_AVAILABILITY",
            "label_ar": "🤝 التوصل لاتفاق نهائي وسعر توافقي",
            "label_en": "🤝 Concessions Mutually Agreed",
            "description_ar": "موافقة الطرفين على التنازلات وترقية الصفقة لمرحلة الحجز والعربون",
            "description_en": "Both parties agreed on terms, proceed to unit reservation and deposit",
            "style": "success",
            "requires_fields": None
        },
        "COUNTER_PREPARED": {
            "next_template_id": "TASK_OFFER_PREPARE",
            "label_ar": "📝 إعداد مسودة عرض مالي محدث بالاتفاق الجديد",
            "label_en": "📝 Prepare Updated Offer Draft",
            "description_ar": "توثيق التعديل السعري في عرض رسمي جديد",
            "description_en": "Document price adjustment in a new formal offer",
            "style": "info",
            "requires_fields": None
        },
        "FAILED": {
            "next_template_id": "TASK_OPPORTUNITY_MATCH_PROPERTIES",
            "label_ar": "❌ تعثر التفاوض والعودة لوحدات بديلة",
            "label_en": "❌ Negotiation Failed — Match Alternatives",
            "description_ar": "إنهاء المفاوضات والبحث عن خيارات أخرى للعميل",
            "description_en": "End talks and find other property options for buyer",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_RESERVATION_VERIFY_AVAILABILITY": {
        "AVAILABLE": {
            "next_template_id": "TASK_RESERVATION_DEPOSIT_FOLLOWUP",
            "label_ar": "🟢 الوحدة شاغرة ومتاحة للحجز الفوري",
            "label_en": "🟢 Unit Available for Immediate Reservation",
            "description_ar": "تثبيت حجز الوحدة بالمخزون كـ (RESERVED) وتوليد مهمة سداد وتدقيق العربون بمهلة 48 ساعة",
            "description_en": "Lock unit in inventory as RESERVED and spawn 48h deposit verification task",
            "style": "success",
            "requires_fields": None
        },
        "UNAVAILABLE": {
            "next_template_id": "TASK_OPPORTUNITY_MATCH_PROPERTIES",
            "label_ar": "🔴 الوحدة محجوزة أو مباعة لطرف آخر",
            "label_en": "🔴 Unit Unavailable / Already Sold",
            "description_ar": "تعذر الحجز والعودة لمطابقة وترشيح عقار بديل",
            "description_en": "Unit unavailable, return to matching alternatives",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_RESERVATION_DEPOSIT_FOLLOWUP": {
        "DEPOSIT_VERIFIED": {
            "next_template_id": "TASK_CONTRACT_DRAFT",
            "label_ar": "💰 سداد وتوثيق العربون بالحساب البنكي",
            "label_en": "💰 Earnest Money Deposit Verified",
            "description_ar": "إصدار سند القبض الرسمي، وتثبيت حجز الوحدة، وتوليد مهمة صياغة مسودة العقد",
            "description_en": "Issue official receipt, lock unit reservation, and spawn contract drafting task",
            "style": "success",
            "requires_fields": None
        },
        "EXPIRED": {
            "next_template_id": "TASK_RESERVATION_EXPIRY_REVIEW",
            "label_ar": "⏰ انتهاء مهلة العربون (48 ساعة)",
            "label_en": "⏰ Deposit Deadline Expired (48h)",
            "description_ar": "توليد مهمة مراجعة انتهاء الحجز واتخاذ قرار التمديد أو فك القفل",
            "description_en": "Spawn expiry review task to extend or release unit back to stock",
            "style": "warning",
            "requires_fields": None
        },
        "CANCELLED": {
            "next_template_id": None,
            "label_ar": "🚫 إلغاء الحجز من طرف العميل",
            "label_en": "🚫 Reservation Cancelled by Client",
            "description_ar": "فك حجز الوحدة وإعادتها لمتاح (AVAILABLE)",
            "description_en": "Release unit back to AVAILABLE stock",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_RESERVATION_EXPIRY_REVIEW": {
        "EXTENDED": {
            "next_template_id": "TASK_RESERVATION_DEPOSIT_FOLLOWUP",
            "label_ar": "⏳ تمديد مهلة الحجز 24 ساعة إضافية",
            "label_en": "⏳ Extend Reservation 24h",
            "description_ar": "منح العميل مهلة إضافية بناءً على مبرر مقبول وتوليد مهمة متابعة",
            "description_en": "Grant 24h extension and spawn deposit follow-up",
            "style": "warning",
            "requires_fields": None
        },
        "RELEASED": {
            "next_template_id": None,
            "label_ar": "🔴 فك الحجز وإعادة إتاحة الوحدة في المخزون",
            "label_en": "🔴 Release Unit to Available Stock",
            "description_ar": "إلغاء الحجز تلقائياً وإتاحة الوحدة للمشترين الآخرين",
            "description_en": "Cancel reservation and make unit AVAILABLE immediately",
            "style": "danger",
            "requires_fields": None
        },
        "CANCELLED": {
            "next_template_id": None,
            "label_ar": "🚫 إنهاء المعاملة وأرشفة الحجز",
            "label_en": "🚫 Cancel & Archive Deal",
            "description_ar": "إغلاق الحجز المنتهي وإلغاء المعاملة",
            "description_en": "Close expired reservation and cancel deal",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_CONTRACT_DRAFT": {
        "SUBMITTED": {
            "next_template_id": "TASK_CONTRACT_INTERNAL_REVIEW",
            "label_ar": "📤 إرسال المسودة للمراجعة القانونية والاعتماد",
            "label_en": "📤 Submit Draft for Legal Review",
            "description_ar": "إحالة مسودة العقد المكتملة للإدارة القانونية للتدقيق والاعتماد الداخلي",
            "description_en": "Refer completed contract draft to legal department for review and internal approval",
            "style": "success",
            "requires_fields": None
        }
    },
    "TASK_CONTRACT_INTERNAL_REVIEW": {
        "APPROVED": {
            "next_template_id": "TASK_CONTRACT_SIGNATURE",
            "label_ar": "✅ اعتماد مسودة العقد للمطابقة والتوقيع",
            "label_en": "✅ Contract Approved for Signature",
            "description_ar": "اعتماد المسودة وتوليد مهمة توقيع العقد من كافة الأطراف عبر شبكة إيجار أو إلكترونياً",
            "description_en": "Contract approved, spawn task for party signatures via Ejar or e-signature",
            "style": "success",
            "requires_fields": None
        },
        "REVISIONS_NEEDED": {
            "next_template_id": "TASK_CONTRACT_DRAFT",
            "label_ar": "📝 طلب تعديلات قانونية إضافية",
            "label_en": "📝 Legal Amendments Requested",
            "description_ar": "إعادة المسودة للتعديل وفق ملاحظات التدقيق القانوني والشؤون التعاقدية",
            "description_en": "Return draft to drafter to incorporate legal counsel revisions",
            "style": "warning",
            "requires_fields": None
        }
    },
    "TASK_CONTRACT_SIGNATURE": {
        "SIGNED": {
            "next_template_id": "TASK_CONTRACT_HANDOVER",
            "label_ar": "✍️ اكتمال توقيع وتوثيق العقد من كافة الأطراف",
            "label_en": "✍️ Contract Signed & Documented by All Parties",
            "description_ar": "ترقية الصفقة إلى (WON) وتوليد مهمة تسليم الوحدة وإصدار فواتير الرسوم والعمولة",
            "description_en": "Advance deal to WON, generate unit handover task and issue fee invoices",
            "style": "success",
            "requires_fields": None
        }
    },
    "TASK_RENT_PREPARE_TENANCY": {
        "AGREEMENT_EXECUTED": {
            "next_template_id": "TASK_RENT_COLLECTION_MONITORING",
            "label_ar": "📑 اكتمال إبرام وتوثيق عقد الإيجار الرسمي",
            "label_en": "📑 Ejar Tenancy Agreement Executed",
            "description_ar": "توثيق وتفعيل العقد في شبكة إيجار وتوليد مهمة متابعة تحصيل الإيجارات والدفعات",
            "description_en": "Register and activate tenancy in Ejar network and spawn periodic rent collection monitoring",
            "style": "success",
            "requires_fields": None
        },
        "TERMS_REJECTED": {
            "next_template_id": "TASK_RENT_MATCH_PROPERTIES",
            "label_ar": "🚫 تعذر الاتفاق على بنود العقد وصرف النظر",
            "label_en": "🚫 Tenancy Terms Rejected",
            "description_ar": "إلغاء المعاملة الإيجارية الحالية والعودة لترشيح وحدات بديلة للعميل",
            "description_en": "Cancel current tenancy deal and return to matching alternative rental units",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_INVEST_INSPECTION_REPORT": {
        "RECOMMENDED": {
            "next_template_id": "TASK_INVEST_VALIDATE_FINANCIALS",
            "label_ar": "⭐ توصية بقبول العقار الاستثماري وسلامة الفحص",
            "label_en": "⭐ Asset Recommended for Investment",
            "description_ar": "اجتياز الفحص الفني (Due Diligence) بنجاح وتوليد مهمة تدقيق التدفقات والافتراضات المالية",
            "description_en": "Technical due diligence passed successfully, spawn financial valuation validation task",
            "style": "success",
            "requires_fields": None
        },
        "NOT_RECOMMENDED": {
            "next_template_id": "TASK_INVEST_COMPARE_RETURNS",
            "label_ar": "❌ عدم التوصية بالعقار (عيوب فنية جوهرية)",
            "label_en": "❌ Not Recommended (Major Technical Deficiencies)",
            "description_ar": "صرف النظر عن الأصل لعدم الجدوى الفنية والعودة لمقارنة عوائد وحدات بديلة",
            "description_en": "Decline asset due to critical physical defects, return to comparing alternative investments",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_INVEST_VALIDATE_FINANCIALS": {
        "VALIDATED": {
            "next_template_id": "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
            "label_ar": "📈 اعتماد صحة التدفقات النقدية والتقييم المالي",
            "label_en": "📈 Financial Cash Flows & Valuation Validated",
            "description_ar": "العوائد الاستثمارية ومعدل الرسملة (Cap Rate) تحقق المستهدف، والانتقال لإعداد عرض الاستحواذ",
            "description_en": "Target yield and Cap Rate achieved, proceed to acquisition offer preparation task",
            "style": "success",
            "requires_fields": None
        },
        "DISCOUNT_REQUIRED": {
            "next_template_id": "TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT",
            "label_ar": "⚠️ يتطلب تعديلاً سعرياً وتفاوضاً على خصم عيوب الفحص (CapEx)",
            "label_en": "⚠️ Price Discount Required (CapEx Defects)",
            "description_ar": "توليد مهمة التفاوض على خصم تكاليف الصيانة لتحقيق العائد المستهدف للمستثمر",
            "description_en": "Spawn price discount negotiation task to protect investor ROI",
            "style": "warning",
            "requires_fields": None
        },
        "REJECTED": {
            "next_template_id": "TASK_INVEST_COMPARE_RETURNS",
            "label_ar": "❌ العائد الاستثماري دون الحد الأدنى المقبول",
            "label_en": "❌ Yield Below Hurdle Rate",
            "description_ar": "صرف النظر والعودة لمقارنة عوائد وحدات استثمارية أخرى",
            "description_en": "Asset rejected, return to compare alternative investment units",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_INVEST_NEGOTIATE_PRICE_DISCOUNT": {
        "DISCOUNT_ACCEPTED": {
            "next_template_id": "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
            "label_ar": "🟢 موافقة البائع على الخصم كاملاً",
            "label_en": "🟢 Seller Accepted Full Discount",
            "description_ar": "تعديل سعر الشراء ليطابق تكلفة الـ CapEx والانتقال لعرض الاستحواذ",
            "description_en": "Purchase price adjusted for CapEx, proceed to acquisition offer",
            "style": "success",
            "requires_fields": None
        },
        "COMPROMISE_AGREED": {
            "next_template_id": "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
            "label_ar": "🟡 التوصل لتسوية وسطية واتفاق على تخفيض جزئي",
            "label_en": "🟡 Compromise Discount Agreed",
            "description_ar": "اعتماد السعر التوافقي والانتقال لتجهيز عرض الاستحواذ للمستثمر",
            "description_en": "Approve compromise price and prepare acquisition offer",
            "style": "warning",
            "requires_fields": None
        },
        "DISCOUNT_REJECTED": {
            "next_template_id": "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
            "label_ar": "🔴 رفض البائع للخصم والتمسك بسعره الأصلي",
            "label_en": "🔴 Seller Rejected Discount",
            "description_ar": "المضي قدماً بالسعر الأصلي وعرض القرار النهائي للمستثمر",
            "description_en": "Proceed at original price, investor to decide",
            "style": "warning",
            "requires_fields": None
        },
        "NEGOTIATION_FAILED": {
            "next_template_id": "TASK_INVEST_COMPARE_RETURNS",
            "label_ar": "❌ فشل التفاوض وصرف النظر عن الأصل",
            "label_en": "❌ Negotiation Failed — Exit Asset",
            "description_ar": "العودة لمقارنة وحدات استثمارية بديلة",
            "description_en": "Return to compare alternative investment units",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_INVEST_PREPARE_ACQUISITION_OFFER": {
        "OFFER_ACCEPTED": {
            "next_template_id": "TASK_INVEST_BASELINE_PERFORMANCE",
            "label_ar": "🤝 قبول البائع لعرض الاستحواذ وتثبيت الصفقة",
            "label_en": "🤝 Acquisition Offer Formally Accepted",
            "description_ar": "إتمام الاستحواذ بنجاح (WON) وتوليد مهمة تأسيس خط الأساس لأداء الاستثمار",
            "description_en": "Acquisition finalized successfully (WON), spawn investment performance baseline establishment task",
            "style": "success",
            "requires_fields": None
        },
        "OFFER_COMPROMISE": {
            "next_template_id": "TASK_INVEST_BASELINE_PERFORMANCE",
            "label_ar": "🤝 قبول العرض بشروط سداد معدلة",
            "label_en": "🤝 Accepted with Adjusted Terms",
            "description_ar": "اعتماد الصفقة وبدء خط الأساس",
            "description_en": "Approve deal and establish baseline",
            "style": "success",
            "requires_fields": None
        },
        "OFFER_REJECTED": {
            "next_template_id": "TASK_INVEST_COMPARE_RETURNS",
            "label_ar": "❌ رفض البائع لعرض الاستحواذ نهائياً",
            "label_en": "❌ Acquisition Offer Rejected",
            "description_ar": "تعذر التوصل لاتفاق استحواذ وإغلاق المعاملة والعودة للبحث عن فرص استثمارية بديلة",
            "description_en": "Acquisition offer rejected, close transaction and return to comparing alternatives",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_INVEST_COMPARE_RETURNS": {
        "RETURNS_COMPARED": {
            "next_template_id": "TASK_INVEST_SCHEDULE_INSPECTION",
            "label_ar": "📊 تم اختيار العقار الأفضل وتأكيد جدولة الفحص الفني",
            "label_en": "📊 Best Asset Selected — Schedule Inspection",
            "description_ar": "اعتماد الوحدة الأعلى عائداً وتوليد مهمة جدولة الفحص الفني الميداني (Due Diligence)",
            "description_en": "Select top performing unit and spawn site inspection task",
            "style": "success",
            "requires_fields": None
        },
        "PROCEED_TO_OFFER": {
            "next_template_id": "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
            "label_ar": "⚡ الانتقال المباشر لتقديم عرض الاستحواذ (مسار سريع)",
            "label_en": "⚡ Fast-Track: Proceed Directly to Acquisition Offer",
            "description_ar": "تجاوز الفحص الفني بناءً على طلب المستثمر وتوليد مهمة تجهيز عرض الاستحواذ فوراً",
            "description_en": "Waive inspection per investor request and immediately spawn acquisition offer task",
            "style": "primary",
            "requires_fields": None
        },
        "NO_SUITABLE_UNITS": {
            "next_template_id": None,
            "label_ar": "🔍 لا توجد أصول تحقق معدل العائد المطلوب (Hurdle Rate)",
            "label_en": "🔍 No Units Meet Target Hurdle Rate",
            "description_ar": "حفظ المتطلبات للبحث المستقبلي",
            "description_en": "Keep deal pending until suitable high-yield asset is sourced",
            "style": "warning",
            "requires_fields": None
        }
    },
    "TASK_INVEST_PORTFOLIO_REVIEW": {
        "HOLD": {
            "next_template_id": "TASK_INVEST_MONITOR_ACTUAL_RETURNS",
            "label_ar": "📈 استمرار الاحتفاظ بالأصل (Hold Strategy)",
            "label_en": "📈 Hold Strategy Confirmed",
            "description_ar": "الأداء المالي يطابق مستهدف خط الأساس، وتوليد مهمة مراقبة وتدقيق العوائد الدورية",
            "description_en": "Financial returns meet baseline target, spawn periodic operating returns monitoring task",
            "style": "success",
            "requires_fields": None
        },
        "EXIT": {
            "next_template_id": None,
            "label_ar": "💰 التوصية بالتخارج وإعادة توظيف رأس المال (Strategic Exit)",
            "label_en": "💰 Strategic Exit & Capital Recycling Recommended",
            "description_ar": "تحقيق الأفق الزمني المستهدف وتوصية ببيع الأصل لتحقيق الأرباح الرأسمالية",
            "description_en": "Target investment horizon reached, recommend selling asset to capture capital gains",
            "style": "primary",
            "requires_fields": None
        }
    },
    "TASK_INVEST_SCHEDULE_INSPECTION": {
        "SCHEDULED": {
            "next_template_id": "TASK_INVEST_INSPECTION_REPORT",
            "label_ar": "👁️ تأكيد موعد الفحص الفني والاستثماري",
            "label_en": "👁️ Inspection Scheduled & Confirmed",
            "description_ar": "تنسيق موعد زيارة الفحص الفني للوحدة وتوليد مهمة تقرير الفحص",
            "description_en": "Book technical inspection visit and spawn due diligence report task",
            "style": "success",
            "requires_fields": "viewing_schedule"
        },
        "CANCELLED": {
            "next_template_id": None,
            "label_ar": "🚫 إلغاء المعاينة من طرف المستثمر",
            "label_en": "🚫 Inspection Cancelled",
            "description_ar": "إلغاء المعاينة وأرشفة الموعد",
            "description_en": "Cancel inspection appointment",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_RESERVATION_DOCUMENTS": {
        "COMPLETED": {
            "next_template_id": "TASK_CONTRACT_DRAFT",
            "label_ar": "📁 استكمال وتدقيق كافة المستندات الإلزامية",
            "label_en": "📁 Mandatory Documents Verified",
            "description_ar": "توثيق الهوية والسجل التجاري وصك الملكية والانتقال لصياغة العقد",
            "description_en": "ID, CR, and title deed verified; proceed to contract drafting",
            "style": "success",
            "requires_fields": None
        }
    },
    "TASK_RENT_SPECIAL_CONDITIONS_NEGOTIATION": {
        "CONDITIONS_AGREED": {
            "next_template_id": "TASK_RENT_PREPARE_TENANCY",
            "label_ar": "🤝 التوصل لاتفاق على الشروط وفترات السماح",
            "label_en": "🤝 Special Terms & Grace Period Agreed",
            "description_ar": "اعتماد بنود عقد الإيجار والانتقال لإبرامه رسمياً",
            "description_en": "Approve terms and proceed to tenancy contract signing",
            "style": "success",
            "requires_fields": None
        },
        "REJECTED": {
            "next_template_id": "TASK_RENT_MATCH_PROPERTIES",
            "label_ar": "❌ رفض الشروط الاستثنائية",
            "label_en": "❌ Special Terms Rejected",
            "description_ar": "تعذر التوافق والعودة لترشيح وحدات أخرى",
            "description_en": "Terms rejected, search for alternative units",
            "style": "danger",
            "requires_fields": None
        }
    },
    "TASK_RENT_SECURITY_DEPOSIT_RECEIPT": {
        "RECEIVED": {
            "next_template_id": "TASK_RENT_COLLECTION_MONITORING",
            "label_ar": "💵 استلام وتوثيق مبلغ تأمين الأضرار والضمان",
            "label_en": "💵 Security Deposit Received & Documented",
            "description_ar": "إيداع مبلغ الضمان في حساب الأمانات وتوليد مهمة متابعة الإيجار",
            "description_en": "Deposit held in escrow and spawn rent collection monitoring",
            "style": "success",
            "requires_fields": None
        }
    }
}

# Documentation outcomes for ACTIVITY templates (Audit logs)
RICH_ACTIVITY_OUTCOMES = {
    "ACT_LEAD_FIRST_CONTACT": {
        "CONNECTED": {"label_ar": "📞 تم الاتصال بالعميل بنجاح", "label_en": "📞 Successfully Connected", "style": "success"},
        "NO_ANSWER": {"label_ar": "📵 لم يرد العميل على المكالمة", "label_en": "📵 Client Did Not Answer", "style": "warning"},
        "CALLBACK_REQUESTED": {"label_ar": "⏰ طلب العميل معاودة الاتصال", "label_en": "⏰ Callback Requested", "style": "info"},
        "INVALID_CONTACT": {"label_ar": "📵 رقم الهاتف غير صحيح", "label_en": "📵 Invalid Contact Number", "style": "danger"}
    },
    "ACT_LEAD_ASSIGNED": {
        "ASSIGNED": {"label_ar": "👤 تم توجيه وتعيين الوسيط المسؤول", "label_en": "👤 Agent Assigned", "style": "success"}
    },
    "ACT_LEAD_QUALIFIED": {
        "QUALIFIED": {"label_ar": "⭐ تم استيفاء معايير التأهيل بنجاح", "label_en": "⭐ Lead Successfully Qualified", "style": "success"},
        "DISQUALIFIED": {"label_ar": "❌ تم استبعاد الطلب لعدم الجدية", "label_en": "❌ Lead Disqualified", "style": "danger"}
    },
    "ACT_LEAD_FOLLOWUP": {
        "FOLLOWUP_COMPLETED": {"label_ar": "📞 تم إنجاز مكالمة المتابعة", "label_en": "📞 Follow-up Call Completed", "style": "success"},
        "NO_ANSWER": {"label_ar": "📵 تعذر التواصل في المتابعة", "label_en": "📵 Follow-up Unanswered", "style": "warning"}
    },
    "ACT_VIEWING_SCHEDULED": {
        "SCHEDULED": {"label_ar": "👁️ تم تحديد موعد المعاينة الميدانية", "label_en": "👁️ Site Visit Scheduled", "style": "success"},
        "CANCELLED": {"label_ar": "🚫 تم إلغاء موعد المعاينة", "label_en": "🚫 Visit Cancelled", "style": "danger"}
    },
    "ACT_VIEWING_REPORT_SUBMITTED": {
        "INTERESTED": {"label_ar": "⭐ العميل مهتم ويرغب بتقديم عرض", "label_en": "⭐ Client Interested & Ready for Offer", "style": "success"},
        "NEEDS_ANOTHER_UNIT": {"label_ar": "🔄 رغبة العميل في معاينة عقار بديل", "label_en": "🔄 Needs Alternative Property", "style": "info"},
        "NOT_INTERESTED": {"label_ar": "🚫 العميل غير مهتم بالعقار", "label_en": "🚫 Client Not Interested", "style": "danger"}
    },
    "ACT_OFFER_SUBMITTED": {
        "SUBMITTED": {"label_ar": "📤 تم تسليم العرض المالي للمالك", "label_en": "📤 Commercial Offer Submitted", "style": "success"}
    },
    "ACT_OFFER_DECISION": {
        "ACCEPTED": {"label_ar": "🎉 قبول العرض المالي من المالك", "label_en": "🎉 Offer Accepted by Owner", "style": "success"},
        "COUNTERED": {"label_ar": "⚖️ تقديم عرض مضاد من المالك", "label_en": "⚖️ Counter Offer Received", "style": "warning"},
        "REJECTED": {"label_ar": "❌ رفض العرض المالي من المالك", "label_en": "❌ Offer Rejected by Owner", "style": "danger"}
    },
    "ACT_RESERVATION_CONFIRMED": {
        "CONFIRMED": {"label_ar": "🔒 تم تثبيت حجز الوحدة بالمخزون", "label_en": "🔒 Unit Reservation Secured", "style": "success"}
    },
    "ACT_CONTRACT_DRAFT_CREATED": {
        "DRAFTED": {"label_ar": "📄 تم إعداد مسودة العقد الرسمي", "label_en": "📄 Contract Draft Created", "style": "success"}
    },
    "ACT_CONTRACT_SIGNED": {
        "SIGNED": {"label_ar": "✍️ تم توقيع العقد رسمياً من الأطراف", "label_en": "✍️ Contract Formally Signed", "style": "success"}
    },
    "ACT_INVOICE_GENERATED": {
        "INVOICE_ISSUED": {"label_ar": "🧾 تم إصدار الفاتورة الضريبية الرسمية", "label_en": "🧾 Tax Invoice Issued", "style": "success"}
    },
    "ACT_FEE_COLLECTED": {
        "FEES_COLLECTED": {"label_ar": "💳 تم تحصيل وتدقيق الرسوم والسعي", "label_en": "💳 Statutory Fees & Commission Collected", "style": "success"}
    },
    "ACT_TASK_CANCELLED": {
        "RELEASED": {"label_ar": "🔓 تم فك حجز الوحدة وإعادتها للمخزون المتاح", "label_en": "🔓 Unit Released Back to Available Inventory", "style": "warning"}
    },
    "ACT_TASK_REOPENED": {
        "REOPENED": {"label_ar": "🔄 تم إعادة فتح المهمة لإعادة المعالجة", "label_en": "🔄 Task Reopened for Processing", "style": "info"}
    }
}


async def enrich_workflow_templates(target_db: Optional[str] = None):
    dsn = settings.asyncpg_dsn
    if target_db:
        dsn = dsn.rsplit("/", 1)[0] + f"/{target_db}"
    db_name = dsn.rsplit('/', 1)[-1]
    print(f"Connecting to database: {db_name} ...")
    conn = await asyncpg.connect(dsn)
    try:
        print(f"Starting workflow templates outcome metadata enrichment on '{db_name}'...")
        # Ensure column is JSON (preserves exact dictionary key ordering)
        await conn.execute("ALTER TABLE workflow_templates ALTER COLUMN outcome_transitions TYPE JSON USING outcome_transitions::json;")
        updated_tasks = 0
        updated_activities = 0

        # 1. Update TASK templates with rich outcome transitions
        for tmpl_id, outcomes in RICH_TASK_OUTCOMES.items():
            json_str = json.dumps(outcomes, ensure_ascii=False)
            res = await conn.execute(
                """
                UPDATE workflow_templates
                SET outcome_transitions = $1::json
                WHERE template_id = $2
                """,
                json_str, tmpl_id
            )
            if res == "UPDATE 1":
                updated_tasks += 1
                print(f"✓ Updated TASK template: {tmpl_id} with {len(outcomes)} rich outcomes.")

        # 2. Update ACTIVITY templates with documented outcomes
        for tmpl_id, outcomes in RICH_ACTIVITY_OUTCOMES.items():
            json_str = json.dumps(outcomes, ensure_ascii=False)
            res = await conn.execute(
                """
                UPDATE workflow_templates
                SET outcome_transitions = $1::json
                WHERE template_id = $2
                """,
                json_str, tmpl_id
            )
            if res == "UPDATE 1":
                updated_activities += 1
                print(f"✓ Documented ACTIVITY template: {tmpl_id} with {len(outcomes)} outcomes.")

        total_rich = await conn.fetchval(
            "SELECT count(*) FROM workflow_templates WHERE outcome_transitions IS NOT NULL"
        )
        print(f"\nFinished enrichment successfully! Total templates with rich outcome transitions: {total_rich}")

    finally:
        await conn.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(enrich_workflow_templates(target))

