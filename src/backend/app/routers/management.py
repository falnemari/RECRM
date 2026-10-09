from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, date, timezone, timedelta
import random
from fastapi import APIRouter, Depends, Query, HTTPException, status
import asyncpg
from app.database import get_db
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.schemas.management import (
    ManagementSummaryOut,
    TenancyOut, TenancyCreateIn,
    RentCollectionOut, RentCollectionCreateIn, RentCollectionPaymentIn,
    MaintenanceTicketOut, MaintenanceTicketCreateIn, MaintenanceTicketUpdateIn,
    VendorOut, VendorCreateIn,
    WorkOrderOut, WorkOrderCreateIn, WorkOrderUpdateIn,
    ManagementContractOut, ManagementContractCreateIn
)

router = APIRouter(tags=["Property Management"])

# ---------------------------------------------------------
# Summary / KPIs
# ---------------------------------------------------------
@router.get("/management/summary", response_model=ResponseEnvelope[ManagementSummaryOut])
async def get_management_summary(conn: asyncpg.Connection = Depends(get_db)):
    active_tenancies = await conn.fetchval(
        "SELECT count(*) FROM tenancies WHERE status = 'ACTIVE'"
    ) or 0

    total_active_rent = await conn.fetchval(
        "SELECT COALESCE(SUM(rent_amount), 0) FROM tenancies WHERE status = 'ACTIVE'"
    ) or 0.0

    open_tickets = await conn.fetchval(
        "SELECT count(*) FROM maintenance_tickets WHERE status != 'CLOSED'"
    ) or 0

    overdue_collections = await conn.fetchval(
        "SELECT count(*) FROM rent_collections WHERE status != 'PAID' AND due_date < CURRENT_DATE"
    ) or 0

    total_vendors = await conn.fetchval(
        "SELECT count(*) FROM vendors WHERE status = 'ACTIVE'"
    ) or 0

    active_pm_contracts = await conn.fetchval(
        "SELECT count(*) FROM management_contracts WHERE status = 'ACTIVE'"
    ) or 0

    summary_data = ManagementSummaryOut(
        active_tenancies=active_tenancies,
        total_active_rent_amount=float(total_active_rent),
        open_maintenance_tickets=open_tickets,
        overdue_rent_collections=overdue_collections,
        total_vendors=total_vendors,
        active_management_contracts=active_pm_contracts
    )
    return ResponseEnvelope(data=summary_data)


# ---------------------------------------------------------
# Tenancies (Leases)
# ---------------------------------------------------------
@router.get("/tenancies", response_model=CollectionEnvelope[TenancyOut])
async def list_tenancies(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    unit_id: Optional[UUID] = None,
    customer_id: Optional[UUID] = None,
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"t.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if unit_id:
        conditions.append(f"t.unit_id = ${p_idx}")
        params.append(unit_id)
        p_idx += 1

    if customer_id:
        conditions.append(f"t.tenant_customer_id = ${p_idx}")
        params.append(customer_id)
        p_idx += 1

    if search:
        s = f"%{search.strip()}%"
        conditions.append(f"(t.contract_number ILIKE ${p_idx} OR u.unit_number ILIKE ${p_idx} OR c.first_name ILIKE ${p_idx} OR c.last_name ILIKE ${p_idx} OR c.company_name ILIKE ${p_idx})")
        params.append(s)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"""
        SELECT count(*) 
        FROM tenancies t
        LEFT JOIN units u ON t.unit_id = u.unit_id
        LEFT JOIN customers c ON t.tenant_customer_id = c.customer_id
        WHERE {where_clause}
        """,
        *params
    )

    query = f"""
        SELECT 
            t.tenancy_id,
            t.unit_id,
            u.unit_number,
            t.tenant_customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS tenant_name,
            c.mobile AS tenant_mobile,
            t.contract_number,
            t.start_date,
            t.end_date,
            CAST(t.rent_amount AS FLOAT) AS rent_amount,
            t.payment_frequency,
            CAST(t.deposit_amount AS FLOAT) AS deposit_amount,
            t.status
        FROM tenancies t
        LEFT JOIN units u ON t.unit_id = u.unit_id
        LEFT JOIN customers c ON t.tenant_customer_id = c.customer_id
        WHERE {where_clause}
        ORDER BY t.start_date DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [TenancyOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/tenancies", response_model=ResponseEnvelope[TenancyOut], status_code=status.HTTP_201_CREATED)
async def create_tenancy(payload: TenancyCreateIn, conn: asyncpg.Connection = Depends(get_db)):
    # Verify unit
    unit = await conn.fetchrow("SELECT unit_id, unit_number, status FROM units WHERE unit_id = $1", payload.unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    # Verify customer
    cust = await conn.fetchrow("SELECT customer_id, first_name, last_name, company_name, mobile FROM customers WHERE customer_id = $1", payload.tenant_customer_id)
    if not cust:
        raise HTTPException(status_code=404, detail="Tenant customer not found")

    contract_number = payload.contract_number
    if not contract_number:
        rnd = random.randint(1000, 9999)
        contract_number = f"TEN-{payload.start_date.strftime('%Y%m')}-{rnd}"

    tenancy_id = uuid4()

    async with conn.transaction():
        # Insert tenancy
        await conn.execute(
            """
            INSERT INTO tenancies (
                tenancy_id, unit_id, tenant_customer_id, contract_number,
                start_date, end_date, rent_amount, payment_frequency,
                deposit_amount, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            tenancy_id,
            payload.unit_id,
            payload.tenant_customer_id,
            contract_number,
            payload.start_date,
            payload.end_date,
            payload.rent_amount,
            payload.payment_frequency,
            payload.deposit_amount or 0.0,
            payload.status or "ACTIVE"
        )

        # Update unit status to RENTED
        if payload.status == "ACTIVE":
            await conn.execute("UPDATE units SET status = 'RENTED' WHERE unit_id = $1", payload.unit_id)

        # Generate rent collection installments if requested
        if payload.generate_installments and payload.installments_count and payload.installments_count > 0:
            count = payload.installments_count
            amount_per_installment = round(payload.rent_amount / count, 2)
            cur_due = payload.start_date
            
            # Days step depending on count
            days_step = 30
            if count == 1:
                days_step = 0
            elif count == 2:
                days_step = 180
            elif count == 4:
                days_step = 90
            elif count == 12:
                days_step = 30

            for i in range(count):
                due_d = cur_due + timedelta(days=i * days_step) if i > 0 else cur_due
                await conn.execute(
                    """
                    INSERT INTO rent_collections (
                        rent_collection_id, tenancy_id, due_date, amount_due, amount_paid, status
                    ) VALUES ($1, $2, $3, $4, 0, 'DUE')
                    """,
                    uuid4(), tenancy_id, due_d, amount_per_installment
                )

    tenant_name = (f"{cust['first_name'] or ''} {cust['last_name'] or ''}").strip() or cust['company_name']
    out = TenancyOut(
        tenancy_id=tenancy_id,
        unit_id=payload.unit_id,
        unit_number=unit["unit_number"],
        tenant_customer_id=payload.tenant_customer_id,
        tenant_name=tenant_name,
        tenant_mobile=cust["mobile"],
        contract_number=contract_number,
        start_date=payload.start_date,
        end_date=payload.end_date,
        rent_amount=payload.rent_amount,
        payment_frequency=payload.payment_frequency,
        deposit_amount=payload.deposit_amount or 0.0,
        status=payload.status or "ACTIVE"
    )
    return ResponseEnvelope(data=out)

@router.get("/tenancies/{tenancy_id}")
async def get_tenancy_detail(tenancy_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    row = await conn.fetchrow(
        """
        SELECT 
            t.tenancy_id,
            t.unit_id,
            u.unit_number,
            t.tenant_customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS tenant_name,
            c.mobile AS tenant_mobile,
            c.email AS tenant_email,
            t.contract_number,
            t.start_date,
            t.end_date,
            CAST(t.rent_amount AS FLOAT) AS rent_amount,
            t.payment_frequency,
            CAST(t.deposit_amount AS FLOAT) AS deposit_amount,
            t.status
        FROM tenancies t
        LEFT JOIN units u ON t.unit_id = u.unit_id
        LEFT JOIN customers c ON t.tenant_customer_id = c.customer_id
        WHERE t.tenancy_id = $1
        """,
        tenancy_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Tenancy not found")

    collections = await conn.fetch(
        """
        SELECT 
            rent_collection_id,
            tenancy_id,
            due_date,
            CAST(amount_due AS FLOAT) AS amount_due,
            CAST(amount_paid AS FLOAT) AS amount_paid,
            paid_at,
            status
        FROM rent_collections
        WHERE tenancy_id = $1
        ORDER BY due_date ASC
        """,
        tenancy_id
    )

    return ResponseEnvelope(data={
        "tenancy": dict(row),
        "collections": [dict(c) for c in collections]
    })

@router.patch("/tenancies/{tenancy_id}", response_model=ResponseEnvelope[dict])
async def update_tenancy_status(
    tenancy_id: UUID,
    status_update: str = Query(..., alias="status"),
    conn: asyncpg.Connection = Depends(get_db)
):
    status_clean = status_update.upper()
    existing = await conn.fetchrow("SELECT tenancy_id, unit_id, status FROM tenancies WHERE tenancy_id = $1", tenancy_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Tenancy not found")

    async with conn.transaction():
        await conn.execute("UPDATE tenancies SET status = $1 WHERE tenancy_id = $2", status_clean, tenancy_id)
        if status_clean in ("EXPIRED", "TERMINATED"):
            # Set unit back to AVAILABLE if not rented by another active contract
            active_cnt = await conn.fetchval(
                "SELECT count(*) FROM tenancies WHERE unit_id = $1 AND status = 'ACTIVE' AND tenancy_id != $2",
                existing["unit_id"], tenancy_id
            )
            if active_cnt == 0:
                await conn.execute("UPDATE units SET status = 'AVAILABLE' WHERE unit_id = $1", existing["unit_id"])

    return ResponseEnvelope(data={"tenancy_id": str(tenancy_id), "status": status_clean})


# ---------------------------------------------------------
# Rent Collections
# ---------------------------------------------------------
@router.get("/rent-collections", response_model=CollectionEnvelope[RentCollectionOut])
async def list_rent_collections(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    tenancy_id: Optional[UUID] = None,
    is_overdue: Optional[bool] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"rc.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if tenancy_id:
        conditions.append(f"rc.tenancy_id = ${p_idx}")
        params.append(tenancy_id)
        p_idx += 1

    if is_overdue:
        conditions.append("rc.status != 'PAID' AND rc.due_date < CURRENT_DATE")

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"""
        SELECT count(*) 
        FROM rent_collections rc
        WHERE {where_clause}
        """,
        *params
    )

    query = f"""
        SELECT 
            rc.rent_collection_id,
            rc.tenancy_id,
            t.contract_number,
            u.unit_number,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS tenant_name,
            rc.due_date,
            CAST(rc.amount_due AS FLOAT) AS amount_due,
            CAST(rc.amount_paid AS FLOAT) AS amount_paid,
            rc.paid_at,
            rc.status
        FROM rent_collections rc
        LEFT JOIN tenancies t ON rc.tenancy_id = t.tenancy_id
        LEFT JOIN units u ON t.unit_id = u.unit_id
        LEFT JOIN customers c ON t.tenant_customer_id = c.customer_id
        WHERE {where_clause}
        ORDER BY rc.due_date ASC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [RentCollectionOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/tenancies/{tenancy_id}/rent-collections", response_model=ResponseEnvelope[RentCollectionOut], status_code=status.HTTP_201_CREATED)
async def create_rent_collection_installment(
    tenancy_id: UUID,
    payload: RentCollectionCreateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    tenancy = await conn.fetchrow(
        """
        SELECT t.tenancy_id, t.contract_number, u.unit_number, COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS tenant_name
        FROM tenancies t
        LEFT JOIN units u ON t.unit_id = u.unit_id
        LEFT JOIN customers c ON t.tenant_customer_id = c.customer_id
        WHERE t.tenancy_id = $1
        """,
        tenancy_id
    )
    if not tenancy:
        raise HTTPException(status_code=404, detail="Tenancy not found")

    new_id = uuid4()
    await conn.execute(
        """
        INSERT INTO rent_collections (rent_collection_id, tenancy_id, due_date, amount_due, amount_paid, status)
        VALUES ($1, $2, $3, $4, 0, 'DUE')
        """,
        new_id, tenancy_id, payload.due_date, payload.amount_due
    )

    out = RentCollectionOut(
        rent_collection_id=new_id,
        tenancy_id=tenancy_id,
        contract_number=tenancy["contract_number"],
        unit_number=tenancy["unit_number"],
        tenant_name=tenancy["tenant_name"],
        due_date=payload.due_date,
        amount_due=payload.amount_due,
        amount_paid=0.0,
        paid_at=None,
        status="DUE"
    )
    return ResponseEnvelope(data=out)

@router.post("/rent-collections/{rent_collection_id}/record-payment", response_model=ResponseEnvelope[RentCollectionOut])
async def record_rent_payment(
    rent_collection_id: UUID,
    payload: RentCollectionPaymentIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    rc = await conn.fetchrow(
        """
        SELECT 
            rc.rent_collection_id, rc.tenancy_id, rc.due_date,
            CAST(rc.amount_due AS FLOAT) AS amount_due,
            CAST(rc.amount_paid AS FLOAT) AS amount_paid,
            rc.status,
            t.contract_number, u.unit_number,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS tenant_name
        FROM rent_collections rc
        LEFT JOIN tenancies t ON rc.tenancy_id = t.tenancy_id
        LEFT JOIN units u ON t.unit_id = u.unit_id
        LEFT JOIN customers c ON t.tenant_customer_id = c.customer_id
        WHERE rc.rent_collection_id = $1
        """,
        rent_collection_id
    )
    if not rc:
        raise HTTPException(status_code=404, detail="Rent collection record not found")

    new_paid = round(rc["amount_paid"] + payload.amount_paid, 2)
    if new_paid > rc["amount_due"]:
        raise HTTPException(
            status_code=400,
            detail=f"Payment amount exceeds amount due. Outstanding balance: {round(rc['amount_due'] - rc['amount_paid'], 2)} SAR"
        )

    now = datetime.now(timezone.utc)
    new_status = "PAID" if new_paid >= rc["amount_due"] else "PARTIAL"

    await conn.execute(
        """
        UPDATE rent_collections
        SET amount_paid = $1, paid_at = $2, status = $3
        WHERE rent_collection_id = $4
        """,
        new_paid, now, new_status, rent_collection_id
    )

    out = RentCollectionOut(
        rent_collection_id=rent_collection_id,
        tenancy_id=rc["tenancy_id"],
        contract_number=rc["contract_number"],
        unit_number=rc["unit_number"],
        tenant_name=rc["tenant_name"],
        due_date=rc["due_date"],
        amount_due=rc["amount_due"],
        amount_paid=new_paid,
        paid_at=now,
        status=new_status
    )
    return ResponseEnvelope(data=out)


# ---------------------------------------------------------
# Maintenance Tickets
# ---------------------------------------------------------
@router.get("/maintenance-tickets", response_model=CollectionEnvelope[MaintenanceTicketOut])
async def list_maintenance_tickets(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    category: Optional[str] = None,
    unit_id: Optional[UUID] = None,
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"mt.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if priority:
        conditions.append(f"mt.priority = ${p_idx}")
        params.append(priority.upper())
        p_idx += 1

    if category:
        conditions.append(f"mt.category = ${p_idx}")
        params.append(category.upper())
        p_idx += 1

    if unit_id:
        conditions.append(f"mt.unit_id = ${p_idx}")
        params.append(unit_id)
        p_idx += 1

    if search:
        s = f"%{search.strip()}%"
        conditions.append(f"(mt.description ILIKE ${p_idx} OR u.unit_number ILIKE ${p_idx})")
        params.append(s)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"""
        SELECT count(*) 
        FROM maintenance_tickets mt
        LEFT JOIN units u ON mt.unit_id = u.unit_id
        WHERE {where_clause}
        """,
        *params
    )

    query = f"""
        SELECT 
            mt.ticket_id,
            mt.unit_id,
            u.unit_number,
            mt.reported_by_customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS reported_by_name,
            mt.assigned_user_id,
            usr.full_name AS assigned_user_name,
            mt.priority,
            mt.category,
            mt.description,
            mt.opened_at,
            mt.due_at,
            mt.closed_at,
            mt.status,
            (SELECT count(*) FROM maintenance_work_orders mwo WHERE mwo.ticket_id = mt.ticket_id) AS work_orders_count
        FROM maintenance_tickets mt
        LEFT JOIN units u ON mt.unit_id = u.unit_id
        LEFT JOIN customers c ON mt.reported_by_customer_id = c.customer_id
        LEFT JOIN users usr ON mt.assigned_user_id = usr.user_id
        WHERE {where_clause}
        ORDER BY 
            CASE mt.priority WHEN 'URGENT' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'NORMAL' THEN 3 ELSE 4 END,
            mt.opened_at DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [MaintenanceTicketOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/maintenance-tickets", response_model=ResponseEnvelope[MaintenanceTicketOut], status_code=status.HTTP_201_CREATED)
async def create_maintenance_ticket(
    payload: MaintenanceTicketCreateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    unit = await conn.fetchrow("SELECT unit_id, unit_number FROM units WHERE unit_id = $1", payload.unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    reported_by_name = None
    if payload.reported_by_customer_id:
        cust = await conn.fetchrow("SELECT first_name, last_name, company_name FROM customers WHERE customer_id = $1", payload.reported_by_customer_id)
        if cust:
            reported_by_name = (f"{cust['first_name'] or ''} {cust['last_name'] or ''}").strip() or cust['company_name']

    assigned_user_name = None
    if payload.assigned_user_id:
        user = await conn.fetchrow("SELECT full_name FROM users WHERE user_id = $1", payload.assigned_user_id)
        if user:
            assigned_user_name = user["full_name"]

    ticket_id = uuid4()
    now = datetime.now(timezone.utc)
    priority = (payload.priority or "NORMAL").upper()
    category = (payload.category or "GENERAL").upper()

    await conn.execute(
        """
        INSERT INTO maintenance_tickets (
            ticket_id, unit_id, reported_by_customer_id, assigned_user_id,
            priority, category, description, opened_at, due_at, status
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'OPEN')
        """,
        ticket_id, payload.unit_id, payload.reported_by_customer_id,
        payload.assigned_user_id, priority, category, payload.description,
        now, payload.due_at
    )

    out = MaintenanceTicketOut(
        ticket_id=ticket_id,
        unit_id=payload.unit_id,
        unit_number=unit["unit_number"],
        reported_by_customer_id=payload.reported_by_customer_id,
        reported_by_name=reported_by_name,
        assigned_user_id=payload.assigned_user_id,
        assigned_user_name=assigned_user_name,
        priority=priority,
        category=category,
        description=payload.description,
        opened_at=now,
        due_at=payload.due_at,
        closed_at=None,
        status="OPEN",
        work_orders_count=0
    )
    return ResponseEnvelope(data=out)

@router.get("/maintenance-tickets/{ticket_id}")
async def get_maintenance_ticket_detail(ticket_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    t = await conn.fetchrow(
        """
        SELECT 
            mt.ticket_id,
            mt.unit_id,
            u.unit_number,
            mt.reported_by_customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS reported_by_name,
            c.mobile AS reporter_mobile,
            mt.assigned_user_id,
            usr.full_name AS assigned_user_name,
            mt.priority,
            mt.category,
            mt.description,
            mt.opened_at,
            mt.due_at,
            mt.closed_at,
            mt.status
        FROM maintenance_tickets mt
        LEFT JOIN units u ON mt.unit_id = u.unit_id
        LEFT JOIN customers c ON mt.reported_by_customer_id = c.customer_id
        LEFT JOIN users usr ON mt.assigned_user_id = usr.user_id
        WHERE mt.ticket_id = $1
        """,
        ticket_id
    )
    if not t:
        raise HTTPException(status_code=404, detail="Maintenance ticket not found")

    work_orders = await conn.fetch(
        """
        SELECT 
            mwo.work_order_id,
            mwo.ticket_id,
            mwo.vendor_id,
            v.vendor_name,
            mwo.assigned_user_id,
            u.full_name AS assigned_user_name,
            CAST(mwo.quoted_amount AS FLOAT) AS quoted_amount,
            CAST(mwo.approved_amount AS FLOAT) AS approved_amount,
            mwo.completed_at,
            mwo.status
        FROM maintenance_work_orders mwo
        LEFT JOIN vendors v ON mwo.vendor_id = v.vendor_id
        LEFT JOIN users u ON mwo.assigned_user_id = u.user_id
        WHERE mwo.ticket_id = $1
        ORDER BY mwo.work_order_id DESC
        """,
        ticket_id
    )

    return ResponseEnvelope(data={
        "ticket": dict(t),
        "work_orders": [dict(w) for w in work_orders]
    })

@router.patch("/maintenance-tickets/{ticket_id}", response_model=ResponseEnvelope[dict])
async def update_maintenance_ticket(
    ticket_id: UUID,
    payload: MaintenanceTicketUpdateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    ticket = await conn.fetchrow("SELECT ticket_id, status FROM maintenance_tickets WHERE ticket_id = $1", ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    sets = []
    params = []
    p_idx = 1

    if payload.status:
        st = payload.status.upper()
        sets.append(f"status = ${p_idx}")
        params.append(st)
        p_idx += 1
        if st == "CLOSED":
            sets.append(f"closed_at = ${p_idx}")
            params.append(datetime.now(timezone.utc))
            p_idx += 1

    if payload.priority:
        sets.append(f"priority = ${p_idx}")
        params.append(payload.priority.upper())
        p_idx += 1

    if payload.category:
        sets.append(f"category = ${p_idx}")
        params.append(payload.category.upper())
        p_idx += 1

    if payload.assigned_user_id:
        sets.append(f"assigned_user_id = ${p_idx}")
        params.append(payload.assigned_user_id)
        p_idx += 1

    if not sets:
        return ResponseEnvelope(data={"ticket_id": str(ticket_id), "status": ticket["status"]})

    params.append(ticket_id)
    sql = f"UPDATE maintenance_tickets SET {', '.join(sets)} WHERE ticket_id = ${p_idx}"
    await conn.execute(sql, *params)

    return ResponseEnvelope(data={"ticket_id": str(ticket_id), "updated": True})


# ---------------------------------------------------------
# Work Orders
# ---------------------------------------------------------
@router.get("/work-orders", response_model=CollectionEnvelope[WorkOrderOut])
async def list_work_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    ticket_id: Optional[UUID] = None,
    vendor_id: Optional[UUID] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"mwo.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if ticket_id:
        conditions.append(f"mwo.ticket_id = ${p_idx}")
        params.append(ticket_id)
        p_idx += 1

    if vendor_id:
        conditions.append(f"mwo.vendor_id = ${p_idx}")
        params.append(vendor_id)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"SELECT count(*) FROM maintenance_work_orders mwo WHERE {where_clause}",
        *params
    )

    query = f"""
        SELECT 
            mwo.work_order_id,
            mwo.ticket_id,
            mt.description AS ticket_description,
            u.unit_number,
            mwo.vendor_id,
            v.vendor_name,
            mwo.assigned_user_id,
            usr.full_name AS assigned_user_name,
            CAST(mwo.quoted_amount AS FLOAT) AS quoted_amount,
            CAST(mwo.approved_amount AS FLOAT) AS approved_amount,
            mwo.completed_at,
            mwo.status
        FROM maintenance_work_orders mwo
        LEFT JOIN maintenance_tickets mt ON mwo.ticket_id = mt.ticket_id
        LEFT JOIN units u ON mt.unit_id = u.unit_id
        LEFT JOIN vendors v ON mwo.vendor_id = v.vendor_id
        LEFT JOIN users usr ON mwo.assigned_user_id = usr.user_id
        WHERE {where_clause}
        ORDER BY mwo.work_order_id DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [WorkOrderOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/maintenance-tickets/{ticket_id}/work-orders", response_model=ResponseEnvelope[WorkOrderOut], status_code=status.HTTP_201_CREATED)
async def create_work_order(
    ticket_id: UUID,
    payload: WorkOrderCreateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    ticket = await conn.fetchrow(
        """
        SELECT mt.ticket_id, mt.description, u.unit_number
        FROM maintenance_tickets mt
        LEFT JOIN units u ON mt.unit_id = u.unit_id
        WHERE mt.ticket_id = $1
        """,
        ticket_id
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Maintenance ticket not found")

    vendor_name = None
    if payload.vendor_id:
        v = await conn.fetchrow("SELECT vendor_name FROM vendors WHERE vendor_id = $1", payload.vendor_id)
        if v:
            vendor_name = v["vendor_name"]

    user_name = None
    if payload.assigned_user_id:
        u = await conn.fetchrow("SELECT full_name FROM users WHERE user_id = $1", payload.assigned_user_id)
        if u:
            user_name = u["full_name"]

    wo_id = uuid4()
    st = (payload.status or "REQUESTED").upper()

    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO maintenance_work_orders (
                work_order_id, ticket_id, vendor_id, assigned_user_id,
                quoted_amount, approved_amount, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            wo_id, ticket_id, payload.vendor_id, payload.assigned_user_id,
            payload.quoted_amount, payload.approved_amount, st
        )
        # Advance ticket status to IN_PROGRESS if OPEN
        await conn.execute(
            "UPDATE maintenance_tickets SET status = 'IN_PROGRESS' WHERE ticket_id = $1 AND status = 'OPEN'",
            ticket_id
        )

    out = WorkOrderOut(
        work_order_id=wo_id,
        ticket_id=ticket_id,
        ticket_description=ticket["description"],
        unit_number=ticket["unit_number"],
        vendor_id=payload.vendor_id,
        vendor_name=vendor_name,
        assigned_user_id=payload.assigned_user_id,
        assigned_user_name=user_name,
        quoted_amount=payload.quoted_amount,
        approved_amount=payload.approved_amount,
        completed_at=None,
        status=st
    )
    return ResponseEnvelope(data=out)

@router.post("/work-orders/{work_order_id}/approve", response_model=ResponseEnvelope[dict])
async def approve_work_order(
    work_order_id: UUID,
    approved_amount: Optional[float] = Query(None),
    conn: asyncpg.Connection = Depends(get_db)
):
    wo = await conn.fetchrow("SELECT work_order_id, quoted_amount, status FROM maintenance_work_orders WHERE work_order_id = $1", work_order_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    final_amount = approved_amount if approved_amount is not None else float(wo["quoted_amount"] or 0.0)

    await conn.execute(
        "UPDATE maintenance_work_orders SET status = 'APPROVED', approved_amount = $1 WHERE work_order_id = $2",
        final_amount, work_order_id
    )
    return ResponseEnvelope(data={"work_order_id": str(work_order_id), "status": "APPROVED", "approved_amount": final_amount})

@router.post("/work-orders/{work_order_id}/complete", response_model=ResponseEnvelope[dict])
async def complete_work_order(
    work_order_id: UUID,
    conn: asyncpg.Connection = Depends(get_db)
):
    wo = await conn.fetchrow("SELECT work_order_id, ticket_id, status FROM maintenance_work_orders WHERE work_order_id = $1", work_order_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    now = datetime.now(timezone.utc)
    await conn.execute(
        "UPDATE maintenance_work_orders SET status = 'COMPLETED', completed_at = $1 WHERE work_order_id = $2",
        now, work_order_id
    )
    return ResponseEnvelope(data={"work_order_id": str(work_order_id), "status": "COMPLETED", "completed_at": now.isoformat()})


# ---------------------------------------------------------
# Vendors
# ---------------------------------------------------------
@router.get("/vendors", response_model=CollectionEnvelope[VendorOut])
async def list_vendors(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = None,
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

    if search:
        s = f"%{search.strip()}%"
        conditions.append(f"(v.vendor_name ILIKE ${p_idx} OR v.phone ILIKE ${p_idx} OR v.email ILIKE ${p_idx} OR v.tax_number ILIKE ${p_idx})")
        params.append(s)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"SELECT count(*) FROM vendors v WHERE {where_clause}", *params)

    query = f"""
        SELECT 
            v.vendor_id,
            v.organization_id,
            v.vendor_name,
            v.phone,
            v.email,
            v.tax_number,
            v.status,
            (SELECT count(*) FROM maintenance_work_orders mwo WHERE mwo.vendor_id = v.vendor_id) AS work_orders_count
        FROM vendors v
        WHERE {where_clause}
        ORDER BY v.vendor_name ASC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [VendorOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/vendors", response_model=ResponseEnvelope[VendorOut], status_code=status.HTTP_201_CREATED)
async def create_vendor(
    payload: VendorCreateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    # Fetch default active organization
    org = await conn.fetchrow("SELECT organization_id FROM organizations WHERE status = 'ACTIVE' LIMIT 1")
    if not org:
        org = await conn.fetchrow("SELECT organization_id FROM organizations LIMIT 1")
    org_id = org["organization_id"]

    vendor_id = uuid4()
    st = (payload.status or "ACTIVE").upper()

    await conn.execute(
        """
        INSERT INTO vendors (vendor_id, organization_id, vendor_name, phone, email, tax_number, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        vendor_id, org_id, payload.vendor_name, payload.phone, payload.email, payload.tax_number, st
    )

    out = VendorOut(
        vendor_id=vendor_id,
        organization_id=org_id,
        vendor_name=payload.vendor_name,
        phone=payload.phone,
        email=payload.email,
        tax_number=payload.tax_number,
        status=st,
        work_orders_count=0
    )
    return ResponseEnvelope(data=out)


# ---------------------------------------------------------
# Owner Management Contracts
# ---------------------------------------------------------
@router.get("/management-contracts", response_model=CollectionEnvelope[ManagementContractOut])
async def list_management_contracts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    customer_id: Optional[UUID] = None,
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"mc.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if customer_id:
        conditions.append(f"mc.customer_id = ${p_idx}")
        params.append(customer_id)
        p_idx += 1

    if search:
        s = f"%{search.strip()}%"
        conditions.append(f"(mc.contract_number ILIKE ${p_idx} OR c.first_name ILIKE ${p_idx} OR c.last_name ILIKE ${p_idx} OR c.company_name ILIKE ${p_idx})")
        params.append(s)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"""
        SELECT count(*) 
        FROM management_contracts mc
        LEFT JOIN customers c ON mc.customer_id = c.customer_id
        WHERE {where_clause}
        """,
        *params
    )

    query = f"""
        SELECT 
            mc.management_contract_id,
            mc.customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS owner_name,
            mc.contract_number,
            mc.start_date,
            mc.end_date,
            mc.fee_type,
            CAST(mc.fee_rate AS FLOAT) AS fee_rate,
            mc.status,
            (SELECT count(*) FROM managed_units mu WHERE mu.management_contract_id = mc.management_contract_id) AS managed_units_count
        FROM management_contracts mc
        LEFT JOIN customers c ON mc.customer_id = c.customer_id
        WHERE {where_clause}
        ORDER BY mc.start_date DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [ManagementContractOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/management-contracts", response_model=ResponseEnvelope[ManagementContractOut], status_code=status.HTTP_201_CREATED)
async def create_management_contract(
    payload: ManagementContractCreateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    cust = await conn.fetchrow("SELECT customer_id, first_name, last_name, company_name FROM customers WHERE customer_id = $1", payload.customer_id)
    if not cust:
        raise HTTPException(status_code=404, detail="Owner customer not found")

    contract_number = payload.contract_number
    if not contract_number:
        rnd = random.randint(1000, 9999)
        contract_number = f"PMC-{payload.start_date.strftime('%Y%m')}-{rnd}"

    mc_id = uuid4()
    st = (payload.status or "ACTIVE").upper()

    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO management_contracts (
                management_contract_id, customer_id, contract_number,
                start_date, end_date, fee_type, fee_rate, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            mc_id, payload.customer_id, contract_number,
            payload.start_date, payload.end_date, (payload.fee_type or "PERCENT").upper(),
            payload.fee_rate, st
        )

        if payload.unit_ids:
            for uid in payload.unit_ids:
                await conn.execute(
                    """
                    INSERT INTO managed_units (management_contract_id, unit_id, management_start, management_end)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT DO NOTHING
                    """,
                    mc_id, uid, payload.start_date, payload.end_date
                )

    owner_name = (f"{cust['first_name'] or ''} {cust['last_name'] or ''}").strip() or cust['company_name']
    out = ManagementContractOut(
        management_contract_id=mc_id,
        customer_id=payload.customer_id,
        owner_name=owner_name,
        contract_number=contract_number,
        start_date=payload.start_date,
        end_date=payload.end_date,
        fee_type=(payload.fee_type or "PERCENT").upper(),
        fee_rate=payload.fee_rate,
        status=st,
        managed_units_count=len(payload.unit_ids or [])
    )
    return ResponseEnvelope(data=out)
