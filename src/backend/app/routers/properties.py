from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException, status
import asyncpg
from app.database import get_db
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.schemas.properties import ProjectOut, UnitOut, UnitStatusUpdate

router = APIRouter(tags=["Properties & Inventory"])

UNIT_SELECT_QUERY = """
    SELECT 
        u.unit_id,
        u.building_id,
        b.project_id,
        p.name_ar AS project_name_ar,
        p.name_en AS project_name_en,
        u.unit_number,
        u.floor_no,
        CAST(u.area_sqm AS FLOAT) AS area_sqm,
        u.bedrooms,
        u.bathrooms,
        u.parking_spaces,
        u.orientation,
        pt.name_en AS property_type_name,
        CAST(u.asking_price AS FLOAT) AS asking_price,
        CAST(u.rent_price AS FLOAT) AS rent_price,
        u.status,
        u.owner_customer_id,
        COALESCE(oc.first_name || ' ' || oc.last_name, oc.company_name) AS owner_name,
        u.assigned_user_id,
        usr.full_name AS assigned_user_name,
        u.created_at,
        u.updated_at
    FROM units u
    LEFT JOIN buildings b ON u.building_id = b.building_id
    LEFT JOIN projects p ON b.project_id = p.project_id
    LEFT JOIN property_types pt ON u.property_type_id = pt.property_type_id
    LEFT JOIN customers oc ON u.owner_customer_id = oc.customer_id
    LEFT JOIN users usr ON u.assigned_user_id = usr.user_id
"""

@router.get("/projects", response_model=CollectionEnvelope[ProjectOut])
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    city_id: Optional[UUID] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"p.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if city_id:
        conditions.append(f"p.city_id = ${p_idx}")
        params.append(city_id)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"SELECT count(*) FROM projects p WHERE {where_clause}", *params)

    query = f"""
        SELECT 
            p.project_id,
            p.organization_id,
            p.name_ar,
            p.name_en,
            c.name_en AS city_name,
            p.status,
            p.start_date,
            p.completion_date
        FROM projects p
        LEFT JOIN cities c ON p.city_id = c.city_id
        WHERE {where_clause}
        ORDER BY p.name_en
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [ProjectOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.get("/units", response_model=CollectionEnvelope[UnitOut])
async def list_units(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    project_id: Optional[UUID] = None,
    property_type_id: Optional[UUID] = None,
    bedrooms: Optional[int] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"u.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if project_id:
        conditions.append(f"b.project_id = ${p_idx}")
        params.append(project_id)
        p_idx += 1

    if property_type_id:
        conditions.append(f"u.property_type_id = ${p_idx}")
        params.append(property_type_id)
        p_idx += 1

    if bedrooms is not None:
        conditions.append(f"u.bedrooms = ${p_idx}")
        params.append(bedrooms)
        p_idx += 1

    if min_price is not None:
        conditions.append(f"(u.asking_price >= ${p_idx} OR u.rent_price >= ${p_idx})")
        params.append(min_price)
        p_idx += 1

    if max_price is not None:
        conditions.append(f"(u.asking_price <= ${p_idx} OR u.rent_price <= ${p_idx})")
        params.append(max_price)
        p_idx += 1

    if search:
        conditions.append(f"(u.unit_number ILIKE ${p_idx} OR p.name_en ILIKE ${p_idx} OR p.name_ar ILIKE ${p_idx})")
        params.append(f"%{search}%")
        p_idx += 1

    where_clause = " AND ".join(conditions)
    count_query = f"""
        SELECT count(*) 
        FROM units u 
        LEFT JOIN buildings b ON u.building_id = b.building_id
        LEFT JOIN projects p ON b.project_id = p.project_id
        WHERE {where_clause}
    """
    total = await conn.fetchval(count_query, *params)

    query = f"""
        {UNIT_SELECT_QUERY}
        WHERE {where_clause}
        ORDER BY p.name_en, u.unit_number
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [UnitOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.get("/units/{unit_id}", response_model=ResponseEnvelope[UnitOut])
async def get_unit(unit_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    query = f"{UNIT_SELECT_QUERY} WHERE u.unit_id = $1"
    row = await conn.fetchrow(query, unit_id)
    if not row:
        raise HTTPException(status_code=404, detail="Unit not found")
    return ResponseEnvelope(data=UnitOut(**dict(row)), meta=BaseMeta())

@router.post("/units/{unit_id}/status", response_model=ResponseEnvelope[UnitOut])
async def update_unit_status(unit_id: UUID, payload: UnitStatusUpdate, conn: asyncpg.Connection = Depends(get_db)):
    async with conn.transaction():
        # Get old status
        old_status = await conn.fetchval("SELECT status FROM units WHERE unit_id = $1", unit_id)
        if not old_status:
            raise HTTPException(status_code=404, detail="Unit not found")
        
        # Update unit status
        await conn.execute("UPDATE units SET status = $1, updated_at = now() WHERE unit_id = $2", payload.status.upper(), unit_id)
        
        # Log to unit_status_history
        user_id = await conn.fetchval("SELECT user_id FROM users LIMIT 1")
        await conn.execute(
            """
            INSERT INTO unit_status_history (unit_id, from_status, to_status, changed_by_user_id, notes, effective_at)
            VALUES ($1, $2, $3, $4, $5, now())
            """,
            unit_id, old_status, payload.status.upper(), user_id, payload.reason or "Status changed via API"
        )

    query = f"{UNIT_SELECT_QUERY} WHERE u.unit_id = $1"
    row = await conn.fetchrow(query, unit_id)
    return ResponseEnvelope(data=UnitOut(**dict(row)), meta=BaseMeta())

