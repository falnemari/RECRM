import hashlib
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException, status
import asyncpg
from app.database import get_db
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.schemas.customers import CustomerOut, CustomerCreate, CustomerUpdate, Customer360Out

router = APIRouter(prefix="/customers", tags=["Customers"])

CUSTOMER_SELECT_QUERY = """
    SELECT 
        customer_id,
        organization_id,
        customer_type,
        first_name,
        last_name,
        COALESCE(NULLIF(TRIM(CONCAT(first_name, ' ', last_name)), ''), company_name, 'Unknown') AS full_name,
        company_name,
        nationality_code,
        preferred_language,
        mobile,
        email,
        national_id_hash,
        status,
        created_at,
        updated_at
    FROM customers
"""

@router.get("", response_model=CollectionEnvelope[CustomerOut])
async def list_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: Optional[str] = None,
    customer_type: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    customer_id: Optional[str] = None,
    mobile: Optional[str] = None,
    email: Optional[str] = None,
    national_id: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if customer_id and customer_id.strip():
        cid_val = customer_id.strip()
        conditions.append(f"CAST(customer_id AS TEXT) ILIKE ${p_idx}")
        params.append(f"%{cid_val}%")
        p_idx += 1

    if first_name and first_name.strip():
        conditions.append(f"first_name ILIKE ${p_idx}")
        params.append(f"%{first_name.strip()}%")
        p_idx += 1

    if last_name and last_name.strip():
        conditions.append(f"last_name ILIKE ${p_idx}")
        params.append(f"%{last_name.strip()}%")
        p_idx += 1

    if mobile and mobile.strip():
        conditions.append(f"mobile ILIKE ${p_idx}")
        params.append(f"%{mobile.strip()}%")
        p_idx += 1

    if email and email.strip():
        conditions.append(f"email ILIKE ${p_idx}")
        params.append(f"%{email.strip()}%")
        p_idx += 1

    if national_id and national_id.strip():
        nid_val = national_id.strip()
        nid_hash = hashlib.sha256(nid_val.encode()).hexdigest()
        conditions.append(f"(national_id_hash ILIKE ${p_idx} OR national_id_hash = ${p_idx + 1})")
        params.extend([f"%{nid_val}%", nid_hash])
        p_idx += 2

    if customer_type:
        conditions.append(f"customer_type = ${p_idx}")
        params.append(customer_type.upper())
        p_idx += 1

    if search and search.strip():
        s = search.strip()
        s_hash = hashlib.sha256(s.encode()).hexdigest()
        conditions.append(
            f"(first_name ILIKE ${p_idx} OR last_name ILIKE ${p_idx} OR company_name ILIKE ${p_idx} "
            f"OR mobile ILIKE ${p_idx} OR email ILIKE ${p_idx} OR CAST(customer_id AS TEXT) ILIKE ${p_idx} "
            f"OR national_id_hash ILIKE ${p_idx} OR national_id_hash = ${p_idx + 1})"
        )
        params.extend([f"%{s}%", s_hash])
        p_idx += 2

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"SELECT count(*) FROM customers WHERE {where_clause}", *params)

    query = f"""
        {CUSTOMER_SELECT_QUERY}
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [CustomerOut(**dict(row)) for row in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.get("/{customer_id}", response_model=ResponseEnvelope[CustomerOut])
async def get_customer(customer_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    query = f"{CUSTOMER_SELECT_QUERY} WHERE customer_id = $1"
    row = await conn.fetchrow(query, customer_id)
    if not row:
        raise HTTPException(status_code=404, detail="Customer not found")
    return ResponseEnvelope(data=CustomerOut(**dict(row)), meta=BaseMeta())

@router.get("/{customer_id}/360", response_model=ResponseEnvelope[Customer360Out])
async def get_customer_360(customer_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    # 1. Profile
    c_row = await conn.fetchrow(f"{CUSTOMER_SELECT_QUERY} WHERE customer_id = $1", customer_id)
    if not c_row:
        raise HTTPException(status_code=404, detail="Customer not found")
    profile = CustomerOut(**dict(c_row))

    # 2. Leads
    leads_rows = await conn.fetch(
        "SELECT lead_id, status, priority, inquiry_type, budget_min, budget_max, created_at FROM leads WHERE customer_id = $1 ORDER BY created_at DESC",
        customer_id
    )
    leads = [dict(r) for r in leads_rows]

    # 3. Opportunities
    opp_rows = await conn.fetch(
        "SELECT opportunity_id, stage, expected_value, expected_close_date, created_at FROM opportunities WHERE customer_id = $1 ORDER BY created_at DESC",
        customer_id
    )
    opportunities = [dict(r) for r in opp_rows]

    # 4. Tenancies
    tenancy_rows = await conn.fetch(
        "SELECT tenancy_id, unit_id, contract_number, start_date, end_date, rent_amount, status FROM tenancies WHERE tenant_customer_id = $1 ORDER BY start_date DESC",
        customer_id
    )
    tenancies = [dict(r) for r in tenancy_rows]

    # 5. Owned units
    unit_rows = await conn.fetch(
        "SELECT unit_id, unit_number, asking_price, rent_price, status FROM units WHERE owner_customer_id = $1",
        customer_id
    )
    owned_units = [dict(r) for r in unit_rows]

    # 6. Maintenance tickets
    ticket_rows = await conn.fetch(
        "SELECT ticket_id, unit_id, priority, category, description, status, opened_at FROM maintenance_tickets WHERE reported_by_customer_id = $1 ORDER BY opened_at DESC",
        customer_id
    )
    tickets = [dict(r) for r in ticket_rows]

    c360 = Customer360Out(
        profile=profile,
        leads=leads,
        opportunities=opportunities,
        tenancies=tenancies,
        owned_units=owned_units,
        tickets=tickets
    )
    return ResponseEnvelope(data=c360, meta=BaseMeta())

@router.post("", response_model=ResponseEnvelope[CustomerOut], status_code=status.HTTP_201_CREATED)
async def create_customer(payload: CustomerCreate, conn: asyncpg.Connection = Depends(get_db)):
    org_id = await conn.fetchval("SELECT organization_id FROM organizations LIMIT 1")
    if not org_id:
        raise HTTPException(status_code=500, detail="No active organization found")

    nid_hash = None
    if payload.national_id and payload.national_id.strip():
        nid_hash = hashlib.sha256(payload.national_id.strip().encode()).hexdigest()

    customer_id = await conn.fetchval(
        """
        INSERT INTO customers (
            organization_id, customer_type, first_name, last_name, company_name,
            nationality_code, preferred_language, mobile, email, national_id_hash, status
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'ACTIVE'
        ) RETURNING customer_id
        """,
        org_id, payload.customer_type.upper(), payload.first_name, payload.last_name, payload.company_name,
        payload.nationality_code, payload.preferred_language, payload.mobile, payload.email, nid_hash
    )
    row = await conn.fetchrow(f"{CUSTOMER_SELECT_QUERY} WHERE customer_id = $1", customer_id)
    return ResponseEnvelope(data=CustomerOut(**dict(row)), meta=BaseMeta())

@router.patch("/{customer_id}", response_model=ResponseEnvelope[CustomerOut])
async def update_customer(customer_id: UUID, payload: CustomerUpdate, conn: asyncpg.Connection = Depends(get_db)):
    existing = await conn.fetchrow("SELECT customer_id FROM customers WHERE customer_id = $1", customer_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Customer not found")

    updates = []
    params = []
    p_idx = 1

    if payload.customer_type is not None:
        updates.append(f"customer_type = ${p_idx}")
        params.append(payload.customer_type.upper())
        p_idx += 1

    if payload.first_name is not None:
        updates.append(f"first_name = ${p_idx}")
        params.append(payload.first_name)
        p_idx += 1

    if payload.last_name is not None:
        updates.append(f"last_name = ${p_idx}")
        params.append(payload.last_name)
        p_idx += 1

    if payload.company_name is not None:
        updates.append(f"company_name = ${p_idx}")
        params.append(payload.company_name)
        p_idx += 1

    if payload.nationality_code is not None:
        updates.append(f"nationality_code = ${p_idx}")
        params.append(payload.nationality_code.upper()[:2])
        p_idx += 1

    if payload.preferred_language is not None:
        updates.append(f"preferred_language = ${p_idx}")
        params.append(payload.preferred_language.lower())
        p_idx += 1

    if payload.mobile is not None:
        updates.append(f"mobile = ${p_idx}")
        params.append(payload.mobile)
        p_idx += 1

    if payload.email is not None:
        updates.append(f"email = ${p_idx}")
        params.append(payload.email)
        p_idx += 1

    if payload.national_id is not None:
        nid_hash = hashlib.sha256(payload.national_id.strip().encode()).hexdigest() if payload.national_id.strip() else None
        updates.append(f"national_id_hash = ${p_idx}")
        params.append(nid_hash)
        p_idx += 1

    if payload.status is not None:
        updates.append(f"status = ${p_idx}")
        params.append(payload.status.upper())
        p_idx += 1

    if updates:
        updates.append("updated_at = now()")
        params.append(customer_id)
        query = f"UPDATE customers SET {', '.join(updates)} WHERE customer_id = ${p_idx}"
        await conn.execute(query, *params)

    row = await conn.fetchrow(f"{CUSTOMER_SELECT_QUERY} WHERE customer_id = $1", customer_id)
    return ResponseEnvelope(data=CustomerOut(**dict(row)), meta=BaseMeta())
