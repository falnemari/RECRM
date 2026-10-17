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
            u.branch_id, b.name AS branch_name, b.city_id
        FROM users u
        LEFT JOIN branches b ON u.branch_id = b.branch_id
        WHERE {where_clause}
        ORDER BY u.full_name
    """
    rows = await conn.fetch(query, *params)
    data = [dict(row) for row in rows]
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


