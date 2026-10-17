from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, status, Header
import asyncpg
from app.database import get_db, get_next_id
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.routers.auth import check_user_scope_override
from app.schemas.properties import (
    ProjectOut, UnitOut, UnitStatusUpdate, UnitCreateIn, UnitUpdateIn,
    BuildingOut, ProjectCreateIn, BuildingCreateIn
)

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
        u.property_type_id,
        pt.name_en AS property_type_name,
        pt.name_en AS property_type_name_en,
        pt.name_ar AS property_type_name_ar,
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
    city_id: Optional[str] = None,
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

@router.post("/projects", response_model=ResponseEnvelope[ProjectOut], status_code=status.HTTP_201_CREATED)
async def create_project(payload: ProjectCreateIn, conn: asyncpg.Connection = Depends(get_db)):
    org_id = await conn.fetchval("SELECT organization_id FROM organizations LIMIT 1")
    if not org_id:
        raise HTTPException(status_code=500, detail="No active organization found")

    project_id = await get_next_id(conn, "projects", "project")
    await conn.execute("""
        INSERT INTO projects (
            project_id, organization_id, name_ar, name_en, developer_customer_id,
            city_id, status, start_date, completion_date
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9
        )
    """, project_id, org_id, payload.name_ar.strip(), payload.name_en.strip(), payload.developer_customer_id,
         payload.city_id, (payload.status or "ACTIVE").upper(), payload.start_date, payload.completion_date)

    query = """
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
        WHERE p.project_id = $1
    """
    row = await conn.fetchrow(query, project_id)
    return ResponseEnvelope(data=ProjectOut(**dict(row)), meta=BaseMeta())

@router.get("/units", response_model=CollectionEnvelope[UnitOut])
async def list_units(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    project_id: Optional[str] = None,
    building_id: Optional[str] = None,
    property_type_id: Optional[str] = None,
    bedrooms: Optional[int] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    assigned_user_id: Optional[str] = None,
    search: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if assigned_user_id:
        conditions.append(f"u.assigned_user_id = ${p_idx}")
        params.append(assigned_user_id)
        p_idx += 1

    if status_filter:
        conditions.append(f"u.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if project_id:
        conditions.append(f"b.project_id = ${p_idx}")
        params.append(project_id)
        p_idx += 1

    if building_id:
        conditions.append(f"u.building_id = ${p_idx}")
        params.append(building_id)
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
        conditions.append(f"(u.unit_number ILIKE ${p_idx} OR p.name_en ILIKE ${p_idx} OR p.name_ar ILIKE ${p_idx} OR u.unit_id ILIKE ${p_idx})")
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
async def get_unit(unit_id: str, conn: asyncpg.Connection = Depends(get_db)):
    query = f"{UNIT_SELECT_QUERY} WHERE u.unit_id = $1"
    row = await conn.fetchrow(query, unit_id)
    if not row:
        raise HTTPException(status_code=404, detail="Unit not found")
    return ResponseEnvelope(data=UnitOut(**dict(row)), meta=BaseMeta())

@router.post("/units/{unit_id}/status", response_model=ResponseEnvelope[UnitOut])
async def update_unit_status(unit_id: str, payload: UnitStatusUpdate, conn: asyncpg.Connection = Depends(get_db)):
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

@router.get("/buildings", response_model=CollectionEnvelope[BuildingOut])
async def list_buildings(
    project_id: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    query = """
        SELECT 
            b.building_id,
            b.project_id,
            p.name_ar AS project_name_ar,
            p.name_en AS project_name_en,
            b.building_code,
            b.name AS building_name,
            b.floors_count
        FROM buildings b
        LEFT JOIN projects p ON b.project_id = p.project_id
    """
    params = []
    if project_id:
        query += " WHERE b.project_id = $1"
        params.append(project_id)
    query += " ORDER BY b.building_code"
    rows = await conn.fetch(query, *params)
    data = [BuildingOut(**dict(r)) for r in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.post("/buildings", response_model=ResponseEnvelope[BuildingOut], status_code=status.HTTP_201_CREATED)
async def create_building(payload: BuildingCreateIn, conn: asyncpg.Connection = Depends(get_db)):
    # Verify project exists
    prj = await conn.fetchrow("SELECT project_id FROM projects WHERE project_id = $1", payload.project_id)
    if not prj:
        raise HTTPException(status_code=400, detail="Invalid project_id: project does not exist.")

    # Check if building_code already exists in this project
    existing = await conn.fetchval(
        "SELECT building_id FROM buildings WHERE project_id = $1 AND LOWER(TRIM(building_code)) = LOWER(TRIM($2))",
        payload.project_id, payload.building_code
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Building code '{payload.building_code}' already exists in this project.")

    building_id = await get_next_id(conn, "buildings", "building")
    await conn.execute("""
        INSERT INTO buildings (
            building_id, project_id, building_code, name, floors_count
        ) VALUES (
            $1, $2, $3, $4, $5
        )
    """, building_id, payload.project_id, payload.building_code.strip(), payload.name.strip() if payload.name else None, payload.floors_count)

    row = await conn.fetchrow("""
        SELECT 
            b.building_id,
            b.project_id,
            p.name_ar AS project_name_ar,
            p.name_en AS project_name_en,
            b.building_code,
            b.name AS building_name,
            b.floors_count
        FROM buildings b
        LEFT JOIN projects p ON b.project_id = p.project_id
        WHERE b.building_id = $1
    """, building_id)
    return ResponseEnvelope(data=BuildingOut(**dict(row)), meta=BaseMeta())

@router.post("/units", response_model=ResponseEnvelope[UnitOut], status_code=status.HTTP_201_CREATED)
async def create_unit(
    payload: UnitCreateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    # Verify building exists
    bld = await conn.fetchrow("SELECT building_id FROM buildings WHERE building_id = $1", payload.building_id)
    if not bld:
        raise HTTPException(status_code=400, detail="Invalid building_id: building does not exist.")

    # Check if unit_number already exists in this building
    existing = await conn.fetchval(
        "SELECT unit_id FROM units WHERE building_id = $1 AND LOWER(TRIM(unit_number)) = LOWER(TRIM($2))",
        payload.building_id, payload.unit_number
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Unit number '{payload.unit_number}' already exists in this building.")

    # If owner customer passed, verify customer exists
    if payload.owner_customer_id:
        cust = await conn.fetchrow("SELECT customer_id FROM customers WHERE customer_id = $1", payload.owner_customer_id)
        if not cust:
            raise HTTPException(status_code=400, detail=f"Customer '{payload.owner_customer_id}' not found.")

    # If assigned user passed, verify user exists
    if payload.assigned_user_id:
        u = await conn.fetchrow("SELECT user_id FROM users WHERE user_id = $1", payload.assigned_user_id)
        if not u:
            raise HTTPException(status_code=400, detail=f"User '{payload.assigned_user_id}' not found.")

    unit_id = await get_next_id(conn, "units", "unit")
    st = (payload.status or "AVAILABLE").upper()

    await conn.execute("""
        INSERT INTO units (
            unit_id, building_id, unit_number, property_type_id, floor_no,
            area_sqm, bedrooms, bathrooms, parking_spaces, orientation,
            asking_price, rent_price, status, owner_customer_id, assigned_user_id
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9, $10,
            $11, $12, $13, $14, $15
        )
    """, unit_id, payload.building_id, payload.unit_number.strip(), payload.property_type_id, payload.floor_no,
         payload.area_sqm, payload.bedrooms, payload.bathrooms, payload.parking_spaces, payload.orientation,
         payload.asking_price, payload.rent_price, st, payload.owner_customer_id, payload.assigned_user_id
    )

    row = await conn.fetchrow(f"{UNIT_SELECT_QUERY} WHERE u.unit_id = $1", unit_id)
    return ResponseEnvelope(data=UnitOut(**dict(row)), meta=BaseMeta())

@router.put("/units/{unit_id}", response_model=ResponseEnvelope[UnitOut])
async def update_unit(
    unit_id: str,
    payload: UnitUpdateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    current = await conn.fetchrow("SELECT unit_id, building_id, status FROM units WHERE unit_id = $1", unit_id)
    if not current:
        raise HTTPException(status_code=404, detail="Unit not found")

    target_bld_id = payload.building_id or current["building_id"]
    if payload.unit_number:
        existing = await conn.fetchval(
            "SELECT unit_id FROM units WHERE building_id = $1 AND LOWER(TRIM(unit_number)) = LOWER(TRIM($2)) AND unit_id != $3",
            target_bld_id, payload.unit_number, unit_id
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"Unit number '{payload.unit_number}' already exists in this building.")

    if payload.owner_customer_id:
        cust = await conn.fetchrow("SELECT customer_id FROM customers WHERE customer_id = $1", payload.owner_customer_id)
        if not cust:
            raise HTTPException(status_code=400, detail=f"Customer '{payload.owner_customer_id}' not found.")

    if payload.assigned_user_id:
        u = await conn.fetchrow("SELECT user_id FROM users WHERE user_id = $1", payload.assigned_user_id)
        if not u:
            raise HTTPException(status_code=400, detail=f"User '{payload.assigned_user_id}' not found.")

    updates = []
    params = []
    p_idx = 1

    field_map = {
        "building_id": payload.building_id,
        "unit_number": payload.unit_number.strip() if payload.unit_number else None,
        "property_type_id": payload.property_type_id,
        "floor_no": payload.floor_no,
        "area_sqm": payload.area_sqm,
        "bedrooms": payload.bedrooms,
        "bathrooms": payload.bathrooms,
        "parking_spaces": payload.parking_spaces,
        "orientation": payload.orientation,
        "asking_price": payload.asking_price,
        "rent_price": payload.rent_price,
        "status": payload.status.upper() if payload.status else None,
        "owner_customer_id": payload.owner_customer_id,
        "assigned_user_id": payload.assigned_user_id,
    }

    payload_dict = payload.model_dump(exclude_unset=True)
    for k in payload_dict.keys():
        if k in field_map:
            val = field_map[k]
            updates.append(f"{k} = ${p_idx}")
            params.append(val)
            p_idx += 1

    if updates:
        updates.append("updated_at = now()")
        params.append(unit_id)
        update_query = f"UPDATE units SET {', '.join(updates)} WHERE unit_id = ${p_idx}"
        await conn.execute(update_query, *params)

    row = await conn.fetchrow(f"{UNIT_SELECT_QUERY} WHERE u.unit_id = $1", unit_id)
    return ResponseEnvelope(data=UnitOut(**dict(row)), meta=BaseMeta())

@router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_unit(unit_id: str, conn: asyncpg.Connection = Depends(get_db)):
    # Check if unit has active tenancies or lease records
    has_tenancies = await conn.fetchval("SELECT count(*) FROM tenancies WHERE unit_id = $1", unit_id)
    if has_tenancies > 0:
        raise HTTPException(status_code=400, detail="Cannot delete unit: associated tenancy/lease records exist.")
    
    # Check listings
    has_listings = await conn.fetchval("SELECT count(*) FROM listings WHERE unit_id = $1", unit_id)
    if has_listings > 0:
        raise HTTPException(status_code=400, detail="Cannot delete unit: associated listings exist.")

    res = await conn.execute("DELETE FROM units WHERE unit_id = $1", unit_id)
    if res == "DELETE 0":
        raise HTTPException(status_code=404, detail="Unit not found")


