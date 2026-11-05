from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, status, Header
import asyncpg
from app.database import get_db, get_next_id
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.routers.auth import check_user_scope_override
from app.schemas.properties import (
    ProjectOut, UnitOut, UnitStatusUpdate, UnitCreateIn, UnitUpdateIn,
    BuildingOut, ProjectCreateIn, BuildingCreateIn, ProjectUpdateIn, BuildingUpdateIn
)

router = APIRouter(tags=["Properties & Inventory"])

UNIT_SELECT_QUERY = """
    SELECT 
        u.unit_id,
        u.building_id,
        b.building_code,
        b.name AS building_name,
        COALESCE(u.project_id, b.project_id) AS project_id,
        COALESCE(p_direct.name_ar, p_bld.name_ar) AS project_name_ar,
        COALESCE(p_direct.name_en, p_bld.name_en) AS project_name_en,
        COALESCE(p_direct.city_id, p_bld.city_id) AS city_id,
        c.name_ar AS city_name_ar,
        c.name_en AS city_name_en,
        COALESCE(c.name_ar, c.name_en) AS city_name,
        u.unit_number,
        u.floor_no,
        u.total_floors,
        b.floors_count AS building_floors_count,
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
        CAST(u.annual_operating_expenses AS FLOAT) AS annual_operating_expenses,
        CAST(u.annual_vacancy_rate AS FLOAT) AS annual_vacancy_rate,
        u.investment_notes,
        COALESCE(u.listing_purpose, 'ALL') AS listing_purpose,
        u.status,
        u.owner_customer_id,
        COALESCE(oc.first_name || ' ' || oc.last_name, oc.company_name) AS owner_name,
        oc.mobile AS owner_mobile,
        u.assigned_user_id,
        usr.full_name AS assigned_user_name,
        u.created_at,
        u.updated_at
    FROM units u
    LEFT JOIN buildings b ON u.building_id = b.building_id
    LEFT JOIN projects p_bld ON b.project_id = p_bld.project_id
    LEFT JOIN projects p_direct ON u.project_id = p_direct.project_id
    LEFT JOIN property_types pt ON u.property_type_id = pt.property_type_id
    LEFT JOIN customers oc ON u.owner_customer_id = oc.customer_id
    LEFT JOIN users usr ON u.assigned_user_id = usr.user_id
    LEFT JOIN cities c ON COALESCE(p_direct.city_id, p_bld.city_id) = c.city_id
"""

SINGLE_PROJECT_QUERY = """
    SELECT 
        p.project_id,
        p.organization_id,
        p.name_ar,
        p.name_en,
        p.developer_customer_id,
        COALESCE(dev.first_name || ' ' || dev.last_name, dev.company_name) AS developer_name,
        c.name_en AS city_name,
        c.name_ar AS city_name_ar,
        p.status,
        p.start_date,
        p.completion_date,
        p.completion_date AS end_date,
        (SELECT COUNT(*) FROM buildings b WHERE b.project_id = p.project_id)::int AS buildings_count,
        (SELECT COUNT(*) FROM units u WHERE u.project_id = p.project_id OR u.building_id IN (SELECT b.building_id FROM buildings b WHERE b.project_id = p.project_id))::int AS units_count
    FROM projects p
    LEFT JOIN cities c ON p.city_id = c.city_id
    LEFT JOIN customers dev ON p.developer_customer_id = dev.customer_id
    WHERE p.project_id = $1
"""

SINGLE_BUILDING_QUERY = """
    SELECT 
        b.building_id,
        b.project_id,
        p.name_ar AS project_name_ar,
        p.name_en AS project_name_en,
        b.building_code,
        b.name AS building_name,
        b.floors_count,
        (SELECT count(*) FROM units u WHERE u.building_id = b.building_id)::int AS units_count
    FROM buildings b
    LEFT JOIN projects p ON b.project_id = p.project_id
    WHERE b.building_id = $1
"""

async def verify_management_delete_permission(conn: asyncpg.Connection, x_user_id: Optional[str]):
    if not x_user_id:
        return
    roles = await conn.fetch(
        """
        SELECT r.role_code 
        FROM user_roles ur 
        JOIN roles r ON ur.role_id = r.role_id 
        WHERE ur.user_id = $1
        """,
        x_user_id
    )
    role_codes = set(r["role_code"].upper() for r in roles)
    allowed_roles = {"GENERAL_MANAGER", "SYS_ADMIN", "ADMIN", "BRANCH_MANAGER", "SALES_MANAGER"}
    if not (role_codes & allowed_roles):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="عملية الحذف محصورة بمدراء الفروع والمدير العام فقط. ليس لديك الصلاحية لحذف هذا السجل."
        )


@router.get("/projects", response_model=CollectionEnvelope[ProjectOut])
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=200),
    status_filter: Optional[str] = Query(None, alias="status"),
    city_id: Optional[str] = None,
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter and status_filter.upper() != "ALL":
        conditions.append(f"p.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if city_id and city_id.strip():
        conditions.append(f"p.city_id = ${p_idx}")
        params.append(city_id.strip())
        p_idx += 1

    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        conditions.append(f"(LOWER(p.name_ar) LIKE ${p_idx} OR LOWER(p.name_en) LIKE ${p_idx} OR LOWER(p.project_id) LIKE ${p_idx} OR LOWER(c.name_en) LIKE ${p_idx} OR LOWER(c.name_ar) LIKE ${p_idx})")
        params.append(term)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"""
        SELECT count(*) 
        FROM projects p 
        LEFT JOIN cities c ON p.city_id = c.city_id
        WHERE {where_clause}
    """, *params)

    query = f"""
        SELECT 
            p.project_id,
            p.organization_id,
            p.name_ar,
            p.name_en,
            p.developer_customer_id,
            COALESCE(dev.first_name || ' ' || dev.last_name, dev.company_name) AS developer_name,
            c.name_en AS city_name,
            c.name_ar AS city_name_ar,
            p.status,
            p.start_date,
            p.completion_date,
            p.completion_date AS end_date,
            (SELECT COUNT(*) FROM buildings b WHERE b.project_id = p.project_id)::int AS buildings_count,
            (SELECT COUNT(*) FROM units u WHERE u.project_id = p.project_id OR u.building_id IN (SELECT b.building_id FROM buildings b WHERE b.project_id = p.project_id))::int AS units_count
        FROM projects p
        LEFT JOIN cities c ON p.city_id = c.city_id
        LEFT JOIN customers dev ON p.developer_customer_id = dev.customer_id
        WHERE {where_clause}
        ORDER BY p.name_ar ASC, p.project_id ASC
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

    dev_id = payload.developer_customer_id
    if dev_id:
        dev_exists = await conn.fetchval("SELECT customer_id FROM customers WHERE customer_id = $1", dev_id)
        if not dev_exists:
            raise HTTPException(status_code=400, detail="المطور العقاري المحدد غير موجود في قاعدة بيانات العملاء.")

    project_id = await get_next_id(conn, "projects", "project")
    completion_date = payload.completion_date or payload.end_date

    await conn.execute("""
        INSERT INTO projects (
            project_id, organization_id, name_ar, name_en, developer_customer_id,
            city_id, status, start_date, completion_date
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9
        )
    """, project_id, org_id, payload.name_ar.strip(), payload.name_en.strip(), dev_id,
         payload.city_id, (payload.status or "ACTIVE").upper(), payload.start_date, completion_date)

    row = await conn.fetchrow(SINGLE_PROJECT_QUERY, project_id)
    return ResponseEnvelope(data=ProjectOut(**dict(row)), meta=BaseMeta())

@router.put("/projects/{project_id}", response_model=ResponseEnvelope[ProjectOut])
async def update_project(
    project_id: str,
    payload: ProjectUpdateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    current = await conn.fetchrow("SELECT * FROM projects WHERE project_id = $1", project_id)
    if not current:
        raise HTTPException(status_code=404, detail="Project not found")

    payload_dict = payload.model_dump(exclude_unset=True)
    if "end_date" in payload_dict and "completion_date" not in payload_dict:
        payload_dict["completion_date"] = payload_dict["end_date"]
    payload_dict.pop("end_date", None)

    if not payload_dict:
        row = await conn.fetchrow(SINGLE_PROJECT_QUERY, project_id)
        return ResponseEnvelope(data=ProjectOut(**dict(row)), meta=BaseMeta())

    if "developer_customer_id" in payload_dict and payload_dict["developer_customer_id"]:
        dev_exists = await conn.fetchval("SELECT customer_id FROM customers WHERE customer_id = $1", payload_dict["developer_customer_id"])
        if not dev_exists:
            raise HTTPException(status_code=400, detail="المطور العقاري المحدد غير موجود في قاعدة بيانات العملاء.")

    updates = []
    params = []
    p_idx = 1
    for k in ("name_ar", "name_en", "city_id", "status", "developer_customer_id", "start_date", "completion_date"):
        if k in payload_dict:
            v = payload_dict[k]
            updates.append(f"{k} = ${p_idx}")
            params.append(v.strip() if isinstance(v, str) else v)
            p_idx += 1

    if updates:
        params.append(project_id)
        await conn.execute(f"UPDATE projects SET {', '.join(updates)} WHERE project_id = ${p_idx}", *params)

    row = await conn.fetchrow(SINGLE_PROJECT_QUERY, project_id)
    return ResponseEnvelope(data=ProjectOut(**dict(row)), meta=BaseMeta())

@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_management_delete_permission(conn, x_user_id)

    current = await conn.fetchrow("SELECT project_id, name_ar, name_en FROM projects WHERE project_id = $1", project_id)
    if not current:
        raise HTTPException(status_code=404, detail="Project not found")

    bld_count = await conn.fetchval("SELECT count(*) FROM buildings WHERE project_id = $1", project_id) or 0
    unit_count = await conn.fetchval("SELECT count(*) FROM units WHERE project_id = $1", project_id) or 0
    camp_count = await conn.fetchval("SELECT count(*) FROM campaigns WHERE target_property_id = $1", project_id) or 0

    reasons = []
    if bld_count > 0:
        reasons.append(f"{bld_count} مبنى / عمارة تابعة")
    if unit_count > 0:
        reasons.append(f"{unit_count} وحدة عقارية مسجلة بالمشروع")
    if camp_count > 0:
        reasons.append(f"{camp_count} حملة تسويقية مرتبطة")

    if reasons:
        msg_ar = f"لا يمكن حذف المشروع العقاري '{current['name_ar'] or current['name_en']}' لارتباطه بالبيانات التالية: {', '.join(reasons)}. يرجى معالجة أو حذف السجلات التابعة أولاً."
        raise HTTPException(status_code=400, detail=msg_ar)

    await conn.execute("DELETE FROM projects WHERE project_id = $1", project_id)

@router.get("/units", response_model=CollectionEnvelope[UnitOut])
async def list_units(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    project_id: Optional[str] = None,
    building_id: Optional[str] = None,
    property_type_id: Optional[str] = None,
    property_type: Optional[str] = None,
    city_id: Optional[str] = None,
    city: Optional[str] = None,
    bedrooms: Optional[int] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    listing_purpose: Optional[str] = None,
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
        statuses = [s.strip().upper() for s in status_filter.split(",") if s.strip()]
        if len(statuses) == 1:
            conditions.append(f"u.status = ${p_idx}")
            params.append(statuses[0])
            p_idx += 1
        elif len(statuses) > 1:
            conditions.append(f"u.status = ANY(${p_idx}::varchar[])")
            params.append(statuses)
            p_idx += 1

    if project_id:
        conditions.append(f"COALESCE(u.project_id, b.project_id) = ${p_idx}")
        params.append(project_id)
        p_idx += 1

    if building_id:
        conditions.append(f"u.building_id = ${p_idx}")
        params.append(building_id)
        p_idx += 1

    if property_type_id and property_type_id.strip():
        conditions.append(f"u.property_type_id = ${p_idx}")
        params.append(property_type_id.strip())
        p_idx += 1
    elif property_type and property_type.strip():
        pt_term = f"%{property_type.strip()}%"
        conditions.append(f"(u.property_type_id = ${p_idx} OR pt.code ILIKE ${p_idx} OR pt.name_ar ILIKE ${p_idx} OR pt.name_en ILIKE ${p_idx})")
        params.append(pt_term)
        p_idx += 1

    if city_id and city_id.strip():
        conditions.append(f"COALESCE(p_direct.city_id, p_bld.city_id) = ${p_idx}")
        params.append(city_id.strip())
        p_idx += 1
    elif city and city.strip():
        c_term = f"%{city.strip()}%"
        conditions.append(f"(COALESCE(p_direct.city_id, p_bld.city_id) = ${p_idx} OR c.name_ar ILIKE ${p_idx} OR c.name_en ILIKE ${p_idx})")
        params.append(c_term)
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

    if listing_purpose:
        lp_val = listing_purpose.strip().upper()
        if lp_val != "ALL":
            conditions.append(f"(u.listing_purpose = ${p_idx} OR u.listing_purpose = 'ALL' OR u.listing_purpose IS NULL)")
            params.append(lp_val)
            p_idx += 1

    if search and search.strip():
        s_term = f"%{search.strip()}%"
        conditions.append(f"""(
            u.unit_number ILIKE ${p_idx} OR
            u.unit_id ILIKE ${p_idx} OR
            COALESCE(p_direct.name_en, p_bld.name_en) ILIKE ${p_idx} OR
            COALESCE(p_direct.name_ar, p_bld.name_ar) ILIKE ${p_idx} OR
            b.name ILIKE ${p_idx} OR
            b.building_code ILIKE ${p_idx} OR
            pt.name_ar ILIKE ${p_idx} OR
            pt.name_en ILIKE ${p_idx} OR
            pt.code ILIKE ${p_idx} OR
            c.name_ar ILIKE ${p_idx} OR
            c.name_en ILIKE ${p_idx}
        )""")
        params.append(s_term)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    count_query = f"""
        SELECT count(*) 
        FROM units u 
        LEFT JOIN buildings b ON u.building_id = b.building_id
        LEFT JOIN projects p_bld ON b.project_id = p_bld.project_id
        LEFT JOIN projects p_direct ON u.project_id = p_direct.project_id
        LEFT JOIN property_types pt ON u.property_type_id = pt.property_type_id
        LEFT JOIN cities c ON COALESCE(p_direct.city_id, p_bld.city_id) = c.city_id
        WHERE {where_clause}
    """
    total = await conn.fetchval(count_query, *params)

    query = f"""
        {UNIT_SELECT_QUERY}
        WHERE {where_clause}
        ORDER BY COALESCE(p_direct.name_en, p_bld.name_en), u.unit_number
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
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if project_id and project_id.strip():
        conditions.append(f"b.project_id = ${p_idx}")
        params.append(project_id.strip())
        p_idx += 1

    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        conditions.append(f"(LOWER(b.building_code) LIKE ${p_idx} OR LOWER(COALESCE(b.name, '')) LIKE ${p_idx} OR LOWER(b.building_id) LIKE ${p_idx} OR LOWER(COALESCE(p.name_ar, '')) LIKE ${p_idx} OR LOWER(COALESCE(p.name_en, '')) LIKE ${p_idx})")
        params.append(term)
        p_idx += 1

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT 
            b.building_id,
            b.project_id,
            p.name_ar AS project_name_ar,
            p.name_en AS project_name_en,
            b.building_code,
            b.name AS building_name,
            b.floors_count,
            (SELECT COUNT(*) FROM units u WHERE u.building_id = b.building_id)::int AS units_count
        FROM buildings b
        LEFT JOIN projects p ON b.project_id = p.project_id
        WHERE {where_clause}
        ORDER BY b.building_code ASC
    """
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
            b.floors_count,
            (SELECT count(*) FROM units u WHERE u.building_id = b.building_id)::int AS units_count
        FROM buildings b
        LEFT JOIN projects p ON b.project_id = p.project_id
        WHERE b.building_id = $1
    """, building_id)
    return ResponseEnvelope(data=BuildingOut(**dict(row)), meta=BaseMeta())

@router.put("/buildings/{building_id}", response_model=ResponseEnvelope[BuildingOut])
async def update_building(
    building_id: str,
    payload: BuildingUpdateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    current = await conn.fetchrow("SELECT * FROM buildings WHERE building_id = $1", building_id)
    if not current:
        raise HTTPException(status_code=404, detail="Building not found")

    payload_dict = payload.model_dump(exclude_unset=True)
    target_prj_id = payload.project_id if "project_id" in payload_dict else current["project_id"]
    target_code = payload.building_code.strip() if payload.building_code else current["building_code"]

    if "project_id" in payload_dict:
        prj = await conn.fetchrow("SELECT project_id FROM projects WHERE project_id = $1", target_prj_id)
        if not prj:
            raise HTTPException(status_code=400, detail="المشروع المحدد غير موجود.")

    # Duplicate code check within the project
    existing = await conn.fetchval(
        "SELECT building_id FROM buildings WHERE project_id = $1 AND LOWER(TRIM(building_code)) = LOWER(TRIM($2)) AND building_id != $3",
        target_prj_id, target_code, building_id
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Building code '{target_code}' already exists in this project.")

    updates = []
    params = []
    p_idx = 1
    for k in ("project_id", "building_code", "name", "floors_count"):
        if k in payload_dict:
            v = payload_dict[k]
            updates.append(f"{k} = ${p_idx}")
            params.append(v.strip() if isinstance(v, str) else v)
            p_idx += 1

    if updates:
        params.append(building_id)
        await conn.execute(f"UPDATE buildings SET {', '.join(updates)} WHERE building_id = ${p_idx}", *params)

    # If floors_count changed, sync units belonging to this building
    if "floors_count" in payload_dict and payload.floors_count is not None:
        await conn.execute("UPDATE units SET total_floors = $1 WHERE building_id = $2", payload.floors_count, building_id)

    row = await conn.fetchrow(SINGLE_BUILDING_QUERY, building_id)
    return ResponseEnvelope(data=BuildingOut(**dict(row)), meta=BaseMeta())

@router.delete("/buildings/{building_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_building(
    building_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_management_delete_permission(conn, x_user_id)

    current = await conn.fetchrow("SELECT building_id, building_code, name FROM buildings WHERE building_id = $1", building_id)
    if not current:
        raise HTTPException(status_code=404, detail="Building not found")

    unit_count = await conn.fetchval("SELECT count(*) FROM units WHERE building_id = $1", building_id) or 0
    camp_count = await conn.fetchval("SELECT count(*) FROM campaigns WHERE target_property_id = $1", building_id) or 0

    reasons = []
    if unit_count > 0:
        reasons.append(f"{unit_count} وحدة عقارية مسجلة تابعة للمبنى")
    if camp_count > 0:
        reasons.append(f"{camp_count} حملة تسويقية مرتبطة بالمبنى")

    if reasons:
        msg_ar = f"لا يمكن حذف المبنى '{current['building_code']}' لارتباطه بالبيانات التالية: {', '.join(reasons)}. يرجى معالجة أو نقل أو حذف الوحدات التابعة أولاً."
        raise HTTPException(status_code=400, detail=msg_ar)

    await conn.execute("DELETE FROM buildings WHERE building_id = $1", building_id)

@router.post("/units", response_model=ResponseEnvelope[UnitOut], status_code=status.HTTP_201_CREATED)
async def create_unit(
    payload: UnitCreateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    effective_project_id = payload.project_id
    effective_building_id = payload.building_id
    effective_total_floors = payload.total_floors

    # If building provided, verify it exists and inherit its project_id and floors_count
    if effective_building_id:
        bld = await conn.fetchrow("SELECT building_id, project_id, floors_count FROM buildings WHERE building_id = $1", effective_building_id)
        if not bld:
            raise HTTPException(status_code=400, detail="Invalid building_id: building does not exist.")
        if not effective_project_id:
            effective_project_id = bld["project_id"]

        # Enforce total_floors from building floors_count
        if bld["floors_count"] is not None:
            effective_total_floors = bld["floors_count"]
            if payload.floor_no is not None and payload.floor_no > bld["floors_count"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"رقم الطابق ({payload.floor_no}) لا يمكن أن يتجاوز إجمالي عدد طوابق المبنى ({bld['floors_count']})."
                )

        # Check if unit_number already exists in this building
        existing = await conn.fetchval(
            "SELECT unit_id FROM units WHERE building_id = $1 AND LOWER(TRIM(unit_number)) = LOWER(TRIM($2))",
            effective_building_id, payload.unit_number
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"Unit number '{payload.unit_number}' already exists in this building.")
    else:
        # Standalone property / Land without building
        if not effective_project_id:
            raise HTTPException(status_code=400, detail="يجب تحديد المشروع أو المبنى التابع له الوحدة العقارية.")

        prj = await conn.fetchrow("SELECT project_id FROM projects WHERE project_id = $1", effective_project_id)
        if not prj:
            raise HTTPException(status_code=400, detail="المشروع المحدد غير موجود.")

        # Check if unit_number already exists in this project without building
        existing = await conn.fetchval(
            "SELECT unit_id FROM units WHERE project_id = $1 AND building_id IS NULL AND LOWER(TRIM(unit_number)) = LOWER(TRIM($2))",
            effective_project_id, payload.unit_number
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"رقم الوحدة/القطعة '{payload.unit_number}' مسجل مسبقاً في هذا المشروع.")

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
    lp = (payload.listing_purpose or "ALL").upper()

    await conn.execute("""
        INSERT INTO units (
            unit_id, project_id, building_id, unit_number, property_type_id, floor_no, total_floors,
            area_sqm, bedrooms, bathrooms, parking_spaces, orientation,
            asking_price, rent_price, annual_operating_expenses, annual_vacancy_rate, investment_notes,
            listing_purpose, status, owner_customer_id, assigned_user_id
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7,
            $8, $9, $10, $11, $12,
            $13, $14, $15, $16, $17,
            $18, $19, $20, $21
        )
    """, unit_id, effective_project_id, effective_building_id, payload.unit_number.strip(), payload.property_type_id, payload.floor_no, effective_total_floors,
         payload.area_sqm, payload.bedrooms, payload.bathrooms, payload.parking_spaces, payload.orientation,
         payload.asking_price, payload.rent_price, payload.annual_operating_expenses, payload.annual_vacancy_rate, payload.investment_notes,
         lp, st, payload.owner_customer_id, payload.assigned_user_id
    )

    row = await conn.fetchrow(f"{UNIT_SELECT_QUERY} WHERE u.unit_id = $1", unit_id)
    return ResponseEnvelope(data=UnitOut(**dict(row)), meta=BaseMeta())

@router.put("/units/{unit_id}", response_model=ResponseEnvelope[UnitOut])
async def update_unit(
    unit_id: str,
    payload: UnitUpdateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    current = await conn.fetchrow("SELECT unit_id, building_id, project_id, unit_number, floor_no, total_floors, status FROM units WHERE unit_id = $1", unit_id)
    if not current:
        raise HTTPException(status_code=404, detail="Unit not found")

    payload_dict = payload.model_dump(exclude_unset=True)

    target_bld_id = payload.building_id if "building_id" in payload_dict else current["building_id"]
    target_prj_id = payload.project_id if "project_id" in payload_dict else current["project_id"]

    if target_bld_id:
        bld = await conn.fetchrow("SELECT building_id, project_id, floors_count FROM buildings WHERE building_id = $1", target_bld_id)
        if not bld:
            raise HTTPException(status_code=400, detail="Invalid building_id: building does not exist.")
        if not target_prj_id:
            target_prj_id = bld["project_id"]
    else:
        if not target_prj_id:
            raise HTTPException(status_code=400, detail="يجب تحديد المشروع للوحدة العقارية غير المرتبطة بمبنى.")
        prj = await conn.fetchrow("SELECT project_id FROM projects WHERE project_id = $1", target_prj_id)
        if not prj:
            raise HTTPException(status_code=400, detail="المشروع المحدد غير موجود.")

    check_num = payload.unit_number.strip() if payload.unit_number else current["unit_number"]
    if target_bld_id:
        existing = await conn.fetchval(
            "SELECT unit_id FROM units WHERE building_id = $1 AND LOWER(TRIM(unit_number)) = LOWER(TRIM($2)) AND unit_id != $3",
            target_bld_id, check_num, unit_id
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"Unit number '{check_num}' already exists in this building.")
    else:
        existing = await conn.fetchval(
            "SELECT unit_id FROM units WHERE project_id = $1 AND building_id IS NULL AND LOWER(TRIM(unit_number)) = LOWER(TRIM($2)) AND unit_id != $3",
            target_prj_id, check_num, unit_id
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"رقم الوحدة/القطعة '{check_num}' مسجل مسبقاً في هذا المشروع.")

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
        "project_id": target_prj_id,
        "building_id": payload.building_id if "building_id" in payload_dict else current["building_id"],
        "unit_number": payload.unit_number.strip() if payload.unit_number else None,
        "property_type_id": payload.property_type_id,
        "floor_no": payload.floor_no if "floor_no" in payload_dict else current["floor_no"],
        "total_floors": payload.total_floors if "total_floors" in payload_dict else current["total_floors"],
        "area_sqm": payload.area_sqm,
        "bedrooms": payload.bedrooms,
        "bathrooms": payload.bathrooms,
        "parking_spaces": payload.parking_spaces,
        "orientation": payload.orientation,
        "asking_price": payload.asking_price,
        "rent_price": payload.rent_price,
        "annual_operating_expenses": payload.annual_operating_expenses,
        "annual_vacancy_rate": payload.annual_vacancy_rate,
        "investment_notes": payload.investment_notes,
        "listing_purpose": payload.listing_purpose.upper() if payload.listing_purpose else None,
        "status": payload.status.upper() if payload.status else None,
        "owner_customer_id": payload.owner_customer_id,
        "assigned_user_id": payload.assigned_user_id,
    }

    # Enforce total_floors and validate floor_no when unit belongs to a building
    if target_bld_id:
        bld = await conn.fetchrow("SELECT floors_count FROM buildings WHERE building_id = $1", target_bld_id)
        if bld and bld["floors_count"] is not None:
            field_map["total_floors"] = bld["floors_count"]
            if "total_floors" not in payload_dict:
                payload_dict["total_floors"] = bld["floors_count"]
            target_floor_no = field_map["floor_no"]
            if target_floor_no is not None and target_floor_no > bld["floors_count"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"رقم الطابق ({target_floor_no}) لا يمكن أن يتجاوز إجمالي عدد طوابق المبنى ({bld['floors_count']})."
                )

    # Ensure project_id is always synced
    if "project_id" in payload_dict or ("building_id" in payload_dict and target_prj_id != current["project_id"]):
        payload_dict["project_id"] = target_prj_id

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
async def delete_unit(
    unit_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_management_delete_permission(conn, x_user_id)

    current = await conn.fetchrow("SELECT unit_id, unit_number FROM units WHERE unit_id = $1", unit_id)
    if not current:
        raise HTTPException(status_code=404, detail="Unit not found")

    reasons = []

    # 1. طلبات (Leads & Inquiries)
    leads_count = await conn.fetchval("SELECT count(*) FROM leads WHERE unit_id = $1", unit_id) or 0
    lead_units_count = await conn.fetchval("SELECT count(*) FROM lead_units WHERE unit_id = $1", unit_id) or 0
    total_leads = leads_count + lead_units_count
    if total_leads > 0:
        reasons.append(f"{total_leads} طلب عميل مرتبط")

    # 2. فرص بيعية وصفقات (Opportunities, Offers, Reservations, Invoices)
    opp_units = await conn.fetchval("SELECT count(*) FROM opportunity_units WHERE unit_id = $1", unit_id) or 0
    offers_cnt = await conn.fetchval("SELECT count(*) FROM offers WHERE unit_id = $1", unit_id) or 0
    res_cnt = await conn.fetchval("SELECT count(*) FROM reservations WHERE unit_id = $1", unit_id) or 0
    inv_cnt = await conn.fetchval("SELECT count(*) FROM invoices WHERE unit_id = $1", unit_id) or 0
    deals_total = opp_units + offers_cnt + res_cnt + inv_cnt
    if deals_total > 0:
        reasons.append(f"{deals_total} صفقة/عرض/حجز بيعي مرتبط")

    # 3. إدارة أصول وعقود تشغيلية وصيانة (Tenancies, Maintenance, Managed Units)
    tenancies_cnt = await conn.fetchval("SELECT count(*) FROM tenancies WHERE unit_id = $1", unit_id) or 0
    tickets_cnt = await conn.fetchval("SELECT count(*) FROM maintenance_tickets WHERE unit_id = $1", unit_id) or 0
    managed_cnt = await conn.fetchval("SELECT count(*) FROM managed_units WHERE unit_id = $1", unit_id) or 0
    pm_total = tenancies_cnt + tickets_cnt + managed_cnt
    if pm_total > 0:
        reasons.append(f"{pm_total} سجل إدارة أصول (عقود إيجار/بلاغات صيانة)")

    # 4. حملات دعائية وإعلانية (Campaigns & Listings)
    listings_cnt = await conn.fetchval("SELECT count(*) FROM listings WHERE unit_id = $1", unit_id) or 0
    camps_cnt = await conn.fetchval("SELECT count(*) FROM campaigns WHERE target_property_id = $1", unit_id) or 0
    mkt_total = listings_cnt + camps_cnt
    if mkt_total > 0:
        reasons.append(f"{mkt_total} إعلان/حملة تسويقية نشطة")

    # 5. مستندات وفحوصات رسمية مرتبطة
    docs_cnt = await conn.fetchval("SELECT count(*) FROM documents WHERE unit_id = $1", unit_id) or 0
    if docs_cnt > 0:
        reasons.append(f"{docs_cnt} وثيقة مؤرشفة")

    if reasons:
        msg_ar = f"لا يمكن حذف الوحدة العقارية '{current['unit_number']}' لأنها مرتبطة بالعمليات التالية: {', '.join(reasons)}. يرجى فك الارتباط أو إنهاء المعاملات قبل الحذف."
        raise HTTPException(status_code=400, detail=msg_ar)

    # Safe deletion: remove auxiliary history/media records
    await conn.execute("DELETE FROM property_media WHERE unit_id = $1", unit_id)
    await conn.execute("DELETE FROM unit_status_history WHERE unit_id = $1", unit_id)
    await conn.execute("DELETE FROM units WHERE unit_id = $1", unit_id)


