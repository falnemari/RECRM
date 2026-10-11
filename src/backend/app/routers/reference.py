from typing import List, Dict, Any
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
async def list_users(conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch("SELECT user_id, employee_no, full_name, email, mobile, status FROM users WHERE status = 'ACTIVE' ORDER BY full_name")
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


