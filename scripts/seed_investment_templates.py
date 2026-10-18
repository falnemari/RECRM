import asyncio
import asyncpg
from app.config import settings

TEMPLATES = [
    # Tasks
    (
        "TASK_INVEST_LEAD_FIRST_CONTACT",
        "TASK",
        "طلب استثماري — الاتصال الأولي وتأكيد الرغبة",
        "Investment Lead — First Contact",
        "INVESTMENT_ADVISOR",
        30,
        "Contact investor customer within 30 minutes to confirm investment interest and schedule consultation"
    ),
    (
        "TASK_INVEST_CONFIRM_OBJECTIVES",
        "TASK",
        "الاستثمار — تأكيد وتحديد الأهداف الاستثمارية",
        "Investment — Confirm Investment Objectives",
        "INVESTMENT_ADVISOR",
        1440,
        "Budget, investment horizon, risk preferences, and return objectives are recorded"
    ),
    (
        "TASK_INVEST_COMPARE_RETURNS",
        "TASK",
        "الاستثمار — مقارنة العوائد الاستثمارية للوحدات المرشحة",
        "Investment — Compare Property Returns",
        "INVESTMENT_ADVISOR",
        1440,
        "Comparable properties have consistent, documented assumptions"
    ),
    (
        "TASK_INVEST_VALIDATE_FINANCIALS",
        "TASK",
        "الاستثمار — تدقيق والتحقق من الافتراضات المالية",
        "Investment — Validate Financial Assumptions",
        "INVESTMENT_ADVISOR",
        1440,
        "Rent, vacancy, operating expenses, financing, and acquisition costs are reviewed"
    ),
    (
        "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
        "TASK",
        "الاستثمار — إعداد وتقديم عرض الاستحواذ",
        "Investment — Prepare Acquisition Offer",
        "INVESTMENT_ADVISOR",
        720,
        "Offer and approval requirements are complete"
    ),
    (
        "TASK_INVEST_BASELINE_PERFORMANCE",
        "TASK",
        "الاستثمار — تأسيس خط الأساس لأداء الاستثمار",
        "Investment — Establish Performance Baseline",
        "INVESTMENT_ADVISOR",
        2880,
        "Purchase cost, forecast rent, costs, and target returns are recorded"
    ),
    (
        "TASK_INVEST_MONITOR_ACTUAL_RETURNS",
        "TASK",
        "الاستثمار — مراقبة ومقارنة العوائد الفعلية",
        "Investment — Monitor Actual Returns",
        "INVESTMENT_ADVISOR",
        4320,
        "Actual collections, expenses, vacancy, and performance variance are reviewed"
    ),
    (
        "TASK_INVEST_PORTFOLIO_REVIEW",
        "TASK",
        "الاستثمار — مراجعة أداء المحفظة الاستثمارية",
        "Investment — Review Portfolio Performance",
        "INVESTMENT_ADVISOR",
        10080,
        "Return variance and recommended next action are recorded"
    ),
    # Activities
    (
        "ACT_INVEST_LEAD_QUALIFIED",
        "ACTIVITY",
        "طلب الاستثمار — اكتمال التأهيل وتحديد المعايير",
        "Investment Lead — Qualified",
        "INVESTMENT_ADVISOR",
        0,
        "Investment lead qualified with explicit investment criteria"
    ),
    (
        "ACT_INVEST_OBJECTIVES_CONFIRMED",
        "ACTIVITY",
        "الاستثمار — تم اعتماد وتأكيد الأهداف الاستثمارية",
        "Investment — Objectives Confirmed",
        "INVESTMENT_ADVISOR",
        0,
        "Investor target capital, horizon, yield, and risk tolerance formally documented"
    ),
    (
        "ACT_INVEST_RETURNS_COMPARED",
        "ACTIVITY",
        "الاستثمار — تم إعداد دراسة مقارنة العوائد المالية",
        "Investment — Property Returns Compared",
        "INVESTMENT_ADVISOR",
        0,
        "Comparable properties evaluated under identical financial assumptions"
    ),
    (
        "ACT_INVEST_FINANCIALS_VALIDATED",
        "ACTIVITY",
        "الاستثمار — تم التحقق من الافتراضات المالية وتدقيقها",
        "Investment — Financial Assumptions Validated",
        "INVESTMENT_ADVISOR",
        0,
        "Rent forecasts, vacancy, operating costs, and financing vetted"
    ),
    (
        "ACT_INVEST_ACQUISITION_OFFER_PREPARED",
        "ACTIVITY",
        "الاستثمار — تم تقديم عرض الاستحواذ للعميل",
        "Investment — Acquisition Offer Prepared",
        "INVESTMENT_ADVISOR",
        0,
        "Acquisition offer submitted and approved by investor"
    ),
    (
        "ACT_INVEST_BASELINE_ESTABLISHED",
        "ACTIVITY",
        "الاستثمار — تم توثيق خط الأساس لمؤشرات الأداء المستهدفة",
        "Investment — Performance Baseline Established",
        "INVESTMENT_ADVISOR",
        0,
        "Baseline purchase price, forecast net rent, and expected ROI established"
    ),
    (
        "ACT_INVEST_RETURNS_MONITORED",
        "ACTIVITY",
        "الاستثمار — تم تدقيق العوائد الفعلية ومقارنتها بخط الأساس",
        "Investment — Actual Returns Monitored",
        "INVESTMENT_ADVISOR",
        0,
        "Actual rental income and expenses reconciled against baseline"
    ),
    (
        "ACT_INVEST_PORTFOLIO_REVIEWED",
        "ACTIVITY",
        "الاستثمار — تم إنجاز مراجعة المحفظة وتحديث التوصيات",
        "Investment — Portfolio Performance Reviewed",
        "INVESTMENT_ADVISOR",
        0,
        "Periodic review completed with variance analysis and future hold/sell recommendations"
    )
]

async def seed_templates():
    conn = await asyncpg.connect(settings.asyncpg_dsn)
    try:
        for t in TEMPLATES:
            await conn.execute(
                """
                INSERT INTO workflow_templates (
                    template_id, template_type, standard_title_ar, standard_title_en,
                    standard_subject_ar, standard_subject_en, owner_role, default_sla_minutes,
                    completion_criteria, escalation_role, escalation_sla_minutes, created_at
                ) VALUES ($1, $2, $3, $4, $3, $4, $5, $6, $7, 'BRANCH_MANAGER', 120, NOW())
                ON CONFLICT (template_id) DO UPDATE SET
                    standard_title_ar = EXCLUDED.standard_title_ar,
                    standard_title_en = EXCLUDED.standard_title_en,
                    standard_subject_ar = EXCLUDED.standard_subject_ar,
                    standard_subject_en = EXCLUDED.standard_subject_en,
                    owner_role = EXCLUDED.owner_role,
                    default_sla_minutes = EXCLUDED.default_sla_minutes,
                    completion_criteria = EXCLUDED.completion_criteria
                """,
                t[0], t[1], t[2], t[3], t[4], t[5], t[6]
            )
        count = await conn.fetchval("SELECT count(*) FROM workflow_templates WHERE template_id LIKE '%INVEST%'")
        print(f"Successfully seeded {count} investment templates.")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(seed_templates())

