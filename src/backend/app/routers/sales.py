from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Query, HTTPException, status, Header
import asyncpg
from app.database import get_db, get_next_id
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.routers.auth import check_user_scope_override
from app.schemas.sales import (
    OpportunityOut, OpportunityUpdate, OpportunityCreateIn, ViewingOut, ViewingCreateIn, ReservationOut,
    OfferOut, OfferCreateIn, OfferUpdateIn, OfferDecisionIn, ReservationCreateIn, ReservationDepositVerifyIn,
    OpportunityUnitOut, OpportunityUnitCreateIn
)
from app.services.workflow_engine import WorkflowEngine

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
        l.inquiry_type,
        CAST(l.budget_min AS FLOAT) AS budget_min,
        CAST(l.budget_max AS FLOAT) AS budget_max,
        l.bedrooms_min,
        CAST(l.area_min_sqm AS FLOAT) AS area_min_sqm,
        l.preferred_property_type_id,
        pt.name_en AS preferred_property_type_name,
        l.preferred_city_id,
        ct.name_en AS preferred_city_name,
        o.created_at,
        o.updated_at
    FROM opportunities o
    LEFT JOIN customers c ON o.customer_id = c.customer_id
    LEFT JOIN users u ON o.assigned_user_id = u.user_id
    LEFT JOIN leads l ON o.lead_id = l.lead_id
    LEFT JOIN property_types pt ON l.preferred_property_type_id = pt.property_type_id
    LEFT JOIN cities ct ON l.preferred_city_id = ct.city_id
"""

@router.get("/opportunities", response_model=CollectionEnvelope[OpportunityOut])
async def list_opportunities(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    stage: Optional[str] = None,
    assigned_user_id: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    assigned_user_id = await check_user_scope_override(conn, x_user_id, assigned_user_id)
    # Auto-sync any qualified leads that don't yet have an opportunity in the pipeline
    unsynced = await conn.fetch("""
        SELECT l.lead_id, l.customer_id, l.assigned_user_id, l.budget_max, l.budget_min
        FROM leads l
        LEFT JOIN opportunities o ON l.lead_id = o.lead_id
        WHERE l.status IN ('QUALIFIED', 'CONVERTED')
          AND l.customer_id IS NOT NULL
          AND o.opportunity_id IS NULL
    """)
    for l in unsynced:
        opp_id = await get_next_id(conn, "opportunities", "opportunity")
        val = float(l["budget_max"] or l["budget_min"] or 0.0)
        await conn.execute("""
            INSERT INTO opportunities (
                opportunity_id, lead_id, customer_id, assigned_user_id,
                stage, expected_value, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'QUALIFIED', $5, now(), now())
        """, opp_id, l["lead_id"], l["customer_id"], l["assigned_user_id"], val)

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
async def get_opportunity(opp_id: str, conn: asyncpg.Connection = Depends(get_db)):
    query = f"{OPP_SELECT_QUERY} WHERE o.opportunity_id = $1"
    row = await conn.fetchrow(query, opp_id)
    if not row:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return ResponseEnvelope(data=OpportunityOut(**dict(row)), meta=BaseMeta())

class OpportunityUnblockIn(BaseModel):
    action: str
    notes: Optional[str] = None

@router.get("/opportunities/{opp_id}/situation", response_model=ResponseEnvelope[dict])
@router.get("/sales/opportunities/{opp_id}/situation", response_model=ResponseEnvelope[dict], include_in_schema=False)
async def get_opportunity_situation_endpoint(opp_id: str, conn: asyncpg.Connection = Depends(get_db)):
    """
    360-Degree Operational Situation & Next Action Engine for a Sales Opportunity:
    Compiles complete milestone timeline, bottleneck/stalling status, and recommended actions.
    """
    try:
        data = await WorkflowEngine.get_entity_situation(conn=conn, opportunity_id=opp_id)
        return ResponseEnvelope(data=data, meta=BaseMeta())
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/opportunities/{opp_id}/unblock", response_model=ResponseEnvelope[dict])
@router.post("/sales/opportunities/{opp_id}/unblock", response_model=ResponseEnvelope[dict], include_in_schema=False)
async def unblock_opportunity_endpoint(
    opp_id: str,
    payload: OpportunityUnblockIn,
    conn: asyncpg.Connection = Depends(get_db),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID")
):
    """
    Executes a 1-click unblock action on any stalled opportunity.
    """
    try:
        async with conn.transaction():
            data = await WorkflowEngine.unblock_entity_situation(
                conn=conn,
                action=payload.action,
                opportunity_id=opp_id,
                user_id=x_user_id,
                notes=payload.notes
            )
        return ResponseEnvelope(data=data, meta=BaseMeta())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.patch("/opportunities/{opp_id}", response_model=ResponseEnvelope[OpportunityOut])
async def update_opportunity(opp_id: str, payload: OpportunityUpdate, conn: asyncpg.Connection = Depends(get_db)):
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

        # Reflect opportunity stage back into the linked lead in leads table
        if payload.stage is not None:
            new_stage = payload.stage.upper()
            if new_stage == "WON":
                await conn.execute("""
                    UPDATE leads SET status = 'CONVERTED', updated_at = now()
                    WHERE lead_id = (SELECT lead_id FROM opportunities WHERE opportunity_id = $1)
                      AND lead_id IS NOT NULL
                """, opp_id)
            elif new_stage == "LOST":
                await conn.execute("""
                    UPDATE leads SET status = 'LOST', updated_at = now()
                    WHERE lead_id = (SELECT lead_id FROM opportunities WHERE opportunity_id = $1)
                      AND lead_id IS NOT NULL
                """, opp_id)
            elif new_stage in ("QUALIFIED", "VIEWING", "NEGOTIATION"):
                await conn.execute("""
                    UPDATE leads SET status = 'QUALIFIED', updated_at = now()
                    WHERE lead_id = (SELECT lead_id FROM opportunities WHERE opportunity_id = $1)
                      AND lead_id IS NOT NULL AND status IN ('NEW', 'CONTACTED')
                """, opp_id)

    query = f"{OPP_SELECT_QUERY} WHERE o.opportunity_id = $1"
    row = await conn.fetchrow(query, opp_id)
    if not row:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return ResponseEnvelope(data=OpportunityOut(**dict(row)), meta=BaseMeta())

@router.post("/opportunities", response_model=ResponseEnvelope[OpportunityOut], status_code=status.HTTP_201_CREATED)
async def create_opportunity(payload: OpportunityCreateIn, conn: asyncpg.Connection = Depends(get_db)):
    opp_id = await get_next_id(conn, "opportunities", "opportunity")
    stage = (payload.stage or "QUALIFIED").upper()
    await conn.execute("""
        INSERT INTO opportunities (
            opportunity_id, lead_id, customer_id, assigned_user_id,
            stage, expected_value, expected_close_date, created_at, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, now(), now())
    """, opp_id, payload.lead_id, payload.customer_id, payload.assigned_user_id,
       stage, payload.expected_value or 0.0, payload.expected_close_date)

    query = f"{OPP_SELECT_QUERY} WHERE o.opportunity_id = $1"
    row = await conn.fetchrow(query, opp_id)
    return ResponseEnvelope(data=OpportunityOut(**dict(row)), meta=BaseMeta())

@router.post("/opportunities/sync-qualified-leads", response_model=ResponseEnvelope[dict])
@router.post("/sales/opportunities/sync-qualified-leads", response_model=ResponseEnvelope[dict], include_in_schema=False)
async def sync_qualified_leads(conn: asyncpg.Connection = Depends(get_db)):
    unsynced = await conn.fetch("""
        SELECT l.lead_id, l.customer_id, l.assigned_user_id, l.budget_max, l.budget_min
        FROM leads l
        LEFT JOIN opportunities o ON l.lead_id = o.lead_id
        WHERE l.status IN ('QUALIFIED', 'CONVERTED')
          AND l.customer_id IS NOT NULL
          AND o.opportunity_id IS NULL
    """)
    synced_count = 0
    for l in unsynced:
        opp_id = await get_next_id(conn, "opportunities", "opportunity")
        val = float(l["budget_max"] or l["budget_min"] or 0.0)
        await conn.execute("""
            INSERT INTO opportunities (
                opportunity_id, lead_id, customer_id, assigned_user_id,
                stage, expected_value, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, 'QUALIFIED', $5, now(), now())
        """, opp_id, l["lead_id"], l["customer_id"], l["assigned_user_id"], val)
        synced_count += 1
    return ResponseEnvelope(data={"synced_count": synced_count, "message": f"Successfully synced {synced_count} qualified leads into active opportunities."})

@router.get("/viewings", response_model=CollectionEnvelope[ViewingOut])
async def list_viewings(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    opportunity_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    unit_id: Optional[str] = None,
    agent_user_id: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    agent_user_id = await check_user_scope_override(conn, x_user_id, agent_user_id)
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"v.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if opportunity_id:
        conditions.append(f"v.opportunity_id = ${p_idx}")
        params.append(opportunity_id)
        p_idx += 1

    if lead_id:
        conditions.append(f"v.lead_id = ${p_idx}")
        params.append(lead_id)
        p_idx += 1

    if unit_id:
        conditions.append(f"v.unit_id = ${p_idx}")
        params.append(unit_id)
        p_idx += 1

    if agent_user_id:
        conditions.append(f"v.agent_user_id = ${p_idx}")
        params.append(agent_user_id)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"SELECT count(*) FROM viewings v WHERE {where_clause}", *params)

    query = f"""
        SELECT 
            v.viewing_id,
            v.opportunity_id,
            v.lead_id,
            v.unit_id,
            u.unit_number,
            COALESCE(p.name_ar, p.name_en) AS project_name,
            b.name AS building_name,
            v.customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            v.agent_user_id,
            ag.full_name AS agent_user_name,
            v.scheduled_start,
            v.scheduled_end,
            v.status,
            v.outcome,
            v.notes,
            COALESCE(v.outcome, v.notes) AS feedback
        FROM viewings v
        LEFT JOIN units u ON v.unit_id = u.unit_id
        LEFT JOIN buildings b ON u.building_id = b.building_id
        LEFT JOIN projects p ON b.project_id = p.project_id
        LEFT JOIN customers c ON v.customer_id = c.customer_id
        LEFT JOIN users ag ON v.agent_user_id = ag.user_id
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

@router.post("/viewings", response_model=ResponseEnvelope[dict])
async def create_viewing(
    payload: ViewingCreateIn,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    user_id = x_user_id or payload.agent_user_id or "user-51"
    async with conn.transaction():
        res = await WorkflowEngine.schedule_property_viewing(
            conn=conn,
            user_id=user_id,
            unit_id=payload.unit_id,
            scheduled_start=payload.scheduled_start,
            scheduled_end=payload.scheduled_end,
            task_id=payload.task_id,
            lead_id=payload.lead_id,
            opportunity_id=payload.opportunity_id,
            customer_id=payload.customer_id,
            agent_user_id=payload.agent_user_id or user_id,
            notes=payload.notes
        )
    return ResponseEnvelope(data=res)

@router.patch("/viewings/{viewing_id}", response_model=ResponseEnvelope[dict])
async def update_viewing(
    viewing_id: str,
    payload: dict,
    conn: asyncpg.Connection = Depends(get_db)
):
    updates = []
    params = []
    p_idx = 1
    for k in ("status", "outcome", "notes", "scheduled_start", "scheduled_end"):
        if k in payload and payload[k] is not None:
            updates.append(f"{k} = ${p_idx}")
            params.append(payload[k])
            p_idx += 1
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    updates.append("updated_at = NOW()")
    params.append(viewing_id)
    await conn.execute(
        f"UPDATE viewings SET {', '.join(updates)} WHERE viewing_id = ${p_idx}",
        *params
    )
    row = await conn.fetchrow("SELECT * FROM viewings WHERE viewing_id = $1", viewing_id)
    if not row:
        raise HTTPException(status_code=404, detail="Viewing not found.")
    return ResponseEnvelope(data=dict(row))

RESERVATION_SELECT_QUERY = """
    SELECT 
        r.reservation_id,
        r.opportunity_id,
        r.unit_id,
        u.unit_number,
        r.reservation_number,
        r.reserved_at,
        r.expires_at,
        CAST(r.deposit_amount AS FLOAT) AS deposit_amount,
        r.status,
        r.customer_id,
        COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
        c.mobile AS customer_mobile,
        c.email AS customer_email,
        c.national_id_hash AS national_id,
        p.name_en AS project_name,
        b.name AS building_name,
        pt.name_en AS property_type,
        u.bedrooms,
        u.bathrooms,
        CAST(u.area_sqm AS FLOAT) AS area_sqm,
        u.floor_no,
        CAST(u.asking_price AS FLOAT) AS asking_price,
        u.status AS unit_status,
        opp.assigned_user_id AS assigned_agent_id,
        ag.full_name AS assigned_agent_name,
        con.contract_id,
        con.contract_number,
        CAST(con.contract_value AS FLOAT) AS contract_value
    FROM reservations r
    LEFT JOIN units u ON r.unit_id = u.unit_id
    LEFT JOIN buildings b ON u.building_id = b.building_id
    LEFT JOIN projects p ON b.project_id = p.project_id
    LEFT JOIN property_types pt ON u.property_type_id = pt.property_type_id
    LEFT JOIN customers c ON r.customer_id = c.customer_id
    LEFT JOIN opportunities opp ON r.opportunity_id = opp.opportunity_id
    LEFT JOIN users ag ON opp.assigned_user_id = ag.user_id
    LEFT JOIN (
        SELECT DISTINCT ON (reservation_id)
            contract_id,
            contract_number,
            contract_value,
            reservation_id
        FROM contracts
        WHERE reservation_id IS NOT NULL
        ORDER BY reservation_id, signed_at DESC NULLS LAST, contract_id DESC
    ) con ON r.reservation_id = con.reservation_id
"""

@router.get("/reservations", response_model=CollectionEnvelope[ReservationOut])
async def list_reservations(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
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

    if search:
        search_pattern = f"%{search}%"
        conditions.append(f"""(
            r.reservation_number ILIKE ${p_idx} OR
            u.unit_number ILIKE ${p_idx} OR
            c.first_name ILIKE ${p_idx} OR
            c.last_name ILIKE ${p_idx} OR
            c.company_name ILIKE ${p_idx} OR
            c.mobile ILIKE ${p_idx}
        )""")
        params.append(search_pattern)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    count_query = f"""
        SELECT count(*) 
        FROM reservations r
        LEFT JOIN units u ON r.unit_id = u.unit_id
        LEFT JOIN customers c ON r.customer_id = c.customer_id
        WHERE {where_clause}
    """
    total = await conn.fetchval(count_query, *params)

    query = f"""
        {RESERVATION_SELECT_QUERY}
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

@router.get("/reservations/{reservation_id}", response_model=ResponseEnvelope[ReservationOut])
async def get_reservation_detail(reservation_id: str, conn: asyncpg.Connection = Depends(get_db)):
    row = await conn.fetchrow(f"{RESERVATION_SELECT_QUERY} WHERE r.reservation_id = $1", reservation_id)
    if not row:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return ResponseEnvelope(data=ReservationOut(**dict(row)), meta=BaseMeta())

@router.post("/reservations", response_model=ResponseEnvelope[ReservationOut], status_code=status.HTTP_201_CREATED)
async def create_reservation(
    payload: ReservationCreateIn,
    conn: asyncpg.Connection = Depends(get_db),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
):
    cust_id = payload.customer_id
    if not cust_id:
        cust_id = await conn.fetchval("SELECT customer_id FROM opportunities WHERE opportunity_id = $1", payload.opportunity_id)
    if not cust_id:
        raise HTTPException(status_code=400, detail="Customer ID is required or must be linked to opportunity.")

    try:
        async with conn.transaction():
            res = await WorkflowEngine.create_unit_reservation(
                conn=conn,
                opportunity_id=payload.opportunity_id,
                unit_id=payload.unit_id,
                customer_id=cust_id,
                deposit_amount=payload.deposit_amount,
                expiry_hours=payload.expiry_hours,
                user_id=x_user_id,
                notes=payload.notes
            )
            reservation_id = res["reservation_id"]
            row = await conn.fetchrow(f"{RESERVATION_SELECT_QUERY} WHERE r.reservation_id = $1", reservation_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    return ResponseEnvelope(data=ReservationOut(**dict(row)), meta=BaseMeta())

@router.post("/reservations/{reservation_id}/verify-deposit", response_model=ResponseEnvelope[dict])
async def verify_reservation_deposit(
    reservation_id: str,
    payload: ReservationDepositVerifyIn,
    conn: asyncpg.Connection = Depends(get_db),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
):
    try:
        async with conn.transaction():
            res = await WorkflowEngine.verify_reservation_deposit(
                conn=conn,
                reservation_id=reservation_id,
                amount_received=payload.amount_received,
                payment_method=payload.payment_method,
                payment_ref=payload.payment_reference,
                user_id=x_user_id,
                notes=payload.notes
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ResponseEnvelope(data=res, meta=BaseMeta())


@router.post("/reservations/process-expired", response_model=ResponseEnvelope[dict])
async def process_expired_reservations_endpoint(
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    Scans for reservations that have expired or are approaching expiration.
    - If past expiry without confirmed deposit: marks reservation EXPIRED and releases unit to AVAILABLE.
    - If within 12h of expiry: generates urgent TASK_RESERVATION_EXPIRY_REVIEW task for Branch Manager.
    """
    res = await WorkflowEngine.process_expired_reservations(conn)
    return ResponseEnvelope(data=res, meta=BaseMeta())




# =============================================================
# Offers Management (offers table)
# =============================================================
@router.get("/offers", response_model=CollectionEnvelope[OfferOut])
@router.get("/sales/offers", response_model=CollectionEnvelope[OfferOut], include_in_schema=False)
async def list_offers(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    opportunity_id: Optional[str] = None,
    unit_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"o.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if opportunity_id:
        conditions.append(f"o.opportunity_id = ${p_idx}")
        params.append(opportunity_id)
        p_idx += 1

    if unit_id:
        conditions.append(f"o.unit_id = ${p_idx}")
        params.append(unit_id)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"SELECT count(*) FROM offers o WHERE {where_clause}", *params)

    query = f"""
        SELECT 
            o.offer_id,
            o.opportunity_id,
            o.unit_id,
            u.unit_number,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            CAST(o.offer_amount AS FLOAT) AS offer_amount,
            o.submitted_at,
            o.valid_until,
            o.status
        FROM offers o
        LEFT JOIN units u ON o.unit_id = u.unit_id
        LEFT JOIN opportunities opp ON o.opportunity_id = opp.opportunity_id
        LEFT JOIN customers c ON opp.customer_id = c.customer_id
        WHERE {where_clause}
        ORDER BY o.submitted_at DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [OfferOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.get("/offers/{offer_id}", response_model=ResponseEnvelope[OfferOut])
async def get_offer(offer_id: str, conn: asyncpg.Connection = Depends(get_db)):
    row = await conn.fetchrow("""
        SELECT 
            o.offer_id,
            o.opportunity_id,
            o.unit_id,
            u.unit_number,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            CAST(o.offer_amount AS FLOAT) AS offer_amount,
            o.submitted_at,
            o.valid_until,
            o.status
        FROM offers o
        LEFT JOIN units u ON o.unit_id = u.unit_id
        LEFT JOIN opportunities opp ON o.opportunity_id = opp.opportunity_id
        LEFT JOIN customers c ON opp.customer_id = c.customer_id
        WHERE o.offer_id = $1
    """, offer_id)
    if not row:
        raise HTTPException(status_code=404, detail="Offer not found")
    return ResponseEnvelope(data=OfferOut(**dict(row)), meta=BaseMeta())

@router.post("/offers", response_model=ResponseEnvelope[OfferOut], status_code=status.HTTP_201_CREATED)
async def create_offer(
    payload: OfferCreateIn,
    conn: asyncpg.Connection = Depends(get_db),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
):
    try:
        res = await WorkflowEngine.submit_commercial_offer(
            conn=conn,
            opportunity_id=payload.opportunity_id,
            unit_id=payload.unit_id,
            offer_amount=payload.offer_amount,
            valid_until=payload.valid_until,
            user_id=x_user_id
        )
        offer_id = res["offer_id"]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    row = await conn.fetchrow("""
        SELECT 
            o.offer_id,
            o.opportunity_id,
            o.unit_id,
            u.unit_number,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            CAST(o.offer_amount AS FLOAT) AS offer_amount,
            o.submitted_at,
            o.valid_until,
            o.status
        FROM offers o
        LEFT JOIN units u ON o.unit_id = u.unit_id
        LEFT JOIN opportunities opp ON o.opportunity_id = opp.opportunity_id
        LEFT JOIN customers c ON opp.customer_id = c.customer_id
        WHERE o.offer_id = $1
    """, offer_id)
    return ResponseEnvelope(data=OfferOut(**dict(row)), meta=BaseMeta())

@router.post("/offers/{offer_id}/record-decision", response_model=ResponseEnvelope[dict])
async def record_offer_decision(
    offer_id: str,
    payload: OfferDecisionIn,
    conn: asyncpg.Connection = Depends(get_db),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
):
    try:
        res = await WorkflowEngine.record_offer_decision(
            conn=conn,
            offer_id=offer_id,
            decision=payload.decision,
            counter_amount=payload.counter_amount,
            notes=payload.notes,
            user_id=x_user_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ResponseEnvelope(data=res, meta=BaseMeta())

@router.patch("/offers/{offer_id}", response_model=ResponseEnvelope[OfferOut])
async def update_offer(offer_id: str, payload: OfferUpdateIn, conn: asyncpg.Connection = Depends(get_db)):
    updates = []
    params = []
    p_idx = 1
    if payload.offer_amount is not None:
        updates.append(f"offer_amount = ${p_idx}")
        params.append(payload.offer_amount)
        p_idx += 1
    if payload.valid_until is not None:
        updates.append(f"valid_until = ${p_idx}")
        params.append(payload.valid_until)
        p_idx += 1
    if payload.status is not None:
        updates.append(f"status = ${p_idx}")
        params.append(payload.status.upper())
        p_idx += 1
    if updates:
        params.append(offer_id)
        await conn.execute(f"UPDATE offers SET {', '.join(updates)} WHERE offer_id = ${p_idx}", *params)

    row = await conn.fetchrow("""
        SELECT 
            o.offer_id,
            o.opportunity_id,
            o.unit_id,
            u.unit_number,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            CAST(o.offer_amount AS FLOAT) AS offer_amount,
            o.submitted_at,
            o.valid_until,
            o.status
        FROM offers o
        LEFT JOIN units u ON o.unit_id = u.unit_id
        LEFT JOIN opportunities opp ON o.opportunity_id = opp.opportunity_id
        LEFT JOIN customers c ON opp.customer_id = c.customer_id
        WHERE o.offer_id = $1
    """, offer_id)
    if not row:
        raise HTTPException(status_code=404, detail="Offer not found")
    return ResponseEnvelope(data=OfferOut(**dict(row)), meta=BaseMeta())


# =============================================================
# Opportunity Units Mapping (opportunity_units table)
# =============================================================
@router.get("/opportunities/{opp_id}/units", response_model=CollectionEnvelope[OpportunityUnitOut])
@router.get("/sales/opportunities/{opp_id}/units", response_model=CollectionEnvelope[OpportunityUnitOut], include_in_schema=False)
async def list_opportunity_units(opp_id: str, conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch("""
        SELECT 
            ou.opportunity_id,
            ou.unit_id,
            u.unit_number,
            ou.is_primary,
            CAST(ou.offered_price AS FLOAT) AS offered_price
        FROM opportunity_units ou
        JOIN units u ON ou.unit_id = u.unit_id
        WHERE ou.opportunity_id = $1
        ORDER BY ou.is_primary DESC, u.unit_number ASC
    """, opp_id)
    data = [OpportunityUnitOut(**dict(r)) for r in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.post("/opportunities/{opp_id}/units", response_model=ResponseEnvelope[OpportunityUnitOut], status_code=status.HTTP_201_CREATED)
@router.post("/sales/opportunities/{opp_id}/units", response_model=ResponseEnvelope[OpportunityUnitOut], include_in_schema=False, status_code=status.HTTP_201_CREATED)
async def add_opportunity_unit(opp_id: str, payload: OpportunityUnitCreateIn, conn: asyncpg.Connection = Depends(get_db)):
    await conn.execute("""
        INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (opportunity_id, unit_id) DO UPDATE 
        SET is_primary = EXCLUDED.is_primary, offered_price = EXCLUDED.offered_price
    """, opp_id, payload.unit_id, payload.is_primary, payload.offered_price)

    row = await conn.fetchrow("""
        SELECT 
            ou.opportunity_id,
            ou.unit_id,
            u.unit_number,
            ou.is_primary,
            CAST(ou.offered_price AS FLOAT) AS offered_price
        FROM opportunity_units ou
        JOIN units u ON ou.unit_id = u.unit_id
        WHERE ou.opportunity_id = $1 AND ou.unit_id = $2
    """, opp_id, payload.unit_id)
    return ResponseEnvelope(data=OpportunityUnitOut(**dict(row)), meta=BaseMeta())

@router.delete("/opportunities/{opp_id}/units/{unit_id}", response_model=ResponseEnvelope[dict])
@router.delete("/sales/opportunities/{opp_id}/units/{unit_id}", response_model=ResponseEnvelope[dict], include_in_schema=False)
async def remove_opportunity_unit(opp_id: str, unit_id: str, conn: asyncpg.Connection = Depends(get_db)):
    await conn.execute("DELETE FROM opportunity_units WHERE opportunity_id = $1 AND unit_id = $2", opp_id, unit_id)
    return ResponseEnvelope(data={"deleted": True, "opportunity_id": opp_id, "unit_id": unit_id}, meta=BaseMeta())


class PresentUnitsIn(BaseModel):
    unit_ids: Optional[list[str]] = None
    notes: Optional[str] = None

@router.post("/opportunities/{opp_id}/present-units", response_model=ResponseEnvelope[dict])
@router.post("/sales/opportunities/{opp_id}/present-units", response_model=ResponseEnvelope[dict], include_in_schema=False)
async def present_opportunity_units(
    opp_id: str,
    payload: Optional[PresentUnitsIn] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    user_id = x_user_id or "user-51"
    unit_ids = payload.unit_ids if payload else None
    notes = payload.notes if payload else None
    async with conn.transaction():
        res = await WorkflowEngine.present_opportunity_properties(
            conn=conn,
            user_id=user_id,
            opportunity_id=opp_id,
            unit_ids=unit_ids,
            notes=notes
        )
    return ResponseEnvelope(data=res, meta=BaseMeta())



