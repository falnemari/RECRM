from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException, status, Header
import asyncpg
from app.database import get_db, get_next_id
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.schemas.leads import LeadOut, LeadCreate, LeadUpdate, LeadNoteOut, LeadNoteCreate, LeadUnitItem
from app.routers.auth import check_user_scope_override

router = APIRouter(prefix="/leads", tags=["Leads"])

async def fetch_lead_units(conn: asyncpg.Connection, lead_id: str) -> List[LeadUnitItem]:
    rows = await conn.fetch("""
        SELECT 
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
    assigned_user_id = await check_user_scope_override(conn, x_user_id, assigned_user_id)
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
async def get_lead(lead_id: str, conn: asyncpg.Connection = Depends(get_db)):
    query = f"{LEAD_SELECT_QUERY} WHERE l.lead_id = $1"
    row = await conn.fetchrow(query, lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    units = await fetch_lead_units(conn, lead_id)
    return ResponseEnvelope(data=LeadOut(**dict(row), units=units), meta=BaseMeta())

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
            unit_id,
            status, priority, inquiry_type, budget_min, budget_max,
            bedrooms_min, area_min_sqm, preferred_city_id, preferred_property_type_id,
            first_contact_due_at
        ) VALUES (
            $1, $2, $3, $4, $5, 'NEW', $6::text, $7, $8, $9, $10, $11, $12, $13,
            CASE 
                WHEN UPPER($6::text) = 'URGENT' THEN now() + interval '1 hour'
                WHEN UPPER($6::text) = 'HIGH' THEN now() + interval '2 hours'
                WHEN UPPER($6::text) = 'LOW' THEN now() + interval '48 hours'
                ELSE now() + interval '24 hours'
            END
        ) RETURNING lead_id
        """,
        org_id, customer_id, payload.lead_source_id, payload.assigned_user_id,
        payload.unit_id or None,
        payload.priority, payload.inquiry_type, payload.budget_min, payload.budget_max,
        payload.bedrooms_min, payload.area_min_sqm, payload.preferred_city_id, payload.preferred_property_type_id
    )

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

    query = f"{LEAD_SELECT_QUERY} WHERE l.lead_id = $1"
    row = await conn.fetchrow(query, lead_id)
    units = await fetch_lead_units(conn, lead_id)
    return ResponseEnvelope(data=LeadOut(**dict(row), units=units), meta=BaseMeta())

@router.patch("/{lead_id}", response_model=ResponseEnvelope[LeadOut])
async def update_lead(lead_id: str, payload: LeadUpdate, conn: asyncpg.Connection = Depends(get_db)):
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

        # Sync with Sales Pipeline opportunities if status changed
        if payload.status is not None:
            st = payload.status.upper()
            if st in ("QUALIFIED", "CONVERTED"):
                existing_opp = await conn.fetchrow("SELECT opportunity_id FROM opportunities WHERE lead_id = $1", lead_id)
                lead_row = await conn.fetchrow("SELECT customer_id, assigned_user_id, budget_max, budget_min, unit_id FROM leads WHERE lead_id = $1", lead_id)
                if not existing_opp:
                    if lead_row and lead_row["customer_id"]:
                        opp_id = await get_next_id(conn, "opportunities", "opportunity")
                        val = float(lead_row["budget_max"] or lead_row["budget_min"] or 0.0)
                        if lead_row["unit_id"]:
                            u_row = await conn.fetchrow("SELECT asking_price, rent_price FROM units WHERE unit_id = $1", lead_row["unit_id"])
                            if u_row and (val == 0 or val is None):
                                val = float(u_row["asking_price"] or u_row["rent_price"] or 0.0)

                        await conn.execute("""
                            INSERT INTO opportunities (
                                opportunity_id, lead_id, customer_id, assigned_user_id,
                                stage, expected_value, created_at, updated_at
                            ) VALUES ($1, $2, $3, $4, 'QUALIFIED', $5, now(), now())
                        """, opp_id, lead_id, lead_row["customer_id"], lead_row["assigned_user_id"], val)

                        # Transfer all shortlisted units to opportunity_units
                        lu_rows = await conn.fetch("""
                            SELECT lu.unit_id, lu.is_primary, COALESCE(un.asking_price, un.rent_price) AS unit_price
                            FROM lead_units lu
                            JOIN units un ON lu.unit_id = un.unit_id
                            WHERE lu.lead_id = $1
                        """, lead_id)
                        for lu in lu_rows:
                            u_price = float(lu["unit_price"] or val or 0.0)
                            await conn.execute("""
                                INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
                                VALUES ($1, $2, $3, $4)
                                ON CONFLICT (opportunity_id, unit_id) DO NOTHING
                            """, opp_id, lu["unit_id"], lu["is_primary"], u_price)
                else:
                    opp_id = existing_opp["opportunity_id"]
                    lu_rows = await conn.fetch("""
                        SELECT lu.unit_id, lu.is_primary, COALESCE(un.asking_price, un.rent_price) AS unit_price
                        FROM lead_units lu
                        JOIN units un ON lu.unit_id = un.unit_id
                        WHERE lu.lead_id = $1
                    """, lead_id)
                    for lu in lu_rows:
                        u_price = float(lu["unit_price"] or 0.0)
                        await conn.execute("""
                            INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
                            VALUES ($1, $2, $3, $4)
                            ON CONFLICT (opportunity_id, unit_id) DO NOTHING
                        """, opp_id, lu["unit_id"], lu["is_primary"], u_price)
            elif st == "LOST":
                await conn.execute("UPDATE opportunities SET stage = 'LOST', updated_at = now() WHERE lead_id = $1 AND stage NOT IN ('WON', 'LOST')", lead_id)

    query = f"{LEAD_SELECT_QUERY} WHERE l.lead_id = $1"
    row = await conn.fetchrow(query, lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    units = await fetch_lead_units(conn, lead_id)
    return ResponseEnvelope(data=LeadOut(**dict(row), units=units), meta=BaseMeta())

@router.post("/{lead_id}/contact", response_model=ResponseEnvelope[LeadOut])
async def mark_lead_contacted(lead_id: str, conn: asyncpg.Connection = Depends(get_db)):
    await conn.execute("""
        UPDATE leads 
        SET status = 'CONTACTED',
            first_contact_at = COALESCE(first_contact_at, now()),
            updated_at = now()
        WHERE lead_id = $1
    """, lead_id)
    query = f"{LEAD_SELECT_QUERY} WHERE l.lead_id = $1"
    row = await conn.fetchrow(query, lead_id)
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    units = await fetch_lead_units(conn, lead_id)
    return ResponseEnvelope(data=LeadOut(**dict(row), units=units), meta=BaseMeta())

@router.post("/{lead_id}/qualify", response_model=ResponseEnvelope[LeadOut])
async def qualify_lead(lead_id: str, conn: asyncpg.Connection = Depends(get_db)):
    await conn.execute("UPDATE leads SET status = 'QUALIFIED', updated_at = now() WHERE lead_id = $1", lead_id)

    # Automatically create/link active opportunity in Sales Pipeline
    existing_opp = await conn.fetchrow("SELECT opportunity_id FROM opportunities WHERE lead_id = $1", lead_id)
    lead_row = await conn.fetchrow("SELECT customer_id, assigned_user_id, budget_max, budget_min, unit_id FROM leads WHERE lead_id = $1", lead_id)
    if not existing_opp:
        if lead_row and lead_row["customer_id"]:
            opp_id = await get_next_id(conn, "opportunities", "opportunity")
            val = float(lead_row["budget_max"] or lead_row["budget_min"] or 0.0)
            if lead_row["unit_id"]:
                u_row = await conn.fetchrow("SELECT asking_price, rent_price FROM units WHERE unit_id = $1", lead_row["unit_id"])
                if u_row and (val == 0 or val is None):
                    val = float(u_row["asking_price"] or u_row["rent_price"] or 0.0)

            await conn.execute("""
                INSERT INTO opportunities (
                    opportunity_id, lead_id, customer_id, assigned_user_id,
                    stage, expected_value, created_at, updated_at
                ) VALUES ($1, $2, $3, $4, 'QUALIFIED', $5, now(), now())
            """, opp_id, lead_id, lead_row["customer_id"], lead_row["assigned_user_id"], val)

            # Transfer all shortlisted units from lead_units to opportunity_units
            lu_rows = await conn.fetch("""
                SELECT lu.unit_id, lu.is_primary, COALESCE(un.asking_price, un.rent_price) AS unit_price
                FROM lead_units lu
                JOIN units un ON lu.unit_id = un.unit_id
                WHERE lu.lead_id = $1
            """, lead_id)
            for lu in lu_rows:
                u_price = float(lu["unit_price"] or val or 0.0)
                await conn.execute("""
                    INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (opportunity_id, unit_id) DO NOTHING
                """, opp_id, lu["unit_id"], lu["is_primary"], u_price)
    else:
        opp_id = existing_opp["opportunity_id"]
        lu_rows = await conn.fetch("""
            SELECT lu.unit_id, lu.is_primary, COALESCE(un.asking_price, un.rent_price) AS unit_price
            FROM lead_units lu
            JOIN units un ON lu.unit_id = un.unit_id
            WHERE lu.lead_id = $1
        """, lead_id)
        for lu in lu_rows:
            u_price = float(lu["unit_price"] or 0.0)
            await conn.execute("""
                INSERT INTO opportunity_units (opportunity_id, unit_id, is_primary, offered_price)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (opportunity_id, unit_id) DO NOTHING
            """, opp_id, lu["unit_id"], lu["is_primary"], u_price)

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

