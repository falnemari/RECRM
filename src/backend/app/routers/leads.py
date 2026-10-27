from datetime import datetime, timezone, timedelta
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Query, HTTPException, status, Header
import asyncpg
from app.database import get_db, get_next_id
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.schemas.leads import (
    LeadOut, LeadCreate, LeadUpdate, LeadNoteOut, LeadNoteCreate, LeadUnitItem,
    LeadQualifyIn, LeadContactIn
)
from app.routers.auth import check_user_scope_override, resolve_user_data_scope, resolve_data_scope_filter
from app.services.workflow_engine import WorkflowEngine

router = APIRouter(prefix="/leads", tags=["Leads"])

async def fetch_lead_units(conn: asyncpg.Connection, lead_id: str) -> List[LeadUnitItem]:
    rows = await conn.fetch("""
        SELECT 
            lu.unit_id,
            un.unit_number,
            un.owner_customer_id,
            COALESCE(NULLIF(TRIM(CONCAT(owner_c.first_name, ' ', owner_c.last_name)), ''), owner_c.company_name) AS unit_owner_name,
            owner_c.mobile AS unit_owner_mobile,
            b.name AS building_name,
            p.name_en AS project_name,
            CAST(COALESCE(un.asking_price, un.rent_price) AS FLOAT) AS unit_price,
            un.bedrooms,
            lu.is_primary
        FROM lead_units lu
        JOIN units un ON lu.unit_id = un.unit_id
        LEFT JOIN customers owner_c ON un.owner_customer_id = owner_c.customer_id
        LEFT JOIN buildings b ON un.building_id = b.building_id
        LEFT JOIN projects p ON b.project_id = p.project_id
        WHERE lu.lead_id = $1
        ORDER BY lu.is_primary DESC, lu.created_at ASC
    """, lead_id)
    return [LeadUnitItem(**dict(r)) for r in rows]

LEAD_SELECT_QUERY = """
    SELECT 
        l.lead_id,
        l.organization_id,
        l.customer_id,
        COALESCE(c.first_name || ' ' || c.last_name, c.company_name, 'Unknown Customer') AS customer_name,
        c.mobile AS customer_mobile,
        c.email AS customer_email,
        l.lead_source_id,
        ls.name AS lead_source_name,
        l.assigned_user_id,
        u.full_name AS assigned_user_name,
        l.branch_id,
        l.status,
        l.priority,
        l.inquiry_type,
        CAST(l.budget_min AS FLOAT) AS budget_min,
        CAST(l.budget_max AS FLOAT) AS budget_max,
        l.preferred_city_id,
        ci.name_en AS preferred_city_name,
        l.preferred_property_type_id,
        pt.name_en AS preferred_property_type_name,
        l.bedrooms_min,
        CAST(l.area_min_sqm AS FLOAT) AS area_min_sqm,
        l.unit_id,
        un.unit_number,
        b.name AS building_name,
        p.name_en AS project_name,
        CAST(COALESCE(un.asking_price, un.rent_price) AS FLOAT) AS unit_price,
        l.first_contact_due_at,
        l.first_contact_at,
        l.created_at,
        l.updated_at
    FROM leads l
    LEFT JOIN customers c ON l.customer_id = c.customer_id
    LEFT JOIN lead_sources ls ON l.lead_source_id = ls.lead_source_id
    LEFT JOIN users u ON l.assigned_user_id = u.user_id
    LEFT JOIN cities ci ON l.preferred_city_id = ci.city_id
    LEFT JOIN property_types pt ON l.preferred_property_type_id = pt.property_type_id
    LEFT JOIN units un ON l.unit_id = un.unit_id
    LEFT JOIN buildings b ON un.building_id = b.building_id
    LEFT JOIN projects p ON b.project_id = p.project_id
"""

@router.get("", response_model=CollectionEnvelope[LeadOut])
async def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    inquiry_type: Optional[str] = None,
    assigned_user_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    search: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    scope_info = await resolve_data_scope_filter(conn, x_user_id, assigned_user_id)
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"l.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if priority:
        pri = priority.upper()
        if pri in ("MEDIUM", "NORMAL"):
            conditions.append("l.priority IN ('MEDIUM', 'NORMAL')")
        else:
            conditions.append(f"l.priority = ${p_idx}")
            params.append(pri)
            p_idx += 1

    if inquiry_type:
        inq = inquiry_type.upper()
        if inq in ("INVEST", "INVESTMENT"):
            conditions.append("l.inquiry_type IN ('INVEST', 'INVESTMENT')")
        else:
            conditions.append(f"l.inquiry_type = ${p_idx}")
            params.append(inq)
            p_idx += 1

    if scope_info["scope_type"] == "OWN":
        conditions.append(f"l.assigned_user_id = ${p_idx}")
        params.append(scope_info["user_id"])
        p_idx += 1
    elif scope_info["scope_type"] == "BRANCH":
        conditions.append(
            f"(l.branch_id = ${p_idx} OR l.assigned_user_id IN (SELECT user_id FROM users WHERE branch_id = ${p_idx}) OR l.assigned_user_id = ${p_idx + 1})"
        )
        params.append(scope_info["branch_id"])
        params.append(scope_info.get("user_id") or "")
        p_idx += 2
    elif scope_info["scope_type"] == "GLOBAL" and scope_info.get("organization_id"):
        conditions.append(f"l.organization_id = ${p_idx}")
        params.append(scope_info["organization_id"])
        p_idx += 1

    if customer_id and customer_id.strip():
        conditions.append(f"CAST(l.customer_id AS TEXT) ILIKE ${p_idx}")
        params.append(f"%{customer_id.strip()}%")
        p_idx += 1

    if search and search.strip():
        s = search.strip()
        clean_digits = "".join(filter(str.isdigit, s))
        core_digits = clean_digits
        if core_digits.startswith("966"):
            core_digits = core_digits[3:]
        core_digits = core_digits.lstrip("0")

        if len(core_digits) >= 4:
            conditions.append(
                f"(c.first_name ILIKE ${p_idx} OR c.last_name ILIKE ${p_idx} OR c.company_name ILIKE ${p_idx} "
                f"OR c.mobile ILIKE ${p_idx} "
                f"OR regexp_replace(COALESCE(c.mobile, ''), '\\D', '', 'g') ILIKE ${p_idx + 1} "
                f"OR c.email ILIKE ${p_idx} "
                f"OR CAST(l.lead_id AS TEXT) ILIKE ${p_idx} OR CAST(l.customer_id AS TEXT) ILIKE ${p_idx})"
            )
            params.append(f"%{s}%")
            params.append(f"%{core_digits}%")
            p_idx += 2
        else:
            conditions.append(
                f"(c.first_name ILIKE ${p_idx} OR c.last_name ILIKE ${p_idx} OR c.company_name ILIKE ${p_idx} "
                f"OR c.mobile ILIKE ${p_idx} OR c.email ILIKE ${p_idx} "
                f"OR CAST(l.lead_id AS TEXT) ILIKE ${p_idx} OR CAST(l.customer_id AS TEXT) ILIKE ${p_idx})"
            )
            params.append(f"%{s}%")
            p_idx += 1

    where_clause = " AND ".join(conditions)

    count_query = f"SELECT count(*) FROM leads l LEFT JOIN customers c ON l.customer_id = c.customer_id WHERE {where_clause}"
    total = await conn.fetchval(count_query, *params)

    query = f"""
        {LEAD_SELECT_QUERY}
        WHERE {where_clause}
        ORDER BY l.created_at DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    
    lead_ids = [r["lead_id"] for r in rows]
    units_by_lead = {}
    if lead_ids:
        u_rows = await conn.fetch("""
            SELECT 
                lu.lead_id,
                lu.unit_id,
                un.unit_number,
                b.name AS building_name,
                p.name_en AS project_name,
                CAST(COALESCE(un.asking_price, un.rent_price) AS FLOAT) AS unit_price,
                un.bedrooms,
                lu.is_primary
            FROM lead_units lu
            JOIN units un ON lu.unit_id = un.unit_id
            LEFT JOIN buildings b ON un.building_id = b.building_id
            LEFT JOIN projects p ON b.project_id = p.project_id
            WHERE lu.lead_id = ANY($1)
            ORDER BY lu.is_primary DESC, lu.created_at ASC
        """, lead_ids)
        for ur in u_rows:
            d = dict(ur)
            lid = d.pop("lead_id")
            units_by_lead.setdefault(lid, []).append(LeadUnitItem(**d))

    data = [LeadOut(**dict(row), units=units_by_lead.get(row["lead_id"], [])) for row in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.get("/{lead_id}", response_model=ResponseEnvelope[LeadOut])
async def get_lead(
    lead_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    query = f"{LEAD_SELECT_QUERY} WHERE l.lead_id = $1"
    row = await conn.fetchrow(query, lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    if x_user_id:
        roles = await conn.fetch(
            "SELECT r.role_code FROM user_roles ur JOIN roles r ON ur.role_id = r.role_id WHERE ur.user_id = $1",
            x_user_id
        )
        scope = resolve_user_data_scope([r["role_code"] for r in roles])
        if scope == "OWN" and row["assigned_user_id"] != x_user_id:
            raise HTTPException(status_code=403, detail="Access denied: Lead belongs to another agent")
        if scope == "BRANCH":
            u_branch = await conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", x_user_id)
            if u_branch:
                ag_branch = await conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", row["assigned_user_id"])
                if row["branch_id"] != u_branch and ag_branch != u_branch:
                    raise HTTPException(status_code=403, detail="Access denied: Lead belongs to another branch")
    units = await fetch_lead_units(conn, lead_id)
    return ResponseEnvelope(data=LeadOut(**dict(row), units=units), meta=BaseMeta())

class LeadUnblockIn(BaseModel):
    action: str
    notes: Optional[str] = None

@router.get("/{lead_id}/situation", response_model=ResponseEnvelope[dict])
async def get_lead_situation_endpoint(
    lead_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    360-Degree Operational Situation & Next Action Engine for a Lead:
    Compiles complete milestone timeline, bottleneck/stalling status, and recommended actions.
    """
    if x_user_id:
        lead_agent = await conn.fetchval("SELECT assigned_user_id FROM leads WHERE lead_id = $1", lead_id)
        if lead_agent:
            roles = await conn.fetch(
                "SELECT r.role_code FROM user_roles ur JOIN roles r ON ur.role_id = r.role_id WHERE ur.user_id = $1",
                x_user_id
            )
            scope = resolve_user_data_scope([r["role_code"] for r in roles])
            if scope == "OWN" and lead_agent != x_user_id:
                raise HTTPException(status_code=403, detail="Access denied: Lead belongs to another agent")
    try:
        data = await WorkflowEngine.get_entity_situation(conn=conn, lead_id=lead_id)
        return ResponseEnvelope(data=data, meta=BaseMeta())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/{lead_id}/unblock", response_model=ResponseEnvelope[dict])
async def unblock_lead_endpoint(
    lead_id: str,
    payload: LeadUnblockIn,
    conn: asyncpg.Connection = Depends(get_db),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Executes a 1-click unblock action on any stalled lead.
    """
    try:
        async with conn.transaction():
            data = await WorkflowEngine.unblock_entity_situation(
                conn=conn,
                action=payload.action,
                lead_id=lead_id,
                user_id=x_user_id,
                notes=payload.notes
            )
        return ResponseEnvelope(data=data, meta=BaseMeta())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("", response_model=ResponseEnvelope[LeadOut], status_code=status.HTTP_201_CREATED)
async def create_lead(payload: LeadCreate, conn: asyncpg.Connection = Depends(get_db)):
    org_id = await conn.fetchval("SELECT organization_id FROM organizations LIMIT 1")
    if not org_id:
        raise HTTPException(status_code=500, detail="No active organization found")

    async with conn.transaction():
        # 1. Customer Deduplication & Resolution
        customer_id = payload.customer_id
        is_duplicate_customer = False
        duplicate_note = None

        if not customer_id and (payload.first_name or payload.mobile or payload.email or payload.national_id):
            customer_id, is_duplicate_customer, cust_info = await WorkflowEngine.find_or_create_customer(
                conn=conn,
                org_id=org_id,
                first_name=payload.first_name,
                last_name=payload.last_name,
                mobile=payload.mobile,
                email=payload.email,
                national_id=payload.national_id,
                customer_type="INDIVIDUAL"
            )
            if is_duplicate_customer:
                matched_label = cust_info.get("matched_by") or "بيانات الاتصال"
                duplicate_note = f"تم العثور على ملف عميل قائم مطابق عبر {matched_label} ({cust_info.get('full_name')} - {customer_id}) وتم ربط الطلب بملفه بدلاً من تكراره."

        # 2. Determine Branch and Manager Assignment
        assigned_user_id = payload.assigned_user_id
        branch_id = None
        branch_manager_id = None

        if assigned_user_id:
            branch_id = await conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", assigned_user_id)
        else:
            # Option 2: Route unassigned lead to Branch Manager based on preferred_city
            branch_id, branch_manager_id = await WorkflowEngine.find_branch_and_manager_for_city(
                conn=conn,
                city_id=payload.preferred_city_id
            )

        # 3. SLA Deadlines
        now_dt = datetime.now(timezone.utc)
        first_contact_due_at = (now_dt + timedelta(minutes=30)) if assigned_user_id else None

        # If preferred property type is Land, bedrooms_min should be None
        eff_bedrooms_min = payload.bedrooms_min
        eff_area_min_sqm = payload.area_min_sqm
        if payload.preferred_property_type_id:
            pt_info = await conn.fetchrow(
                "SELECT code, category, name_en, name_ar FROM property_types WHERE property_type_id = $1",
                payload.preferred_property_type_id
            )
            if pt_info:
                pt_text = f"{pt_info['code'] or ''} {pt_info['category'] or ''} {pt_info['name_en'] or ''} {pt_info['name_ar'] or ''}".upper()
                if "LAND" in pt_text or "أرض" in (pt_info['name_ar'] or ""):
                    if eff_bedrooms_min and not eff_area_min_sqm:
                        eff_area_min_sqm = float(eff_bedrooms_min)
                    eff_bedrooms_min = None

        # 4. Generate Sequential Lead ID
        lead_id = await get_next_id(conn, "leads", "lead")

        # 5. Insert Lead in 'NEW' status
        await conn.execute(
            """
            INSERT INTO leads (
                lead_id, organization_id, customer_id, lead_source_id, assigned_user_id,
                branch_id, unit_id, status, priority, inquiry_type, budget_min, budget_max,
                bedrooms_min, area_min_sqm, preferred_city_id, preferred_property_type_id,
                first_contact_due_at, created_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, 'NEW', $8::text, $9, $10, $11, $12, $13, $14, $15,
                $16, NOW(), NOW()
            )
            """,
            lead_id, org_id, customer_id, payload.lead_source_id, assigned_user_id,
            branch_id, payload.unit_id or None, payload.priority, payload.inquiry_type,
            payload.budget_min, payload.budget_max, eff_bedrooms_min, eff_area_min_sqm,
            payload.preferred_city_id, payload.preferred_property_type_id, first_contact_due_at
        )

        # 6. Insert Unit Associations
        primary_unit = payload.unit_id or (payload.unit_ids[0] if payload.unit_ids else None)
        if payload.unit_ids:
            for idx, uid in enumerate(payload.unit_ids):
                is_prim = (uid == primary_unit) or (primary_unit is None and idx == 0)
                await conn.execute("""
                    INSERT INTO lead_units (lead_id, unit_id, is_primary)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (lead_id, unit_id) DO NOTHING
                """, lead_id, uid, is_prim)
        elif payload.unit_id:
            await conn.execute("""
                INSERT INTO lead_units (lead_id, unit_id, is_primary)
                VALUES ($1, $2, TRUE)
                ON CONFLICT (lead_id, unit_id) DO NOTHING
            """, lead_id, payload.unit_id)

        # 7. Workflow Engine: Task Spawning & Routing
        if assigned_user_id:
            inq = (payload.inquiry_type or "").upper()
            if inq == "RENT":
                contact_tmpl = "TASK_RENT_LEAD_FIRST_CONTACT"
            elif inq in ("INVEST", "INVESTMENT"):
                contact_tmpl = "TASK_INVEST_LEAD_FIRST_CONTACT"
            else:
                contact_tmpl = "TASK_LEAD_FIRST_CONTACT"
            await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id=contact_tmpl,
                lead_id=lead_id,
                customer_id=customer_id,
                assigned_user_id=assigned_user_id,
                priority=payload.priority or "NORMAL",
                custom_due_at=first_contact_due_at
            )

            # 8. Workflow Engine: Record Lead Creation Activity
            activity_notes = "تم استلام وتعيين الطلب بنجاح للوسيط. مهلة الاتصال بالعميل: 30 دقيقة."
            if duplicate_note:
                activity_notes += f"\n{duplicate_note}"

            await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_LEAD_CREATED",
                user_id=assigned_user_id,
                customer_id=customer_id,
                lead_id=lead_id,
                outcome="CREATED",
                notes=activity_notes
            )
        else:
            # Unassigned lead: Route to Branch Manager with TASK_LEAD_ASSIGN (15m SLA)
            assign_due_at = now_dt + timedelta(minutes=15)
            await WorkflowEngine.spawn_task_from_template(
                conn=conn,
                template_id="TASK_LEAD_ASSIGN",
                lead_id=lead_id,
                customer_id=customer_id,
                assigned_user_id=branch_manager_id,
                priority="HIGH",
                custom_due_at=assign_due_at
            )

            # 8. Workflow Engine: Record Lead Routing Activity
            activity_notes = "طلب جديد وارد بدون وسيط. تم توجيهه تلقائياً إلى مدير الفرع المعني لتعيين وسيط مبيعات خلال 15 دقيقة."
            if duplicate_note:
                activity_notes += f"\n{duplicate_note}"

            await WorkflowEngine.record_activity_from_template(
                conn=conn,
                template_id="ACT_LEAD_ROUTED",
                user_id=branch_manager_id,
                customer_id=customer_id,
                lead_id=lead_id,
                outcome="ROUTED",
                notes=activity_notes
            )


    # 9. Return Created Lead with Duplication Indicators
    query = f"{LEAD_SELECT_QUERY} WHERE l.lead_id = $1"
    row = await conn.fetchrow(query, lead_id)
    units = await fetch_lead_units(conn, lead_id)
    lead_dict = dict(row)
    lead_dict["is_duplicate_customer"] = is_duplicate_customer
    lead_dict["duplicate_customer_note"] = duplicate_note

    return ResponseEnvelope(data=LeadOut(**lead_dict, units=units), meta=BaseMeta())

@router.patch("/{lead_id}", response_model=ResponseEnvelope[LeadOut])
async def update_lead(
    lead_id: str,
    payload: LeadUpdate,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):

    current_lead = await conn.fetchrow(
        "SELECT assigned_user_id, status, preferred_property_type_id, bedrooms_min, area_min_sqm FROM leads WHERE lead_id = $1",
        lead_id
    )
    if not current_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    old_assigned_user_id = current_lead["assigned_user_id"]

    updates = []
    params = []
    p_idx = 1

    fields_set = payload.model_fields_set

    if "customer_id" in fields_set:
        updates.append(f"customer_id = ${p_idx}")
        params.append(payload.customer_id)
        p_idx += 1

    if "lead_source_id" in fields_set:
        updates.append(f"lead_source_id = ${p_idx}")
        params.append(payload.lead_source_id)
        p_idx += 1

    if payload.status is not None:
        st_upper = payload.status.upper()
        updates.append(f"status = ${p_idx}")
        params.append(st_upper)
        p_idx += 1
        if st_upper == 'CONTACTED' and payload.first_contact_at is None:
            updates.append("first_contact_at = COALESCE(first_contact_at, now())")

    if payload.priority is not None:
        updates.append(f"priority = ${p_idx}")
        params.append(payload.priority.upper())
        p_idx += 1

    if payload.inquiry_type is not None:
        updates.append(f"inquiry_type = ${p_idx}")
        params.append(payload.inquiry_type.upper())
        p_idx += 1

    if "assigned_user_id" in fields_set:
        updates.append(f"assigned_user_id = ${p_idx}")
        params.append(payload.assigned_user_id)
        p_idx += 1

    if "budget_min" in fields_set:
        updates.append(f"budget_min = ${p_idx}")
        params.append(payload.budget_min)
        p_idx += 1

    if "budget_max" in fields_set:
        updates.append(f"budget_max = ${p_idx}")
        params.append(payload.budget_max)
        p_idx += 1

    if "preferred_city_id" in fields_set:
        updates.append(f"preferred_city_id = ${p_idx}")
        params.append(payload.preferred_city_id)
        p_idx += 1

    if "preferred_property_type_id" in fields_set:
        updates.append(f"preferred_property_type_id = ${p_idx}")
        params.append(payload.preferred_property_type_id)
        p_idx += 1

    # Check if effective preferred property type is Land
    eff_prop_type_id = payload.preferred_property_type_id if "preferred_property_type_id" in fields_set else current_lead["preferred_property_type_id"]
    is_land_type = False
    if eff_prop_type_id:
        pt_row = await conn.fetchrow(
            "SELECT code, category, name_en, name_ar FROM property_types WHERE property_type_id = $1",
            eff_prop_type_id
        )
        if pt_row:
            pt_text = f"{pt_row['code'] or ''} {pt_row['category'] or ''} {pt_row['name_en'] or ''} {pt_row['name_ar'] or ''}".upper()
            if "LAND" in pt_text or "أرض" in (pt_row["name_ar"] or ""):
                is_land_type = True

    if "bedrooms_min" in fields_set:
        target_beds = None if is_land_type else payload.bedrooms_min
        updates.append(f"bedrooms_min = ${p_idx}")
        params.append(target_beds)
        p_idx += 1
    elif is_land_type and current_lead["bedrooms_min"] is not None:
        updates.append("bedrooms_min = NULL")

    if "area_min_sqm" in fields_set:
        updates.append(f"area_min_sqm = ${p_idx}")
        params.append(payload.area_min_sqm)
        p_idx += 1

    if payload.unit_ids is not None:
        await conn.execute("DELETE FROM lead_units WHERE lead_id = $1", lead_id)
        primary_unit = payload.unit_id or (payload.unit_ids[0] if payload.unit_ids else None)
        for idx, uid in enumerate(payload.unit_ids):
            is_prim = (uid == primary_unit) or (primary_unit is None and idx == 0)
            await conn.execute("""
                INSERT INTO lead_units (lead_id, unit_id, is_primary)
                VALUES ($1, $2, $3)
                ON CONFLICT (lead_id, unit_id) DO UPDATE SET is_primary = $3
            """, lead_id, uid, is_prim)
        updates.append(f"unit_id = ${p_idx}")
        params.append(primary_unit)
        p_idx += 1
    elif payload.unit_id is not None:
        if payload.unit_id == "" or payload.unit_id.lower() == "null":
            await conn.execute("DELETE FROM lead_units WHERE lead_id = $1", lead_id)
            updates.append("unit_id = NULL")
        else:
            await conn.execute("""
                INSERT INTO lead_units (lead_id, unit_id, is_primary)
                VALUES ($1, $2, TRUE)
                ON CONFLICT (lead_id, unit_id) DO UPDATE SET is_primary = TRUE
            """, lead_id, payload.unit_id)
            updates.append(f"unit_id = ${p_idx}")
            params.append(payload.unit_id)
            p_idx += 1

    if payload.first_contact_at is not None:
        updates.append(f"first_contact_at = ${p_idx}")
        params.append(payload.first_contact_at)
        p_idx += 1

    if updates:
        updates.append("updated_at = now()")
        params.append(lead_id)
        update_query = f"UPDATE leads SET {', '.join(updates)} WHERE lead_id = ${p_idx}"
        await conn.execute(update_query, *params)

        # Sync priority to all active tasks associated with this lead and its opportunities
        if payload.priority is not None:
            new_pri = payload.priority.upper()
            await conn.execute("""
                UPDATE tasks
                SET priority = $1
                WHERE (lead_id = $2 OR opportunity_id IN (SELECT opportunity_id FROM opportunities WHERE lead_id = $2))
                  AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
            """, new_pri, lead_id)


        # Trigger workflow lead assignment handler ONLY IF assigned_user_id actually changed
        if payload.assigned_user_id and payload.assigned_user_id != old_assigned_user_id:
            await WorkflowEngine.on_lead_assigned(
                conn=conn,
                lead_id=lead_id,
                assigned_user_id=payload.assigned_user_id,
                assigner_user_id=x_user_id
            )


        # Sync with Sales Pipeline opportunities if status changed
        if payload.status is not None:
            st = payload.status.upper()
            if st in ("QUALIFIED", "CONVERTED"):
                await WorkflowEngine.on_lead_qualified(
                    conn=conn,
                    lead_id=lead_id,
                    user_id=x_user_id,
                    budget_min=payload.budget_min,
                    budget_max=payload.budget_max,
                    preferred_property_type_id=payload.preferred_property_type_id,
                    preferred_city_id=payload.preferred_city_id
                )
            elif st in ("LOST", "DISQUALIFIED"):
                await conn.execute("UPDATE opportunities SET stage = 'LOST', updated_at = now() WHERE lead_id = $1 AND stage NOT IN ('WON', 'LOST')", lead_id)

    query = f"{LEAD_SELECT_QUERY} WHERE l.lead_id = $1"
    row = await conn.fetchrow(query, lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    units = await fetch_lead_units(conn, lead_id)
    return ResponseEnvelope(data=LeadOut(**dict(row), units=units), meta=BaseMeta())

@router.post("/{lead_id}/contact", response_model=ResponseEnvelope[LeadOut])
async def mark_lead_contacted(
    lead_id: str,
    payload: Optional[LeadContactIn] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    outcome = (payload.outcome if payload and payload.outcome else "CONNECTED").upper()
    notes = payload.notes if payload else None

    async with conn.transaction():
        lead_row = await conn.fetchrow("SELECT lead_id, customer_id, assigned_user_id, status FROM leads WHERE lead_id = $1", lead_id)
        if not lead_row:
            raise HTTPException(status_code=404, detail="Lead not found")

        user_id = x_user_id or lead_row["assigned_user_id"] or "user-51"

        # Look for open first contact or followup task
        open_task = await conn.fetchrow(
            """
            SELECT task_id FROM tasks 
            WHERE lead_id = $1 AND template_id IN ('TASK_LEAD_FIRST_CONTACT', 'TASK_RENT_LEAD_FIRST_CONTACT', 'TASK_INVEST_LEAD_FIRST_CONTACT', 'TASK_LEAD_FOLLOWUP')
              AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
            LIMIT 1
            """,
            lead_id
        )

        if open_task:
            await WorkflowEngine.complete_task_with_outcome(
                conn=conn,
                task_id=open_task["task_id"],
                user_id=user_id,
                outcome=outcome,
                notes=notes or "تم تسجيل محاولة التواصل مع العميل."
            )
        else:
            now_dt = datetime.now(timezone.utc)
            if outcome == "CONNECTED":
                await conn.execute("""
                    UPDATE leads 
                    SET status = 'CONTACTED',
                        first_contact_at = COALESCE(first_contact_at, now()),
                        updated_at = now()
                    WHERE lead_id = $1
                """, lead_id)

                await WorkflowEngine.record_activity_from_template(
                    conn=conn,
                    template_id="ACT_LEAD_FIRST_CONTACT",
                    user_id=user_id,
                    customer_id=lead_row["customer_id"],
                    lead_id=lead_id,
                    outcome="CONNECTED",
                    notes=notes or "تم التواصل مع العميل وتحديث الحالة إلى متصل (CONTACTED)."
                )

                await WorkflowEngine.spawn_task_from_template(
                    conn=conn,
                    template_id="TASK_LEAD_QUALIFY",
                    lead_id=lead_id,
                    customer_id=lead_row["customer_id"],
                    assigned_user_id=lead_row["assigned_user_id"] or user_id,
                    priority="HIGH"
                )
            elif outcome in ("NO_ANSWER", "BUSY", "UNREACHABLE"):
                await WorkflowEngine.record_activity_from_template(
                    conn=conn,
                    template_id="ACT_LEAD_FOLLOWUP",
                    user_id=user_id,
                    customer_id=lead_row["customer_id"],
                    lead_id=lead_id,
                    outcome=outcome,
                    notes=notes or "محاولة اتصال لم يتم الرد عليها.",
                    completed_at=now_dt
                )
                followup_due = now_dt + timedelta(hours=3)
                await WorkflowEngine.spawn_task_from_template(
                    conn=conn,
                    template_id="TASK_LEAD_FOLLOWUP",
                    lead_id=lead_id,
                    customer_id=lead_row["customer_id"],
                    assigned_user_id=lead_row["assigned_user_id"] or user_id,
                    custom_due_at=followup_due,
                    priority="NORMAL"
                )
            elif outcome in ("DISQUALIFIED", "NOT_INTERESTED"):
                await conn.execute("""
                    UPDATE leads 
                    SET status = 'DISQUALIFIED',
                        updated_at = now()
                    WHERE lead_id = $1
                """, lead_id)
                await WorkflowEngine.record_activity_from_template(
                    conn=conn,
                    template_id="ACT_LEAD_FIRST_CONTACT",
                    user_id=user_id,
                    customer_id=lead_row["customer_id"],
                    lead_id=lead_id,
                    outcome="DISQUALIFIED",
                    notes=notes or "العميل غير مهتم بالعرض.",
                    completed_at=now_dt
                )

    query = f"{LEAD_SELECT_QUERY} WHERE l.lead_id = $1"
    row = await conn.fetchrow(query, lead_id)
    units = await fetch_lead_units(conn, lead_id)
    return ResponseEnvelope(data=LeadOut(**dict(row), units=units), meta=BaseMeta())

@router.post("/{lead_id}/qualify", response_model=ResponseEnvelope[LeadOut])
async def qualify_lead(
    lead_id: str,
    payload: Optional[LeadQualifyIn] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    async with conn.transaction():
        await WorkflowEngine.on_lead_qualified(
            conn=conn,
            lead_id=lead_id,
            user_id=x_user_id,
            budget_min=payload.budget_min if payload else None,
            budget_max=payload.budget_max if payload else None,
            preferred_property_type_id=payload.preferred_property_type_id if payload else None,
            preferred_city_id=payload.preferred_city_id if payload else None,
            notes=payload.notes if payload else None
        )

    query = f"{LEAD_SELECT_QUERY} WHERE l.lead_id = $1"
    row = await conn.fetchrow(query, lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    units = await fetch_lead_units(conn, lead_id)
    return ResponseEnvelope(data=LeadOut(**dict(row), units=units), meta=BaseMeta())


@router.get("/{lead_id}/notes", response_model=CollectionEnvelope[LeadNoteOut])
async def list_lead_notes(lead_id: str, conn: asyncpg.Connection = Depends(get_db)):
    query = """
        SELECT 
            ln.note_id,
            ln.lead_id,
            ln.user_id AS created_by_user_id,
            u.full_name AS created_by_user_name,
            ln.note_text AS note,
            ln.created_at
        FROM lead_notes ln
        LEFT JOIN users u ON ln.user_id = u.user_id
        WHERE ln.lead_id = $1
        ORDER BY ln.created_at DESC
    """
    rows = await conn.fetch(query, lead_id)
    data = [LeadNoteOut(**dict(row)) for row in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.post("/{lead_id}/notes", response_model=ResponseEnvelope[LeadNoteOut], status_code=status.HTTP_201_CREATED)
async def add_lead_note(lead_id: str, payload: LeadNoteCreate, conn: asyncpg.Connection = Depends(get_db)):
    user_id = await conn.fetchval("SELECT user_id FROM users LIMIT 1")
    note_id = await conn.fetchval(
        """
        INSERT INTO lead_notes (lead_id, user_id, note_text, created_at)
        VALUES ($1, $2, $3, now())
        RETURNING note_id
        """,
        lead_id, user_id, payload.note
    )
    query = """
        SELECT 
            ln.note_id,
            ln.lead_id,
            ln.user_id AS created_by_user_id,
            u.full_name AS created_by_user_name,
            ln.note_text AS note,
            ln.created_at
        FROM lead_notes ln
        LEFT JOIN users u ON ln.user_id = u.user_id
        WHERE ln.note_id = $1
    """
    row = await conn.fetchrow(query, note_id)
    return ResponseEnvelope(data=LeadNoteOut(**dict(row)), meta=BaseMeta())

