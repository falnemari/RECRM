from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, date, timezone, timedelta
import random
from fastapi import APIRouter, Depends, Query, HTTPException, status, Header
from fastapi.responses import HTMLResponse
import asyncpg
from app.database import get_db, get_next_id
from app.services.workflow_engine import WorkflowEngine
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.schemas.management import (
    ManagementSummaryOut,
    TenancyOut, TenancyCreateIn,
    RentCollectionOut, RentCollectionCreateIn, RentCollectionPaymentIn,
    MaintenanceTicketOut, MaintenanceTicketCreateIn, MaintenanceTicketUpdateIn,
    VendorOut, VendorCreateIn,
    WorkOrderOut, WorkOrderCreateIn, WorkOrderUpdateIn,
    ManagementContractOut, ManagementContractCreateIn,
    OwnerYieldDistributionOut, OwnerYieldCalculationPreviewOut,
    OwnerYieldDistributionCalculateIn, OwnerYieldDistributionCreateIn,
    OwnerYieldDistributionPayoutIn
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

    total_managed_units = await conn.fetchval(
        "SELECT count(DISTINCT unit_id) FROM managed_units"
    ) or 0

    occupancy_rate = 0.0
    if total_managed_units > 0:
        occupancy_rate = round(float(active_tenancies) / float(total_managed_units) * 100.0, 1)

    total_yield_distributed = await conn.fetchval(
        "SELECT COALESCE(SUM(net_yield_amount), 0) FROM owner_yield_distributions WHERE status = 'PAID'"
    ) or 0.0

    pending_owner_payouts = await conn.fetchval(
        "SELECT COALESCE(SUM(net_yield_amount), 0) FROM owner_yield_distributions WHERE status IN ('DRAFT', 'APPROVED')"
    ) or 0.0

    summary_data = ManagementSummaryOut(
        active_tenancies=active_tenancies,
        total_active_rent_amount=float(total_active_rent),
        open_maintenance_tickets=open_tickets,
        overdue_rent_collections=overdue_collections,
        total_vendors=total_vendors,
        active_management_contracts=active_pm_contracts,
        total_managed_units=total_managed_units,
        occupancy_rate=occupancy_rate,
        total_yield_distributed=float(total_yield_distributed),
        pending_owner_payouts=float(pending_owner_payouts)
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
    unit_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    p_val = int(page) if isinstance(page, int) else (int(page.default) if hasattr(page, 'default') else 1)
    ps_val = int(page_size) if isinstance(page_size, int) else (int(page_size.default) if hasattr(page_size, 'default') else 50)
    offset = (p_val - 1) * ps_val
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter and isinstance(status_filter, str):
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
        conditions.append(f"(t.contract_number ILIKE ${p_idx} OR t.ejar_contract_number ILIKE ${p_idx} OR u.unit_number ILIKE ${p_idx} OR c.first_name ILIKE ${p_idx} OR c.last_name ILIKE ${p_idx} OR c.company_name ILIKE ${p_idx})")
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
            t.ejar_contract_number,
            t.ejar_status,
            t.contract_type,
            t.start_date,
            t.end_date,
            CAST(t.rent_amount AS FLOAT) AS rent_amount,
            t.payment_frequency,
            CAST(t.deposit_amount AS FLOAT) AS deposit_amount,
            t.security_deposit_status,
            t.status
        FROM tenancies t
        LEFT JOIN units u ON t.unit_id = u.unit_id
        LEFT JOIN customers c ON t.tenant_customer_id = c.customer_id
        WHERE {where_clause}
        ORDER BY t.start_date DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([ps_val, offset])
    rows = await conn.fetch(query, *params)
    data = [TenancyOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=p_val, page_size=ps_val, total=total)
    )

@router.post("/tenancies", response_model=ResponseEnvelope[TenancyOut], status_code=status.HTTP_201_CREATED)
async def create_tenancy(
    payload: TenancyCreateIn, 
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    try:
        async with conn.transaction():
            res = await WorkflowEngine.execute_tenancy_agreement(
                conn=conn,
                unit_id=payload.unit_id,
                tenant_customer_id=payload.tenant_customer_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
                rent_amount=payload.rent_amount,
                payment_frequency=payload.payment_frequency or "ANNUAL",
                deposit_amount=payload.deposit_amount or 0.0,
                contract_number=payload.contract_number,
                lead_id=payload.lead_id,
                opportunity_id=payload.opportunity_id,
                user_id=x_user_id,
                generate_installments=payload.generate_installments if payload.generate_installments is not None else True,
                installments_count=payload.installments_count or 1
            )
            tenancy = res["tenancy"]
            if payload.ejar_contract_number or payload.contract_type or payload.security_deposit_status or payload.ejar_status:
                await conn.execute(
                    """
                    UPDATE tenancies 
                    SET ejar_contract_number = COALESCE($1, ejar_contract_number),
                        ejar_status = COALESCE($2, ejar_status),
                        contract_type = COALESCE($3, contract_type),
                        security_deposit_status = COALESCE($4, security_deposit_status)
                    WHERE tenancy_id = $5
                    """,
                    payload.ejar_contract_number,
                    payload.ejar_status or 'ACTIVE',
                    payload.contract_type or 'RESIDENTIAL',
                    payload.security_deposit_status or 'HELD',
                    tenancy["tenancy_id"]
                )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    out = TenancyOut(
        tenancy_id=tenancy["tenancy_id"],
        unit_id=tenancy["unit_id"],
        unit_number=res.get("unit_number"),
        tenant_customer_id=tenancy["tenant_customer_id"],
        tenant_name=res.get("tenant_name"),
        tenant_mobile=res.get("tenant_mobile"),
        contract_number=tenancy["contract_number"],
        ejar_contract_number=payload.ejar_contract_number,
        ejar_status=payload.ejar_status or "ACTIVE",
        contract_type=payload.contract_type or "RESIDENTIAL",
        start_date=tenancy["start_date"],
        end_date=tenancy["end_date"],
        rent_amount=float(tenancy["rent_amount"]),
        payment_frequency=tenancy["payment_frequency"],
        deposit_amount=float(tenancy["deposit_amount"]),
        security_deposit_status=payload.security_deposit_status or "HELD",
        status=tenancy["status"]
    )
    return ResponseEnvelope(data=out)

@router.get("/tenancies/{tenancy_id}")
async def get_tenancy_detail(tenancy_id: str, conn: asyncpg.Connection = Depends(get_db)):
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
            t.ejar_contract_number,
            t.ejar_status,
            t.contract_type,
            t.start_date,
            t.end_date,
            CAST(t.rent_amount AS FLOAT) AS rent_amount,
            t.payment_frequency,
            CAST(t.deposit_amount AS FLOAT) AS deposit_amount,
            t.security_deposit_status,
            t.status
        FROM tenancies t
        LEFT JOIN units u ON t.unit_id = u.unit_id
        LEFT JOIN customers c ON t.tenant_customer_id = c.customer_id
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
    tenancy_id: str,
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
    tenancy_id: Optional[str] = None,
    collection_id: Optional[str] = None,
    search: Optional[str] = None,
    is_overdue: Optional[bool] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    p_val = int(page) if isinstance(page, int) else (int(page.default) if hasattr(page, 'default') else 1)
    ps_val = int(page_size) if isinstance(page_size, int) else (int(page_size.default) if hasattr(page_size, 'default') else 50)
    offset = (p_val - 1) * ps_val
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter and isinstance(status_filter, str):
        conditions.append(f"rc.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if tenancy_id:
        conditions.append(f"rc.tenancy_id = ${p_idx}")
        params.append(tenancy_id)
        p_idx += 1

    if collection_id:
        conditions.append(f"rc.rent_collection_id = ${p_idx}")
        params.append(collection_id)
        p_idx += 1

    if search:
        s = f"%{search.strip()}%"
        conditions.append(f"""(
            rc.rent_collection_id ILIKE ${p_idx}
            OR t.contract_number ILIKE ${p_idx}
            OR u.unit_number ILIKE ${p_idx}
            OR c.first_name ILIKE ${p_idx}
            OR c.last_name ILIKE ${p_idx}
            OR c.company_name ILIKE ${p_idx}
        )""")
        params.append(s)
        p_idx += 1

    if is_overdue:
        conditions.append("rc.status != 'PAID' AND rc.due_date < CURRENT_DATE")

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"""
        SELECT count(*) 
        FROM rent_collections rc
        LEFT JOIN tenancies t ON rc.tenancy_id = t.tenancy_id
        LEFT JOIN units u ON t.unit_id = u.unit_id
        LEFT JOIN customers c ON t.tenant_customer_id = c.customer_id
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
    params.extend([ps_val, offset])
    rows = await conn.fetch(query, *params)
    data = [RentCollectionOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=p_val, page_size=ps_val, total=total)
    )

@router.post("/tenancies/{tenancy_id}/rent-collections", response_model=ResponseEnvelope[RentCollectionOut], status_code=status.HTTP_201_CREATED)
async def create_rent_collection_installment(
    tenancy_id: str,
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

    new_id = await get_next_id(conn, "rent_collections", "rent_collection")
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
    rent_collection_id: str,
    payload: RentCollectionPaymentIn,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    rc = await conn.fetchrow(
        """
        SELECT 
            rc.rent_collection_id, rc.tenancy_id, rc.due_date,
            CAST(rc.amount_due AS FLOAT) AS amount_due,
            CAST(rc.amount_paid AS FLOAT) AS amount_paid,
            rc.status,
            t.contract_number, u.unit_number, t.tenant_customer_id,
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

    async with conn.transaction():
        await conn.execute(
            """
            UPDATE rent_collections
            SET amount_paid = $1, paid_at = $2, status = $3
            WHERE rent_collection_id = $4
            """,
            new_paid, now, new_status, rent_collection_id
        )

        # Record Activity ACT_RENT_PAYMENT_COLLECTED
        rem_balance = round(rc["amount_due"] - new_paid, 2)
        await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_RENT_PAYMENT_COLLECTED",
            user_id=x_user_id or "user-51",
            customer_id=rc["tenant_customer_id"],
            outcome="PAID" if new_status == "PAID" else "PARTIAL",
            notes=f"تم استلام دفعة إيجارية بمبلغ {payload.amount_paid:,.2f} ريال للعقد {rc['contract_number']}. الرصيد المتبقي: {rem_balance:,.2f} ريال.",
            completed_at=now
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
    unit_id: Optional[str] = None,
    ticket_id: Optional[str] = None,
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    p_val = int(page) if isinstance(page, int) else (int(page.default) if hasattr(page, 'default') else 1)
    ps_val = int(page_size) if isinstance(page_size, int) else (int(page_size.default) if hasattr(page_size, 'default') else 50)
    offset = (p_val - 1) * ps_val
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter and isinstance(status_filter, str):
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

    if ticket_id:
        conditions.append(f"mt.ticket_id = ${p_idx}")
        params.append(ticket_id)
        p_idx += 1

    if search:
        s = f"%{search.strip()}%"
        conditions.append(f"""(
            mt.ticket_id ILIKE ${p_idx} 
            OR mt.description ILIKE ${p_idx} 
            OR u.unit_number ILIKE ${p_idx}
            OR EXISTS (SELECT 1 FROM maintenance_work_orders mwo WHERE mwo.ticket_id = mt.ticket_id AND mwo.work_order_id ILIKE ${p_idx})
        )""")
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
    params.extend([ps_val, offset])
    rows = await conn.fetch(query, *params)
    data = [MaintenanceTicketOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=p_val, page_size=ps_val, total=total)
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

    ticket_id = await get_next_id(conn, "maintenance_tickets", "ticket")
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
async def get_maintenance_ticket_detail(ticket_id: str, conn: asyncpg.Connection = Depends(get_db)):
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
    ticket_id: str,
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
    ticket_id: Optional[str] = None,
    vendor_id: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    p_val = int(page) if isinstance(page, int) else (int(page.default) if hasattr(page, 'default') else 1)
    ps_val = int(page_size) if isinstance(page_size, int) else (int(page_size.default) if hasattr(page_size, 'default') else 50)
    offset = (p_val - 1) * ps_val
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter and isinstance(status_filter, str):
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
            mwo.cost_bearer,
            CAST(mwo.quoted_amount AS FLOAT) AS quoted_amount,
            CAST(mwo.approved_amount AS FLOAT) AS approved_amount,
            CAST(mwo.vat_amount AS FLOAT) AS vat_amount,
            CAST(mwo.total_amount AS FLOAT) AS total_amount,
            mwo.invoice_ref,
            mwo.notes,
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
    params.extend([ps_val, offset])
    rows = await conn.fetch(query, *params)
    data = [WorkOrderOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=p_val, page_size=ps_val, total=total)
    )

@router.post("/maintenance-tickets/{ticket_id}/work-orders", response_model=ResponseEnvelope[WorkOrderOut], status_code=status.HTTP_201_CREATED)
async def create_work_order(
    ticket_id: str,
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

    wo_id = await get_next_id(conn, "maintenance_work_orders", "work_order")
    st = (payload.status or "REQUESTED").upper()
    cost_bearer = (payload.cost_bearer or "OWNER").upper()

    quoted = payload.quoted_amount or 0.0
    vat = payload.vat_amount if payload.vat_amount is not None else round(quoted * 0.15, 2)
    tot = payload.total_amount if payload.total_amount is not None else round(quoted + vat, 2)

    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO maintenance_work_orders (
                work_order_id, ticket_id, vendor_id, assigned_user_id,
                quoted_amount, approved_amount, status, cost_bearer, vat_amount, total_amount,
                invoice_ref, notes
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            """,
            wo_id, ticket_id, payload.vendor_id, payload.assigned_user_id,
            payload.quoted_amount, payload.approved_amount, st, cost_bearer, vat, tot,
            payload.invoice_ref, payload.notes
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
        cost_bearer=cost_bearer,
        quoted_amount=payload.quoted_amount,
        approved_amount=payload.approved_amount,
        vat_amount=vat,
        total_amount=tot,
        invoice_ref=payload.invoice_ref,
        notes=payload.notes,
        completed_at=None,
        status=st
    )
    return ResponseEnvelope(data=out)

@router.post("/work-orders/{work_order_id}/approve", response_model=ResponseEnvelope[dict])
async def approve_work_order(
    work_order_id: str,
    approved_amount: Optional[float] = Query(None),
    conn: asyncpg.Connection = Depends(get_db)
):
    wo = await conn.fetchrow("SELECT work_order_id, quoted_amount, status FROM maintenance_work_orders WHERE work_order_id = $1", work_order_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    final_amount = approved_amount if approved_amount is not None else float(wo["quoted_amount"] or 0.0)
    vat = round(final_amount * 0.15, 2)
    tot = round(final_amount + vat, 2)

    await conn.execute(
        """
        UPDATE maintenance_work_orders 
        SET status = 'APPROVED', approved_amount = $1, vat_amount = $2, total_amount = $3 
        WHERE work_order_id = $4
        """,
        final_amount, vat, tot, work_order_id
    )
    return ResponseEnvelope(data={"work_order_id": str(work_order_id), "status": "APPROVED", "approved_amount": final_amount, "total_amount": tot})

@router.post("/work-orders/{work_order_id}/complete", response_model=ResponseEnvelope[dict])
async def complete_work_order(
    work_order_id: str,
    conn: asyncpg.Connection = Depends(get_db)
):
    wo = await conn.fetchrow("SELECT work_order_id, ticket_id, status FROM maintenance_work_orders WHERE work_order_id = $1", work_order_id)
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")

    now = datetime.now(timezone.utc)
    async with conn.transaction():
        await conn.execute(
            "UPDATE maintenance_work_orders SET status = 'COMPLETED', completed_at = $1 WHERE work_order_id = $2",
            now, work_order_id
        )
        if wo["ticket_id"]:
            # Check if all work orders for this ticket are completed
            pending = await conn.fetchval(
                "SELECT count(*) FROM maintenance_work_orders WHERE ticket_id = $1 AND status != 'COMPLETED'",
                wo["ticket_id"]
            )
            if pending == 0:
                await conn.execute(
                    "UPDATE maintenance_tickets SET status = 'RESOLVED', closed_at = $1 WHERE ticket_id = $2 AND status != 'CLOSED'",
                    now, wo["ticket_id"]
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
    p_val = int(page) if isinstance(page, int) else (int(page.default) if hasattr(page, 'default') else 1)
    ps_val = int(page_size) if isinstance(page_size, int) else (int(page_size.default) if hasattr(page_size, 'default') else 50)
    offset = (p_val - 1) * ps_val
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter and isinstance(status_filter, str):
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
    params.extend([ps_val, offset])
    rows = await conn.fetch(query, *params)
    data = [VendorOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=p_val, page_size=ps_val, total=total)
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

    vendor_id = await get_next_id(conn, "vendors", "vendor")
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
    customer_id: Optional[str] = None,
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    p_val = int(page) if isinstance(page, int) else (int(page.default) if hasattr(page, 'default') else 1)
    ps_val = int(page_size) if isinstance(page_size, int) else (int(page_size.default) if hasattr(page_size, 'default') else 50)
    offset = (p_val - 1) * ps_val
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter and isinstance(status_filter, str):
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
    params.extend([ps_val, offset])
    rows = await conn.fetch(query, *params)
    data = [ManagementContractOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=p_val, page_size=ps_val, total=total)
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

    mc_id = await get_next_id(conn, "management_contracts", "management_contract")
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


# ---------------------------------------------------------
# Owner Relations & Periodic Yield Distributions
# ---------------------------------------------------------
@router.get("/owner-distributions", response_model=CollectionEnvelope[OwnerYieldDistributionOut])
async def list_owner_distributions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    owner_id: Optional[str] = None,
    contract_id: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    p_val = int(page) if isinstance(page, int) else (int(page.default) if hasattr(page, 'default') else 1)
    ps_val = int(page_size) if isinstance(page_size, int) else (int(page_size.default) if hasattr(page_size, 'default') else 50)
    offset = (p_val - 1) * ps_val
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter and isinstance(status_filter, str):
        conditions.append(f"d.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if owner_id:
        conditions.append(f"d.owner_customer_id = ${p_idx}")
        params.append(owner_id)
        p_idx += 1

    if contract_id:
        conditions.append(f"d.management_contract_id = ${p_idx}")
        params.append(contract_id)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"SELECT count(*) FROM owner_yield_distributions d WHERE {where_clause}",
        *params
    ) or 0

    query = f"""
        SELECT 
            d.distribution_id,
            d.management_contract_id,
            mc.contract_number,
            d.owner_customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS owner_name,
            c.mobile AS owner_mobile,
            d.period_start,
            d.period_end,
            CAST(d.gross_rent_collected AS FLOAT) AS gross_rent_collected,
            CAST(d.management_fee_rate AS FLOAT) AS management_fee_rate,
            CAST(d.management_fee_amount AS FLOAT) AS management_fee_amount,
            CAST(d.maintenance_expenses_deducted AS FLOAT) AS maintenance_expenses_deducted,
            CAST(d.other_deductions AS FLOAT) AS other_deductions,
            CAST(d.net_yield_amount AS FLOAT) AS net_yield_amount,
            d.status,
            d.payment_reference,
            d.bank_name,
            d.iban,
            d.paid_at,
            d.notes,
            d.created_at
        FROM owner_yield_distributions d
        JOIN management_contracts mc ON d.management_contract_id = mc.management_contract_id
        JOIN customers c ON d.owner_customer_id = c.customer_id
        WHERE {where_clause}
        ORDER BY d.created_at DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([ps_val, offset])
    rows = await conn.fetch(query, *params)
    data = [OwnerYieldDistributionOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=p_val, page_size=ps_val, total=total)
    )


@router.post("/owner-distributions/calculate", response_model=ResponseEnvelope[OwnerYieldCalculationPreviewOut])
async def calculate_owner_yield_preview(
    payload: OwnerYieldDistributionCalculateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    Simulates / previews periodic yield calculation for a property management contract.
    Reconciles actual rent collections against management fee rate and approved owner maintenance work orders.
    """
    contract = await conn.fetchrow("""
        SELECT mc.*, COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS owner_name
        FROM management_contracts mc
        JOIN customers c ON mc.customer_id = c.customer_id
        WHERE mc.management_contract_id = $1
    """, payload.management_contract_id)

    if not contract:
        raise HTTPException(status_code=404, detail="Management contract not found")

    units = await conn.fetch("""
        SELECT mu.unit_id, u.unit_number, u.rent_price
        FROM managed_units mu
        JOIN units u ON mu.unit_id = u.unit_id
        WHERE mu.management_contract_id = $1
    """, payload.management_contract_id)

    unit_ids = [u["unit_id"] for u in units]

    gross_rent = 0.0
    collections_count = 0
    work_orders_expense = 0.0
    wo_count = 0
    breakdown = []

    if unit_ids:
        # Actual collected rents for these units in the period
        rent_rows = await conn.fetch("""
            SELECT rc.rent_collection_id, rc.amount_paid, t.unit_id, u.unit_number, rc.due_date, rc.paid_at
            FROM rent_collections rc
            JOIN tenancies t ON rc.tenancy_id = t.tenancy_id
            JOIN units u ON t.unit_id = u.unit_id
            WHERE t.unit_id = ANY($1)
              AND rc.status = 'PAID'
              AND (rc.paid_at::date >= $2 AND rc.paid_at::date <= $3)
        """, unit_ids, payload.period_start, payload.period_end)

        if not rent_rows:
            rent_rows = await conn.fetch("""
                SELECT rc.rent_collection_id, rc.amount_paid, t.unit_id, u.unit_number, rc.due_date, rc.paid_at
                FROM rent_collections rc
                JOIN tenancies t ON rc.tenancy_id = t.tenancy_id
                JOIN units u ON t.unit_id = u.unit_id
                WHERE t.unit_id = ANY($1)
                  AND rc.status = 'PAID'
                  AND (rc.due_date >= $2 AND rc.due_date <= $3)
            """, unit_ids, payload.period_start, payload.period_end)

        collections_count = len(rent_rows)
        gross_rent = float(sum(r["amount_paid"] or 0.0 for r in rent_rows))

        # Maintenance work orders charged to OWNER in the period
        wo_rows = await conn.fetch("""
            SELECT mwo.work_order_id, COALESCE(mwo.approved_amount, mwo.quoted_amount, 0) as amount,
                   mt.unit_id, u.unit_number, mt.description
            FROM maintenance_work_orders mwo
            JOIN maintenance_tickets mt ON mwo.ticket_id = mt.ticket_id
            JOIN units u ON mt.unit_id = u.unit_id
            WHERE mt.unit_id = ANY($1)
              AND mwo.status = 'COMPLETED'
              AND mwo.cost_bearer = 'OWNER'
              AND (mwo.completed_at::date >= $2 AND mwo.completed_at::date <= $3)
        """, unit_ids, payload.period_start, payload.period_end)

        wo_count = len(wo_rows)
        work_orders_expense = float(sum(w["amount"] or 0.0 for w in wo_rows))

        for u in units:
            u_rent = sum(float(r["amount_paid"] or 0) for r in rent_rows if r["unit_id"] == u["unit_id"])
            u_wo = sum(float(w["amount"] or 0) for w in wo_rows if w["unit_id"] == u["unit_id"])
            breakdown.append({
                "unit_id": u["unit_id"],
                "unit_number": u["unit_number"],
                "gross_rent": u_rent,
                "maintenance_expense": u_wo,
                "net_unit_yield": round(max(0.0, u_rent - u_wo), 2)
            })

    fee_type = contract["fee_type"] or "PERCENT"
    fee_rate = float(contract["fee_rate"] or 5.0)
    if fee_type == "PERCENT":
        management_fee = round(gross_rent * (fee_rate / 100.0), 2)
    else:
        management_fee = round(fee_rate, 2)

    other_ded = float(payload.other_deductions or 0.0)
    net_yield = round(max(0.0, gross_rent - management_fee - work_orders_expense - other_ded), 2)

    preview = OwnerYieldCalculationPreviewOut(
        management_contract_id=payload.management_contract_id,
        owner_customer_id=contract["customer_id"],
        owner_name=contract["owner_name"],
        contract_number=contract["contract_number"],
        period_start=payload.period_start,
        period_end=payload.period_end,
        fee_type=fee_type,
        management_fee_rate=fee_rate,
        managed_units_count=len(units),
        gross_rent_collected=gross_rent,
        rent_collections_count=collections_count,
        management_fee_amount=management_fee,
        maintenance_expenses_deducted=work_orders_expense,
        work_orders_count=wo_count,
        other_deductions=other_ded,
        net_yield_amount=net_yield,
        units_breakdown=breakdown
    )
    return ResponseEnvelope(data=preview)


@router.post("/owner-distributions", response_model=ResponseEnvelope[OwnerYieldDistributionOut], status_code=status.HTTP_201_CREATED)
async def create_owner_distribution(
    payload: OwnerYieldDistributionCreateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    calc_in = OwnerYieldDistributionCalculateIn(
        management_contract_id=payload.management_contract_id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        other_deductions=payload.other_deductions
    )
    res = await calculate_owner_yield_preview(calc_in, conn=conn)
    preview = res.data

    dist_id = await get_next_id(conn, "owner_yield_distributions", "dist")
    now = datetime.now(timezone.utc)

    await conn.execute("""
        INSERT INTO owner_yield_distributions (
            distribution_id, organization_id, management_contract_id, owner_customer_id,
            period_start, period_end, gross_rent_collected, management_fee_rate,
            management_fee_amount, maintenance_expenses_deducted, other_deductions,
            net_yield_amount, status, notes, created_at, updated_at
        ) VALUES ($1, 'organization-1', $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'DRAFT', $12, $13, $13)
    """,
        dist_id, preview.management_contract_id, preview.owner_customer_id,
        preview.period_start, preview.period_end, preview.gross_rent_collected,
        preview.management_fee_rate, preview.management_fee_amount,
        preview.maintenance_expenses_deducted, preview.other_deductions,
        preview.net_yield_amount, payload.notes, now
    )

    cust = await conn.fetchrow("SELECT mobile FROM customers WHERE customer_id = $1", preview.owner_customer_id)

    out = OwnerYieldDistributionOut(
        distribution_id=dist_id,
        management_contract_id=preview.management_contract_id,
        contract_number=preview.contract_number,
        owner_customer_id=preview.owner_customer_id,
        owner_name=preview.owner_name,
        owner_mobile=cust["mobile"] if cust else None,
        period_start=preview.period_start,
        period_end=preview.period_end,
        gross_rent_collected=preview.gross_rent_collected,
        management_fee_rate=preview.management_fee_rate,
        management_fee_amount=preview.management_fee_amount,
        maintenance_expenses_deducted=preview.maintenance_expenses_deducted,
        other_deductions=preview.other_deductions,
        net_yield_amount=preview.net_yield_amount,
        status="DRAFT",
        payment_reference=None,
        bank_name=None,
        iban=None,
        paid_at=None,
        notes=payload.notes,
        created_at=now
    )
    return ResponseEnvelope(data=out)


@router.post("/owner-distributions/{distribution_id}/approve", response_model=ResponseEnvelope[dict])
async def approve_owner_distribution(
    distribution_id: str,
    conn: asyncpg.Connection = Depends(get_db)
):
    dist = await conn.fetchrow("SELECT distribution_id, status FROM owner_yield_distributions WHERE distribution_id = $1", distribution_id)
    if not dist:
        raise HTTPException(status_code=404, detail="Owner distribution not found")

    await conn.execute("UPDATE owner_yield_distributions SET status = 'APPROVED', updated_at = NOW() WHERE distribution_id = $1", distribution_id)
    return ResponseEnvelope(data={"distribution_id": str(distribution_id), "status": "APPROVED"})


@router.post("/owner-distributions/{distribution_id}/record-payout", response_model=ResponseEnvelope[dict])
async def record_owner_distribution_payout(
    distribution_id: str,
    payload: OwnerYieldDistributionPayoutIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    dist = await conn.fetchrow("SELECT distribution_id, status FROM owner_yield_distributions WHERE distribution_id = $1", distribution_id)
    if not dist:
        raise HTTPException(status_code=404, detail="Owner distribution not found")

    paid_time = payload.paid_at or datetime.now(timezone.utc)

    await conn.execute("""
        UPDATE owner_yield_distributions 
        SET status = 'PAID', 
            payment_reference = $1,
            bank_name = $2,
            iban = $3,
            paid_at = $4,
            notes = COALESCE($5, notes),
            updated_at = NOW()
        WHERE distribution_id = $6
    """, payload.payment_reference, payload.bank_name, payload.iban, paid_time, payload.notes, distribution_id)

    return ResponseEnvelope(data={
        "distribution_id": str(distribution_id),
        "status": "PAID",
        "payment_reference": payload.payment_reference,
        "paid_at": paid_time.isoformat()
    })


@router.get("/owner-distributions/{distribution_id}/statement-html", response_class=HTMLResponse)
async def get_owner_distribution_statement_html(
    distribution_id: str,
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    Renders official, printable, high-fidelity Owner Statement document (كشف حساب المالك وتوزيع العوائد).
    """
    dist = await conn.fetchrow("""
        SELECT d.*, mc.contract_number, mc.fee_type,
               COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS owner_name,
               c.mobile AS owner_mobile, c.email AS owner_email, c.national_id_hash AS owner_id_number
        FROM owner_yield_distributions d
        JOIN management_contracts mc ON d.management_contract_id = mc.management_contract_id
        JOIN customers c ON d.owner_customer_id = c.customer_id
        WHERE d.distribution_id = $1
    """, distribution_id)

    if not dist:
        raise HTTPException(status_code=404, detail="Owner distribution not found")

    units = await conn.fetch("""
        SELECT mu.unit_id, u.unit_number, u.asking_price, b.name as building_name
        FROM managed_units mu
        JOIN units u ON mu.unit_id = u.unit_id
        LEFT JOIN buildings b ON u.building_id = b.building_id
        WHERE mu.management_contract_id = $1
    """, dist["management_contract_id"])

    u_rows_html = "".join([f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{u['unit_number']}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">{u['building_name'] or 'عقار مأهول'}</td>
            <td style="padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: left; font-weight: bold; color: #10b981;">نشط ومؤجر</td>
        </tr>
    """ for u in units]) or "<tr><td colspan='3' style='padding: 10px; text-align: center;'>لا توجد وحدات مسجلة</td></tr>"

    status_badge = {
        "DRAFT": "<span style='background: #fef3c7; color: #92400e; padding: 4px 10px; border-radius: 6px; font-weight: bold;'>مسودة توزيع</span>",
        "APPROVED": "<span style='background: #dbeafe; color: #1e40af; padding: 4px 10px; border-radius: 6px; font-weight: bold;'>معتمد ومعد للصرف</span>",
        "PAID": "<span style='background: #dcfce7; color: #166534; padding: 4px 10px; border-radius: 6px; font-weight: bold;'>تم الصرف والتحويل البنكي</span>"
    }.get(dist["status"], dist["status"])

    html = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>كشف حساب المالك وتوزيع العوائد - {dist['distribution_id']}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 30px; color: #1e293b; background: #fff; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 3px solid #0f172a; padding-bottom: 20px; margin-bottom: 25px; }}
        .header-title h1 {{ margin: 0; font-size: 24px; color: #0f172a; }}
        .header-title p {{ margin: 5px 0 0 0; color: #64748b; font-size: 14px; }}
        .statement-badge {{ text-align: left; }}
        .meta-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px; margin-bottom: 25px; }}
        .meta-item {{ font-size: 14px; }}
        .meta-item span {{ color: #64748b; }}
        .meta-item strong {{ color: #0f172a; margin-right: 5px; }}
        .kpi-cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 30px; }}
        .kpi-box {{ padding: 14px; border-radius: 8px; text-align: center; border: 1px solid #e2e8f0; }}
        .kpi-box.gross {{ background: #f0fdf4; border-color: #bbf7d0; }}
        .kpi-box.fee {{ background: #eff6ff; border-color: #bfdbfe; }}
        .kpi-box.maint {{ background: #fef2f2; border-color: #fecaca; }}
        .kpi-box.net {{ background: #0f172a; color: white; border-color: #0f172a; }}
        .kpi-box h4 {{ margin: 0; font-size: 12px; color: #64748b; }}
        .kpi-box.net h4 {{ color: #94a3b8; }}
        .kpi-box .val {{ font-size: 19px; font-weight: bold; margin-top: 6px; }}
        .kpi-box.net .val {{ color: #38bdf8; font-size: 22px; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 25px; font-size: 14px; }}
        th {{ background: #f1f5f9; padding: 10px; text-align: right; border-bottom: 2px solid #cbd5e1; color: #334155; }}
        .payout-box {{ background: #faf5ff; border: 1px solid #e9d5ff; border-radius: 8px; padding: 18px; margin-top: 20px; }}
        .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e2e8f0; display: flex; justify-content: space-between; font-size: 12px; color: #64748b; }}
        @media print {{ .no-print {{ display: none; }} body {{ padding: 10px; }} }}
    </style>
</head>
<body>
    <div class="no-print" style="margin-bottom: 20px; text-align: left;">
        <button onclick="window.print()" style="background: #0f172a; color: white; border: none; padding: 8px 20px; border-radius: 6px; cursor: pointer; font-family: inherit; font-size: 14px;">🖨️ طباعة كشف الحساب الرسمي</button>
    </div>

    <div class="header">
        <div class="header-title">
            <h1>مكتب معاذ خضر النمري للخدمات العقارية</h1>
            <p>إدارة وتأجير وصيانة الأملاك والمرافق | كشف حساب المالك وتوزيع العوائد الدورية</p>
        </div>
        <div class="statement-badge">
            {status_badge}
            <div style="font-size: 12px; color: #64748b; margin-top: 6px;">رقم السجل: {dist['distribution_id']}</div>
        </div>
    </div>

    <div class="meta-grid">
        <div class="meta-item"><span>اسم المالك:</span> <strong>{dist['owner_name']}</strong></div>
        <div class="meta-item"><span>رقم عقد إدارة الأملاك:</span> <strong>{dist['contract_number']}</strong></div>
        <div class="meta-item"><span>رقم الجوال:</span> <strong>{dist['owner_mobile'] or 'غير مسجل'}</strong></div>
        <div class="meta-item"><span>فترة استحقاق العائد:</span> <strong>{dist['period_start']} إلى {dist['period_end']}</strong></div>
        <div class="meta-item"><span>أتعاب إدارة الأملاك:</span> <strong>{dist['management_fee_rate']}% ({dist['fee_type']})</strong></div>
        <div class="meta-item"><span>تاريخ إصدار الكشف:</span> <strong>{dist['created_at'].strftime('%Y-%m-%d %H:%M')}</strong></div>
    </div>

    <div class="kpi-cards">
        <div class="kpi-box gross">
            <h4>إجمالي الإيجارات المحصلة</h4>
            <div class="val" style="color: #166534;">{float(dist['gross_rent_collected']):,.2f} ر.س</div>
        </div>
        <div class="kpi-box fee">
            <h4>أتعاب إدارة الأملاك المخصومة</h4>
            <div class="val" style="color: #1e40af;">- {float(dist['management_fee_amount']):,.2f} ر.س</div>
        </div>
        <div class="kpi-box maint">
            <h4>مصاريف الصيانة والتشغيل</h4>
            <div class="val" style="color: #991b1b;">- {float(dist['maintenance_expenses_deducted']):,.2f} ر.س</div>
        </div>
        <div class="kpi-box net">
            <h4>صافي العائد المستحق للمالك</h4>
            <div class="val">{float(dist['net_yield_amount']):,.2f} ر.س</div>
        </div>
    </div>

    <h3 style="color: #0f172a; margin-bottom: 12px; font-size: 16px;">🏢 بيان الوحدات العقارية المدارة التابعة للعقد</h3>
    <table>
        <thead>
            <tr>
                <th>رقم الوحدة العقارية</th>
                <th>المبنى / المشروع</th>
                <th style="text-align: left;">حالة الإشغال</th>
            </tr>
        </thead>
        <tbody>
            {u_rows_html}
        </tbody>
    </table>

    <div class="payout-box">
        <h4 style="margin: 0 0 10px 0; color: #6b21a8; font-size: 15px;">💳 بيانات التسوية والتحويل المالي للمالك</h4>
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; font-size: 13px;">
            <div><span style="color: #64748b;">رقم الحوالة البنكية / المرجع:</span> <strong>{dist['payment_reference'] or 'قيد الاعتماد'}</strong></div>
            <div><span style="color: #64748b;">البنك المحول إليه:</span> <strong>{dist['bank_name'] or 'البنك الأهلي السعودي / الراجحي'}</strong></div>
            <div><span style="color: #64748b;">الآيبان المحول له:</span> <strong>{dist['iban'] or '--'}</strong></div>
            <div><span style="color: #64748b;">تاريخ التحويل الفعلي:</span> <strong>{dist['paid_at'].strftime('%Y-%m-%d') if dist['paid_at'] else 'مجدول'}</strong></div>
        </div>
    </div>

    <div class="footer">
        <div>المحاسب المعتمد: إدارة الشؤون المالية وإدارة الأملاك</div>
        <div>ختم واعتماد المكتب: معاذ خضر النمري للخدمات العقارية - ترخيص فال 1200000000</div>
        <div>الصفحة 1 من 1</div>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)
