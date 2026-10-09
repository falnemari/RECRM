from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException, status
import asyncpg
from app.database import get_db
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.schemas.sales import OpportunityOut, OpportunityUpdate, ViewingOut, ReservationOut

router = APIRouter(tags=["Sales Pipeline"])

OPP_SELECT_QUERY = """
    SELECT 
        o.opportunity_id,
        o.lead_id,
        o.customer_id,
        COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
        c.mobile AS customer_mobile,
        o.assigned_user_id,
        u.full_name AS assigned_user_name,
        o.stage,
        CAST(o.expected_value AS FLOAT) AS expected_value,
        o.expected_close_date,
        o.created_at,
        o.updated_at
    FROM opportunities o
    LEFT JOIN customers c ON o.customer_id = c.customer_id
    LEFT JOIN users u ON o.assigned_user_id = u.user_id
"""

@router.get("/opportunities", response_model=CollectionEnvelope[OpportunityOut])
async def list_opportunities(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    stage: Optional[str] = None,
    assigned_user_id: Optional[UUID] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if stage:
        conditions.append(f"o.stage = ${p_idx}")
        params.append(stage.upper())
        p_idx += 1

    if assigned_user_id:
        conditions.append(f"o.assigned_user_id = ${p_idx}")
        params.append(assigned_user_id)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"SELECT count(*) FROM opportunities o WHERE {where_clause}", *params)

    query = f"""
        {OPP_SELECT_QUERY}
        WHERE {where_clause}
        ORDER BY o.created_at DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [OpportunityOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.get("/opportunities/{opp_id}", response_model=ResponseEnvelope[OpportunityOut])
async def get_opportunity(opp_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    query = f"{OPP_SELECT_QUERY} WHERE o.opportunity_id = $1"
    row = await conn.fetchrow(query, opp_id)
    if not row:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return ResponseEnvelope(data=OpportunityOut(**dict(row)), meta=BaseMeta())

@router.patch("/opportunities/{opp_id}", response_model=ResponseEnvelope[OpportunityOut])
async def update_opportunity(opp_id: UUID, payload: OpportunityUpdate, conn: asyncpg.Connection = Depends(get_db)):
    updates = []
    params = []
    p_idx = 1

    if payload.stage is not None:
        updates.append(f"stage = ${p_idx}")
        params.append(payload.stage.upper())
        p_idx += 1

    if payload.expected_value is not None:
        updates.append(f"expected_value = ${p_idx}")
        params.append(payload.expected_value)
        p_idx += 1

    if payload.expected_close_date is not None:
        updates.append(f"expected_close_date = ${p_idx}")
        params.append(payload.expected_close_date)
        p_idx += 1

    if payload.assigned_user_id is not None:
        updates.append(f"assigned_user_id = ${p_idx}")
        params.append(payload.assigned_user_id)
        p_idx += 1

    if updates:
        updates.append("updated_at = now()")
        params.append(opp_id)
        await conn.execute(f"UPDATE opportunities SET {', '.join(updates)} WHERE opportunity_id = ${p_idx}", *params)

    query = f"{OPP_SELECT_QUERY} WHERE o.opportunity_id = $1"
    row = await conn.fetchrow(query, opp_id)
    if not row:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return ResponseEnvelope(data=OpportunityOut(**dict(row)), meta=BaseMeta())

@router.get("/viewings", response_model=CollectionEnvelope[ViewingOut])
async def list_viewings(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"v.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"SELECT count(*) FROM viewings v WHERE {where_clause}", *params)

    query = f"""
        SELECT 
            v.viewing_id,
            v.opportunity_id,
            v.unit_id,
            u.unit_number,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            v.scheduled_start,
            v.scheduled_end,
            v.status,
            COALESCE(v.outcome, v.notes) AS feedback
        FROM viewings v
        LEFT JOIN units u ON v.unit_id = u.unit_id
        LEFT JOIN customers c ON v.customer_id = c.customer_id
        WHERE {where_clause}
        ORDER BY v.scheduled_start DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [ViewingOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.get("/reservations", response_model=CollectionEnvelope[ReservationOut])
async def list_reservations(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"r.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"SELECT count(*) FROM reservations r WHERE {where_clause}", *params)

    query = f"""
        SELECT 
            r.reservation_id,
            r.opportunity_id,
            r.unit_id,
            u.unit_number,
            r.reservation_number,
            r.reserved_at,
            r.expires_at,
            CAST(r.deposit_amount AS FLOAT) AS deposit_amount,
            r.status
        FROM reservations r
        LEFT JOIN units u ON r.unit_id = u.unit_id
        WHERE {where_clause}
        ORDER BY r.reserved_at DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [ReservationOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

