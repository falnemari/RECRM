from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException, status
import asyncpg
from app.database import get_db
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.schemas.leads import LeadOut, LeadCreate, LeadUpdate, LeadNoteOut, LeadNoteCreate

router = APIRouter(prefix="/leads", tags=["Leads"])

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
"""

@router.get("", response_model=CollectionEnvelope[LeadOut])
async def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    inquiry_type: Optional[str] = None,
    assigned_user_id: Optional[UUID] = None,
    customer_id: Optional[str] = None,
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
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

    if assigned_user_id:
        conditions.append(f"l.assigned_user_id = ${p_idx}")
        params.append(assigned_user_id)
        p_idx += 1

    if customer_id and customer_id.strip():
        conditions.append(f"CAST(l.customer_id AS TEXT) ILIKE ${p_idx}")
        params.append(f"%{customer_id.strip()}%")
        p_idx += 1

    if search and search.strip():
        s = search.strip()
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
    data = [LeadOut(**dict(row)) for row in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.get("/{lead_id}", response_model=ResponseEnvelope[LeadOut])
async def get_lead(lead_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    query = f"{LEAD_SELECT_QUERY} WHERE l.lead_id = $1"
    row = await conn.fetchrow(query, lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return ResponseEnvelope(data=LeadOut(**dict(row)), meta=BaseMeta())

@router.post("", response_model=ResponseEnvelope[LeadOut], status_code=status.HTTP_201_CREATED)
async def create_lead(payload: LeadCreate, conn: asyncpg.Connection = Depends(get_db)):
    # Fetch default organization
    org_id = await conn.fetchval("SELECT organization_id FROM organizations LIMIT 1")
    if not org_id:
        raise HTTPException(status_code=500, detail="No active organization found")

    customer_id = payload.customer_id
    if not customer_id and (payload.first_name or payload.mobile):
        # Create new customer record
        customer_id = await conn.fetchval(
            """
            INSERT INTO customers (organization_id, customer_type, first_name, last_name, mobile, email, preferred_language, status)
            VALUES ($1, 'INDIVIDUAL', $2, $3, $4, $5, 'ar', 'ACTIVE')
            RETURNING customer_id
            """,
            org_id, payload.first_name or "New", payload.last_name or "Lead", payload.mobile, payload.email
        )

    lead_id = await conn.fetchval(
        """
        INSERT INTO leads (
            organization_id, customer_id, lead_source_id, assigned_user_id,
            status, priority, inquiry_type, budget_min, budget_max,
            bedrooms_min, area_min_sqm, preferred_city_id, preferred_property_type_id
        ) VALUES (
            $1, $2, $3, $4, 'NEW', $5, $6, $7, $8, $9, $10, $11, $12
        ) RETURNING lead_id
        """,
        org_id, customer_id, payload.lead_source_id, payload.assigned_user_id,
        payload.priority, payload.inquiry_type, payload.budget_min, payload.budget_max,
        payload.bedrooms_min, payload.area_min_sqm, payload.preferred_city_id, payload.preferred_property_type_id
    )

    query = f"{LEAD_SELECT_QUERY} WHERE l.lead_id = $1"
    row = await conn.fetchrow(query, lead_id)
    return ResponseEnvelope(data=LeadOut(**dict(row)), meta=BaseMeta())

@router.patch("/{lead_id}", response_model=ResponseEnvelope[LeadOut])
async def update_lead(lead_id: UUID, payload: LeadUpdate, conn: asyncpg.Connection = Depends(get_db)):
    updates = []
    params = []
    p_idx = 1

    if payload.customer_id is not None:
        updates.append(f"customer_id = ${p_idx}")
        params.append(payload.customer_id)
        p_idx += 1

    if payload.lead_source_id is not None:
        updates.append(f"lead_source_id = ${p_idx}")
        params.append(payload.lead_source_id)
        p_idx += 1

    if payload.status is not None:
        updates.append(f"status = ${p_idx}")
        params.append(payload.status.upper())
        p_idx += 1

    if payload.priority is not None:
        updates.append(f"priority = ${p_idx}")
        params.append(payload.priority.upper())
        p_idx += 1

    if payload.inquiry_type is not None:
        updates.append(f"inquiry_type = ${p_idx}")
        params.append(payload.inquiry_type.upper())
        p_idx += 1

    if payload.assigned_user_id is not None:
        updates.append(f"assigned_user_id = ${p_idx}")
        params.append(payload.assigned_user_id)
        p_idx += 1

    if payload.budget_min is not None:
        updates.append(f"budget_min = ${p_idx}")
        params.append(payload.budget_min)
        p_idx += 1

    if payload.budget_max is not None:
        updates.append(f"budget_max = ${p_idx}")
        params.append(payload.budget_max)
        p_idx += 1

    if payload.bedrooms_min is not None:
        updates.append(f"bedrooms_min = ${p_idx}")
        params.append(payload.bedrooms_min)
        p_idx += 1

    if payload.area_min_sqm is not None:
        updates.append(f"area_min_sqm = ${p_idx}")
        params.append(payload.area_min_sqm)
        p_idx += 1

    if payload.preferred_city_id is not None:
        updates.append(f"preferred_city_id = ${p_idx}")
        params.append(payload.preferred_city_id)
        p_idx += 1

    if payload.preferred_property_type_id is not None:
        updates.append(f"preferred_property_type_id = ${p_idx}")
        params.append(payload.preferred_property_type_id)
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

    query = f"{LEAD_SELECT_QUERY} WHERE l.lead_id = $1"
    row = await conn.fetchrow(query, lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return ResponseEnvelope(data=LeadOut(**dict(row)), meta=BaseMeta())

@router.post("/{lead_id}/qualify", response_model=ResponseEnvelope[LeadOut])
async def qualify_lead(lead_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    await conn.execute("UPDATE leads SET status = 'QUALIFIED', updated_at = now() WHERE lead_id = $1", lead_id)
    query = f"{LEAD_SELECT_QUERY} WHERE l.lead_id = $1"
    row = await conn.fetchrow(query, lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return ResponseEnvelope(data=LeadOut(**dict(row)), meta=BaseMeta())

@router.get("/{lead_id}/notes", response_model=CollectionEnvelope[LeadNoteOut])
async def list_lead_notes(lead_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
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
async def add_lead_note(lead_id: UUID, payload: LeadNoteCreate, conn: asyncpg.Connection = Depends(get_db)):
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

