from typing import List, Dict, Any, Optional
from uuid import UUID
from fastapi import APIRouter, Depends
import asyncpg
from app.database import get_db
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta

router = APIRouter(tags=["Reference Data"])

@router.get("/cities", response_model=CollectionEnvelope[Dict[str, Any]])
async def list_cities(conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch("SELECT city_id, country_code, region_name, name_ar, name_en, status FROM cities ORDER BY name_en")
    data = [dict(row) for row in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/property-types", response_model=CollectionEnvelope[Dict[str, Any]])
async def list_property_types(conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch("SELECT property_type_id, code, name_ar, name_en, category FROM property_types ORDER BY name_en")
    data = [dict(row) for row in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/lead-sources", response_model=CollectionEnvelope[Dict[str, Any]])
async def list_lead_sources(conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch("SELECT lead_source_id, code, name, channel FROM lead_sources ORDER BY name")
    data = [dict(row) for row in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/users", response_model=CollectionEnvelope[Dict[str, Any]])
async def list_users(
    city_id: Optional[str] = None,
    branch_id: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    conditions = ["u.status = 'ACTIVE'"]
    params = []
    p_idx = 1
    if city_id:
        conditions.append(f"b.city_id = ${p_idx}")
        params.append(city_id)
        p_idx += 1
    if branch_id:
        conditions.append(f"u.branch_id = ${p_idx}")
        params.append(branch_id)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT 
            u.user_id, u.employee_no, u.full_name, u.email, u.mobile, u.status,
            u.branch_id, b.name AS branch_name, b.city_id,
            COALESCE(array_agg(r.role_code ORDER BY r.role_code) FILTER (WHERE r.role_code IS NOT NULL), ARRAY[]::varchar[]) AS role_codes,
            COALESCE(array_agg(r.name_ar ORDER BY r.role_code) FILTER (WHERE r.name_ar IS NOT NULL), ARRAY[]::varchar[]) AS role_names_ar,
            COALESCE(array_agg(r.name_en ORDER BY r.role_code) FILTER (WHERE r.name_en IS NOT NULL), ARRAY[]::varchar[]) AS role_names_en,
            COALESCE(string_agg(COALESCE(r.name_ar, r.name), '، ' ORDER BY r.role_code), '') AS role_titles_ar
        FROM users u
        LEFT JOIN branches b ON u.branch_id = b.branch_id
        LEFT JOIN user_roles ur ON u.user_id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.role_id
        WHERE {where_clause}
        GROUP BY u.user_id, u.employee_no, u.full_name, u.email, u.mobile, u.status, u.branch_id, b.name, b.city_id
        ORDER BY u.full_name
    """
    rows = await conn.fetch(query, *params)
    data = [dict(row) for row in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/branches", response_model=CollectionEnvelope[Dict[str, Any]])
async def list_reference_branches(
    city_id: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    conditions = ["b.status = 'ACTIVE'"]
    params = []
    p_idx = 1
    if city_id:
        conditions.append(f"b.city_id = ${p_idx}")
        params.append(city_id)
        p_idx += 1
    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT 
            b.branch_id, b.branch_code, b.name, b.city_id,
            c.name_ar AS city_name_ar, c.name_en AS city_name_en, b.status
        FROM branches b
        LEFT JOIN cities c ON b.city_id = c.city_id
        WHERE {where_clause}
        ORDER BY b.name
    """
    rows = await conn.fetch(query, *params)
    data = [dict(r) for r in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/loss-reasons", response_model=CollectionEnvelope[Dict[str, Any]])
async def list_loss_reasons(conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch("SELECT loss_reason_id, code, name FROM loss_reasons ORDER BY name")
    data = [dict(row) for row in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/activity-types", response_model=CollectionEnvelope[Dict[str, Any]])
async def list_activity_types(conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch("SELECT activity_type_id, code, name FROM activity_types ORDER BY name")
    data = [dict(row) for row in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/document-types", response_model=CollectionEnvelope[Dict[str, Any]])
async def list_document_types(conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch("SELECT document_type_id, code, name, expiry_required FROM document_types ORDER BY name")
    data = [dict(row) for row in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/roles", response_model=CollectionEnvelope[Dict[str, Any]])
async def list_roles_reference(conn: asyncpg.Connection = Depends(get_db)):
    """Canonical bilingual organizational roles catalog."""
    rows = await conn.fetch("""
        SELECT role_id, role_code, name, name_ar, name_en, description 
        FROM roles 
        ORDER BY role_code
    """)
    data = [dict(row) for row in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/workflow-templates", response_model=CollectionEnvelope[Dict[str, Any]])
async def list_workflow_templates(conn: asyncpg.Connection = Depends(get_db)):
    """
    Returns all standard workflow templates (Tasks, Activities, Communications)
    directly from the database as the Single Source of Truth for frontend localization.
    """
    rows = await conn.fetch("""
        SELECT template_id, template_type, standard_title_ar, standard_title_en,
               owner_role, default_sla_minutes,
               completion_criteria_ar, completion_criteria_en, escalation_role, escalation_sla_minutes, created_at,
               next_template_id, outcome_transitions
        FROM workflow_templates
        ORDER BY template_type ASC, template_id ASC
    """)
    import json
    data = []
    for row in rows:
        d = dict(row)
        if d.get("outcome_transitions") and isinstance(d["outcome_transitions"], str):
            try:
                d["outcome_transitions"] = json.loads(d["outcome_transitions"])
            except Exception:
                pass
        data.append(d)
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/sop-catalog", response_model=CollectionEnvelope[Dict[str, Any]])
async def list_sop_catalog(
    stage_code: Optional[str] = None,
    entity_type: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    Unified Bilingual SOP Guidance Matrix covering all tasks, activities,
    communications, and lifecycle procedures joined dynamically with canonical roles.
    """
    conditions = ["g.is_active = TRUE"]
    params = []
    p_idx = 1
    if stage_code:
        conditions.append(f"g.stage_code = ${p_idx}")
        params.append(stage_code.upper())
        p_idx += 1
    if entity_type:
        conditions.append(f"g.entity_type = ${p_idx}")
        params.append(entity_type.upper())
        p_idx += 1

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT 
            g.guidance_id, g.stage_code, g.entity_type, g.procedure_code, g.template_id,
            COALESCE(t.owner_role, g.responsible_role_code) AS responsible_role_code,
            COALESCE(t.standard_title_ar, g.stage_name_ar) AS stage_name_ar,
            COALESCE(t.standard_title_en, g.stage_name_en) AS stage_name_en,
            t.completion_criteria_ar,
            t.completion_criteria_en,
            g.required_now_ar, g.required_now_en,
            r.name_ar AS current_responsible_ar,
            r.name_en AS current_responsible_en,
            g.next_action_ar, g.next_action_en,
            g.step_goal_ar, g.step_goal_en,
            g.mandatory_conditions_ar, g.mandatory_conditions_en,
            g.consequence_ar, g.consequence_en,
            g.execution_steps_ar, g.execution_steps_en,
            g.sample_notes_ar, g.sample_notes_en,
            g.display_order, g.is_active
        FROM workflow_sop_guidance g
        LEFT JOIN workflow_templates t ON g.template_id = t.template_id
        LEFT JOIN roles r ON COALESCE(t.owner_role, g.responsible_role_code) = r.role_code
        WHERE {where_clause}
        ORDER BY g.display_order ASC
    """
    rows = await conn.fetch(query, *params)
    import json
    data = []
    for row in rows:
        item = dict(row)
        for f in ("execution_steps_ar", "execution_steps_en"):
            if isinstance(item.get(f), str):
                try:
                    item[f] = json.loads(item[f])
                except Exception:
                    pass
        data.append(item)

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/sop-guide/{code}", response_model=ResponseEnvelope[Dict[str, Any]])
async def get_sop_guide(code: str, conn: asyncpg.Connection = Depends(get_db)):
    """
    Fetch exact step-by-step SOP execution guide and sample notes for a task template,
    activity template, procedure code, or task/activity instance.
    Guarantees resilient resolution with fuzzy matching and fallback synthesis.
    """
    import json
    import urllib.parse
    raw_code = urllib.parse.unquote(code).strip()
    search_code = raw_code

    # Direct Activity to Task template mapping
    ACT_TO_TASK_MAP = {
        "ACT_INVEST_OBJECTIVES_CONFIRMED": "TASK_INVEST_CONFIRM_OBJECTIVES",
        "ACT_INVEST_RETURNS_COMPARED": "TASK_INVEST_COMPARE_RETURNS",
        "ACT_INVEST_INSPECTION_SCHEDULED": "TASK_INVEST_SCHEDULE_INSPECTION",
        "ACT_INVEST_INSPECTION_COMPLETED": "TASK_INVEST_INSPECTION_REPORT",
        "ACT_INVEST_FINANCIALS_VALIDATED": "TASK_INVEST_VALIDATE_FINANCIALS",
        "ACT_INVEST_ACQUISITION_OFFER_PREPARED": "TASK_INVEST_PREPARE_ACQUISITION_OFFER",
        "ACT_INVEST_BASELINE_ESTABLISHED": "TASK_INVEST_BASELINE_PERFORMANCE",
        "ACT_INVEST_RETURNS_MONITORED": "TASK_INVEST_MONITOR_ACTUAL_RETURNS",
        "ACT_INVEST_PORTFOLIO_REVIEWED": "TASK_INVEST_PORTFOLIO_REVIEW",
        "ACT_INVEST_LEAD_QUALIFIED": "TASK_INVEST_CONFIRM_OBJECTIVES",
        "ACT_RENT_LEAD_QUALIFIED": "TASK_RENT_LEAD_FIRST_CONTACT",
        "ACT_RENT_PROPERTIES_MATCHED": "TASK_RENT_MATCH_PROPERTIES",
        "ACT_TENANCY_ACTIVATED": "TASK_RENT_PREPARE_TENANCY",
        "ACT_RENT_PAYMENT_COLLECTED": "TASK_RENT_COLLECTION_MONITORING",
        "ACT_VIEWING_SCHEDULED": "TASK_VIEWING_SCHEDULE",
        "ACT_VIEWING_REPORT_SUBMITTED": "TASK_VIEWING_REPORT",
        "ACT_OFFER_CREATED": "TASK_OFFER_PREPARE",
        "ACT_OFFER_SUBMITTED": "TASK_OFFER_SUBMIT",
        "ACT_OFFER_DECISION": "TASK_OFFER_FOLLOWUP",
        "ACT_RESERVATION_AVAILABILITY_VERIFIED": "TASK_RESERVATION_VERIFY_AVAILABILITY",
        "ACT_RESERVATION_CONFIRMED": "TASK_RESERVATION_DEPOSIT_FOLLOWUP",
        "ACT_CONTRACT_DRAFT_CREATED": "TASK_CONTRACT_DRAFT",
        "ACT_CONTRACT_SIGNED": "TASK_CONTRACT_SIGNATURE",
        "ACT_CONTRACT_CLOSED": "TASK_CONTRACT_HANDOVER",
        "ACT_LEAD_CREATED": "TASK_LEAD_FIRST_CONTACT",
        "ACT_LEAD_FIRST_CONTACT": "TASK_LEAD_FIRST_CONTACT",
        "ACT_LEAD_FOLLOWUP": "TASK_LEAD_FOLLOWUP",
        "ACT_LEAD_QUALIFIED": "TASK_LEAD_QUALIFY",
        "ACT_LEAD_ASSIGNED": "TASK_LEAD_ASSIGN",
        "ACT_LEAD_ROUTED": "TASK_LEAD_ASSIGN",
        "ACT_OPPORTUNITY_PROPERTIES_PRESENTED": "TASK_OPPORTUNITY_MATCH_PROPERTIES",
        "ACT_TASK_REOPENED": "TASK_UNBLOCK_PROCEDURE",
        "ACT_FINANCIAL_CHECK": "TASK_LEAD_QUALIFY",
    }

    # 1. Resolve task-ID (e.g. task-1234)
    if search_code.lower().startswith("task-"):
        t_row = await conn.fetchrow("SELECT template_id, title FROM tasks WHERE task_id = $1", search_code)
        if t_row:
            if t_row.get("template_id"):
                search_code = t_row["template_id"]
            elif t_row.get("title"):
                search_code = t_row["title"]

    # 2. Resolve act-ID (e.g. act-5678)
    elif search_code.lower().startswith("act-"):
        a_row = await conn.fetchrow("SELECT template_id, subject FROM activities WHERE activity_id = $1", search_code)
        if a_row:
            if a_row.get("template_id"):
                search_code = a_row["template_id"]
            elif a_row.get("subject"):
                search_code = a_row["subject"]

    # 3. Check direct activity mapping
    if search_code in ACT_TO_TASK_MAP:
        search_code = ACT_TO_TASK_MAP[search_code]

    # 4. Check exact title match in workflow_templates
    tmpl_match = await conn.fetchval(
        "SELECT template_id FROM workflow_templates WHERE standard_title_ar = $1 OR standard_title_en = $1",
        search_code
    )
    if tmpl_match:
        search_code = tmpl_match
        if search_code in ACT_TO_TASK_MAP:
            search_code = ACT_TO_TASK_MAP[search_code]

    base_select = """
        SELECT 
            g.guidance_id, g.stage_code, g.entity_type, g.procedure_code, g.template_id,
            COALESCE(t.owner_role, g.responsible_role_code) AS responsible_role_code,
            COALESCE(t.standard_title_ar, g.stage_name_ar) AS stage_name_ar,
            COALESCE(t.standard_title_en, g.stage_name_en) AS stage_name_en,
            t.completion_criteria_ar,
            t.completion_criteria_en,
            g.required_now_ar, g.required_now_en,
            r.name_ar AS current_responsible_ar,
            r.name_en AS current_responsible_en,
            g.next_action_ar, g.next_action_en,
            g.step_goal_ar, g.step_goal_en,
            g.mandatory_conditions_ar, g.mandatory_conditions_en,
            g.consequence_ar, g.consequence_en,
            g.execution_steps_ar, g.execution_steps_en,
            g.sample_notes_ar, g.sample_notes_en,
            g.display_order, g.is_active
        FROM workflow_sop_guidance g
        LEFT JOIN workflow_templates t ON g.template_id = t.template_id
        LEFT JOIN roles r ON COALESCE(t.owner_role, g.responsible_role_code) = r.role_code
    """

    # 5. Query workflow_sop_guidance directly
    row = await conn.fetchrow(f"""
        {base_select}
        WHERE (g.template_id = $1 OR g.procedure_code = $1 OR g.guidance_id = $1)
          AND g.is_active = TRUE
        ORDER BY g.display_order ASC LIMIT 1
    """, search_code)

    # 6. Try stage_code match
    if not row:
        row = await conn.fetchrow(f"""
            {base_select}
            WHERE g.stage_code = $1 AND g.is_active = TRUE
            ORDER BY g.display_order ASC LIMIT 1
        """, search_code.upper())

    # 7. Fuzzy matching for Arabic/English keywords (handles slight variations like "الاستثمار — تأكيد الأهداف والميزانية")
    if not row:
        norm = (raw_code + " " + search_code).lower()
        resolved_template = None
        if "استثمار" in norm or "invest" in norm:
            if any(w in norm for w in ["هدف", "أهداف", "ميزانية", "objective"]):
                resolved_template = "TASK_INVEST_CONFIRM_OBJECTIVES"
            elif any(w in norm for w in ["عائد", "عوائد", "مقارنة", "return"]):
                resolved_template = "TASK_INVEST_COMPARE_RETURNS"
            elif any(w in norm for w in ["فحص", "معاينة", "إنشائي", "نافي للجهالة", "inspect", "due diligence"]):
                resolved_template = "TASK_INVEST_INSPECTION_REPORT" if any(x in norm for x in ["تقرير", "توثيق", "report", "complete"]) else "TASK_INVEST_SCHEDULE_INSPECTION"
            elif any(w in norm for w in ["افتراض", "تدقيق", "مالي", "validat"]):
                resolved_template = "TASK_INVEST_VALIDATE_FINANCIALS"
            elif any(w in norm for w in ["استحواذ", "عرض", "acquisit", "offer"]):
                resolved_template = "TASK_INVEST_PREPARE_ACQUISITION_OFFER"
            elif any(w in norm for w in ["أساس", "خط أساس", "baseline"]):
                resolved_template = "TASK_INVEST_BASELINE_PERFORMANCE"
            elif any(w in norm for w in ["مراقبة", "فعلية", "monitor"]):
                resolved_template = "TASK_INVEST_MONITOR_ACTUAL_RETURNS"
            elif any(w in norm for w in ["محفظة", "portfolio"]):
                resolved_template = "TASK_INVEST_PORTFOLIO_REVIEW"
            else:
                resolved_template = "TASK_INVEST_LEAD_FIRST_CONTACT"
        elif "إيجار" in norm or "تأجير" in norm or "rent" in norm:
            if any(w in norm for w in ["مطابقة", "ترشيح", "وحدات", "match"]):
                resolved_template = "TASK_RENT_MATCH_PROPERTIES"
            elif any(w in norm for w in ["جدولة", "موعد", "schedule"]):
                resolved_template = "TASK_VIEWING_SCHEDULE"
            elif any(w in norm for w in ["معاينة", "زيارة", "متابعة", "رغبة", "view", "follow"]):
                resolved_template = "TASK_RENT_VIEWING_FOLLOW_UP"
            elif any(w in norm for w in ["عقد", "صياغة", "إبرام", "tenancy", "lease"]):
                resolved_template = "TASK_RENT_PREPARE_TENANCY"
            elif any(w in norm for w in ["تحصيل", "دفعات", "قسط", "collect"]):
                resolved_template = "TASK_RENT_COLLECTION_MONITORING"
            else:
                resolved_template = "TASK_RENT_LEAD_FIRST_CONTACT"
        elif "عقد" in norm or "contract" in norm:
            if any(w in norm for w in ["صياغة", "مسودة", "draft"]):
                resolved_template = "TASK_CONTRACT_DRAFT"
            elif any(w in norm for w in ["مراجعة", "قانونية", "اعتماد", "review"]):
                resolved_template = "TASK_CONTRACT_INTERNAL_REVIEW"
            elif any(w in norm for w in ["توقيع", "sign"]):
                resolved_template = "TASK_CONTRACT_SIGNATURE"
            elif any(w in norm for w in ["مطابقة", "تسوية", "دفعات", "reconciliation"]):
                resolved_template = "TASK_CONTRACT_RECONCILIATION"
            elif any(w in norm for w in ["تسليم", "فحص", "handover"]):
                resolved_template = "TASK_CONTRACT_HANDOVER"
        elif "معاينة" in norm or "viewing" in norm:
            if any(w in norm for w in ["تقرير", "تقييم", "report"]):
                resolved_template = "TASK_VIEWING_REPORT"
            elif any(w in norm for w in ["جدولة", "موعد", "schedule"]):
                resolved_template = "TASK_VIEWING_SCHEDULE"
            elif any(w in norm for w in ["إعادة", "reschedule"]):
                resolved_template = "TASK_VIEWING_RESCHEDULE"
        elif "حجز" in norm or "reservation" in norm:
            if any(w in norm for w in ["توفر", "جاهزية", "availability"]):
                resolved_template = "TASK_RESERVATION_VERIFY_AVAILABILITY"
            elif any(w in norm for w in ["عربون", "سداد", "deposit"]):
                resolved_template = "TASK_RESERVATION_DEPOSIT_FOLLOWUP"
            elif any(w in norm for w in ["انتهاء", "تمديد", "expiry"]):
                resolved_template = "TASK_RESERVATION_EXPIRY_REVIEW"
            elif any(w in norm for w in ["مستندات", "وثائق", "documents"]):
                resolved_template = "TASK_RESERVATION_DOCUMENTS"
        elif "عرض" in norm or "offer" in norm:
            if any(w in norm for w in ["إعداد", "تجاري", "prepare"]):
                resolved_template = "TASK_OFFER_PREPARE"
            elif any(w in norm for w in ["تقديم", "مالي", "submit"]):
                resolved_template = "TASK_OFFER_SUBMIT"
            elif any(w in norm for w in ["اعتماد", "تخفيض", "approval"]):
                resolved_template = "TASK_OFFER_MANAGER_APPROVAL"
            elif any(w in norm for w in ["متابعة", "صلاحية", "followup"]):
                resolved_template = "TASK_OFFER_FOLLOWUP"

        if resolved_template:
            row = await conn.fetchrow(f"""
                {base_select}
                WHERE g.template_id = $1 AND g.is_active = TRUE
                ORDER BY g.display_order ASC LIMIT 1
            """, resolved_template)

    # 8. If still not found, try partial text matching in stage_name_ar / stage_name_en
    if not row and len(raw_code) >= 3:
        row = await conn.fetchrow(f"""
            {base_select}
            WHERE (g.stage_name_ar ILIKE $1 OR g.stage_name_en ILIKE $1 OR g.step_goal_ar ILIKE $1)
              AND g.is_active = TRUE
            ORDER BY g.display_order ASC LIMIT 1
        """, f"%{raw_code}%")

    # 9. Fallback Synthesizer: NEVER return 404. Always provide clear, structured SOP guidance.
    if not row:
        display_title_ar = raw_code if any('\u0600' <= c <= '\u06FF' for c in raw_code) else f"إجراء تشغيلي: {raw_code}"
        display_title_en = raw_code if not any('\u0600' <= c <= '\u06FF' for c in raw_code) else f"Operational Procedure: {raw_code}"
        item = {
            "guidance_id": f"sop-fallback-{search_code.lower().replace('_', '-')}",
            "stage_code": "GENERAL",
            "entity_type": "TASK",
            "procedure_code": search_code,
            "template_id": search_code,
            "responsible_role_code": "SALES_AGENT",
            "stage_name_ar": display_title_ar,
            "stage_name_en": display_title_en,
            "required_now_ar": "مراجعة متطلبات الإجراء والتواصل مع الأطراف وتوثيق محضر الإنجاز في النظام.",
            "required_now_en": "Review task requirements, contact stakeholders, and record completion details.",
            "current_responsible_ar": "الوسيط أو المستشار المكلف",
            "current_responsible_en": "Assigned Agent or Advisor",
            "next_action_ar": "متابعة الخطوة التالية في مسار سير العمل بعد الحفظ والاعتماد.",
            "next_action_en": "Proceed to next operational step upon save and sign-off.",
            "step_goal_ar": "إنجاز المتطلب التشغيلي بأعلى معايير الدقة والامتثال المؤسسي.",
            "step_goal_en": "Complete the operational requirement with highest quality and compliance.",
            "mandatory_conditions_ar": "التأكد من اكتمال كافة البيانات الإلزامية وتوثيق التاريخ والنتيجة بدقة.",
            "mandatory_conditions_en": "Ensure all mandatory fields and outcome details are properly committed.",
            "consequence_ar": "إغلاق المهمة بنجاح وتحديث السجل التاريخي للطلب في لوحة التحكم.",
            "consequence_en": "Completes task and appends verified audit trail to CRM lead history.",
            "execution_steps_ar": [
                {"step_no": 1, "title": "مراجعة بيانات المهمة والطلب", "description": "الاطلاع على خلفية الطلب وسجل الملاحظات والأنشطة السابقة."},
                {"step_no": 2, "title": "تنفيذ الإجراء المطلوب مع العميل", "description": "التواصل الفعلي واستيفاء كافة البيانات والمتطلبات الإلزامية."},
                {"step_no": 3, "title": "تدقيق المعايير والامتثال", "description": "التأكد من صحة المدخلات ومطابقتها لسياسات العمل المعتمدة."},
                {"step_no": 4, "title": "حفظ النتيجة وإغلاق المهمة", "description": "تسجيل النتيجة والملاحظات في النظام واعتماد إنجاز المهمة."}
            ],
            "execution_steps_en": [
                {"step_no": 1, "title": "Review Task and Lead Context", "description": "Inspect previous notes, lead history, and required task parameters."},
                {"step_no": 2, "title": "Execute Procedure with Stakeholder", "description": "Conduct communication and gather necessary details or documentation."},
                {"step_no": 3, "title": "Audit Compliance and Criteria", "description": "Verify accuracy and alignment with operational brokerage policies."},
                {"step_no": 4, "title": "Commit Outcome and Mark Completed", "description": "Select outcome, enter clear notes, and save task completion."}
            ],
            "sample_notes_ar": f"تم استكمال متطلبات ({display_title_ar}) والتأكد من استيفاء كافة البنود وتحديث سجل العميل.",
            "sample_notes_en": f"Completed requirements for ({display_title_en}); verified all criteria and refreshed customer profile.",
            "display_order": 99,
            "is_active": True
        }
        return ResponseEnvelope(data=item, meta=BaseMeta())

    item = dict(row)
    for f in ("execution_steps_ar", "execution_steps_en"):
        if isinstance(item.get(f), str):
            try:
                item[f] = json.loads(item[f])
            except Exception:
                pass

    return ResponseEnvelope(data=item, meta=BaseMeta())



