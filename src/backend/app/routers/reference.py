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
            g.responsible_role_code, g.stage_name_ar, g.stage_name_en,
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
        LEFT JOIN roles r ON g.responsible_role_code = r.role_code
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
    Fetch exact step-by-step SOP execution guide and sample notes for a task template or procedure code.
    """
    import json
    row = await conn.fetchrow("""
        SELECT 
            g.guidance_id, g.stage_code, g.entity_type, g.procedure_code, g.template_id,
            g.responsible_role_code, g.stage_name_ar, g.stage_name_en,
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
        LEFT JOIN roles r ON g.responsible_role_code = r.role_code
        WHERE (g.template_id = $1 OR g.procedure_code = $1 OR g.guidance_id = $1)
          AND g.is_active = TRUE
        ORDER BY g.display_order ASC LIMIT 1
    """, code)

    if not row:
        row = await conn.fetchrow("""
            SELECT 
                g.guidance_id, g.stage_code, g.entity_type, g.procedure_code, g.template_id,
                g.responsible_role_code, g.stage_name_ar, g.stage_name_en,
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
            LEFT JOIN roles r ON g.responsible_role_code = r.role_code
            WHERE g.stage_code = $1 AND g.is_active = TRUE
            ORDER BY g.display_order ASC LIMIT 1
        """, code.upper())

    if not row:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"SOP Guide not found for '{code}'")

    item = dict(row)
    for f in ("execution_steps_ar", "execution_steps_en"):
        if isinstance(item.get(f), str):
            try:
                item[f] = json.loads(item[f])
            except Exception:
                pass

    return ResponseEnvelope(data=item, meta=BaseMeta())



