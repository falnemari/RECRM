import uuid
import json
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException, status, Header
import asyncpg
from app.database import get_db
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.schemas.contracts import (
    ContractOut, ContractCreate, ContractDetailOut, ConvertReservationIn, AdvanceContractIn,
    PaymentOut, PaymentCreate, RecordPaymentIn,
    CommissionOut, CommissionCreate,
    FinanceSummary,
    InvoiceOut, CollectInvoiceIn, GenerateFeeInvoicesIn
)
from app.services.workflow_engine import WorkflowEngine

router = APIRouter(tags=["Contracts, Payments & Commissions"])

async def verify_finance_summary_access(conn: asyncpg.Connection, x_user_id: Optional[str]) -> None:
    """Verifies that the requesting user has central executive financial summary access privileges."""
    if not x_user_id:
        return
    roles = await conn.fetch(
        """
        SELECT r.role_code FROM user_roles ur
        JOIN roles r ON ur.role_id = r.role_id
        WHERE ur.user_id = $1
        """,
        x_user_id
    )
    role_codes = set(r["role_code"].upper() for r in roles if r.get("role_code"))
    allowed_roles = {
        "SYS_ADMIN", "ADMIN", "ACCOUNTANT", "AUDITOR",
        "GENERAL_MANAGER", "BRANCH_MANAGER", "SALES_MANAGER",
        "SALES_DIRECTOR", "DOCUMENT_CONTROL"
    }
    if role_codes.intersection(allowed_roles):
        return

    permissions = await conn.fetch(
        """
        SELECT p.code FROM user_roles ur
        JOIN role_permissions rp ON ur.role_id = rp.role_id
        JOIN permissions p ON rp.permission_id = p.permission_id
        WHERE ur.user_id = $1
        """,
        x_user_id
    )
    perm_codes = set(p["code"].upper() for p in permissions if p.get("code"))
    allowed_perms = {"PAYMENT_READ", "PAYMENT_WRITE", "ADMIN"}
    if perm_codes.intersection(allowed_perms):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden: You do not have permission to access financial records."
    )

async def verify_finance_access(conn: asyncpg.Connection, x_user_id: Optional[str]) -> None:
    """Verifies that the requesting user has financial module access privileges."""
    if not x_user_id:
        return
    # Check assigned roles
    roles = await conn.fetch(
        """
        SELECT r.role_code FROM user_roles ur
        JOIN roles r ON ur.role_id = r.role_id
        WHERE ur.user_id = $1
        """,
        x_user_id
    )
    role_codes = set(r["role_code"].upper() for r in roles if r.get("role_code"))
    allowed_roles = {
        "SYS_ADMIN", "ADMIN", "ACCOUNTANT", "AUDITOR",
        "GENERAL_MANAGER", "BRANCH_MANAGER", "SALES_MANAGER",
        "SALES_DIRECTOR", "DOCUMENT_CONTROL", "SALES_AGENT", "LEASING_AGENT"
    }
    if role_codes.intersection(allowed_roles):
        return

    # Check effective permissions
    permissions = await conn.fetch(
        """
        SELECT p.code FROM user_roles ur
        JOIN role_permissions rp ON ur.role_id = rp.role_id
        JOIN permissions p ON rp.permission_id = p.permission_id
        WHERE ur.user_id = $1
        """,
        x_user_id
    )
    perm_codes = set(p["code"].upper() for p in permissions if p.get("code"))
    allowed_perms = {"PAYMENT_READ", "PAYMENT_WRITE", "ADMIN", "SALES_WRITE", "LEAD_READ"}
    if perm_codes.intersection(allowed_perms):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden: You do not have permission to access financial records."
    )

CONTRACT_SELECT_QUERY = """
    SELECT 
        c.contract_id,
        c.reservation_id,
        r.reservation_number,
        r.customer_id,
        COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
        cust.mobile AS customer_mobile,
        r.unit_id,
        u.unit_number,
        u.owner_customer_id,
        COALESCE(NULLIF(TRIM(CONCAT(owner_cust.first_name, ' ', owner_cust.last_name)), ''), owner_cust.company_name) AS unit_owner_name,
        owner_cust.mobile AS unit_owner_mobile,
        c.contract_number,
        c.contract_type,
        c.start_date,
        c.end_date,
        CAST(COALESCE(c.contract_value, 0) AS FLOAT) AS contract_value,
        c.signed_at,
        c.status,
        CAST(COALESCE((SELECT SUM(amount_paid) FROM payments WHERE contract_id = c.contract_id), 0) AS FLOAT) AS total_paid,
        CAST(COALESCE(c.contract_value, 0) - COALESCE((SELECT SUM(amount_paid) FROM payments WHERE contract_id = c.contract_id), 0) AS FLOAT) AS outstanding_balance
    FROM contracts c
    LEFT JOIN reservations r ON c.reservation_id = r.reservation_id
    LEFT JOIN customers cust ON r.customer_id = cust.customer_id
    LEFT JOIN units u ON r.unit_id = u.unit_id
    LEFT JOIN customers owner_cust ON u.owner_customer_id = owner_cust.customer_id
"""

@router.get("/finance/summary", response_model=ResponseEnvelope[FinanceSummary])
async def get_finance_summary(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_summary_access(conn, x_user_id)
    total_contracts = await conn.fetchval("SELECT count(*) FROM contracts WHERE status NOT IN ('CANCELLED', 'TERMINATED')")
    total_contract_value = await conn.fetchval("SELECT COALESCE(SUM(contract_value), 0) FROM contracts WHERE status NOT IN ('CANCELLED', 'TERMINATED')")
    
    total_payments_due = await conn.fetchval("SELECT COALESCE(SUM(amount_due), 0) FROM payments WHERE status != 'CANCELLED'")
    total_payments_collected = await conn.fetchval("SELECT COALESCE(SUM(amount_paid), 0) FROM payments WHERE status != 'CANCELLED'")
    outstanding_receivables = float(total_payments_due) - float(total_payments_collected)

    total_commissions_amount = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM commissions WHERE status != 'CANCELLED'")
    paid_commissions_amount = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM commissions WHERE status = 'PAID'")
    pending_commissions_amount = float(total_commissions_amount) - float(paid_commissions_amount)

    summary = FinanceSummary(
        total_contracts=total_contracts,
        total_contract_value=float(total_contract_value),
        total_payments_collected=float(total_payments_collected),
        total_payments_due=float(total_payments_due),
        outstanding_receivables=max(0.0, outstanding_receivables),
        total_commissions_amount=float(total_commissions_amount),
        paid_commissions_amount=float(paid_commissions_amount),
        pending_commissions_amount=max(0.0, pending_commissions_amount)
    )
    return ResponseEnvelope(data=summary, meta=BaseMeta())

@router.get("/contracts", response_model=CollectionEnvelope[ContractOut])
async def list_contracts(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    contract_type: Optional[str] = None,
    search: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"c.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if contract_type:
        conditions.append(f"c.contract_type = ${p_idx}")
        params.append(contract_type.upper())
        p_idx += 1

    if search:
        conditions.append(f"(c.contract_number ILIKE ${p_idx} OR cust.first_name ILIKE ${p_idx} OR cust.last_name ILIKE ${p_idx} OR cust.company_name ILIKE ${p_idx} OR u.unit_number ILIKE ${p_idx})")
        params.append(f"%{search}%")
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"SELECT count(*) FROM contracts c LEFT JOIN reservations r ON c.reservation_id = r.reservation_id LEFT JOIN customers cust ON r.customer_id = cust.customer_id LEFT JOIN units u ON r.unit_id = u.unit_id WHERE {where_clause}",
        *params
    )

    query = f"""
        {CONTRACT_SELECT_QUERY}
        WHERE {where_clause}
        ORDER BY c.start_date DESC NULLS LAST, c.contract_number DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [ContractOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.get("/contracts/{contract_id}", response_model=ResponseEnvelope[ContractDetailOut])
async def get_contract_detail(
    contract_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    c_row = await conn.fetchrow(f"{CONTRACT_SELECT_QUERY} WHERE c.contract_id = $1", contract_id)
    if not c_row:
        raise HTTPException(status_code=404, detail="Contract not found")
    contract = ContractOut(**dict(c_row))

    # Payments
    pay_rows = await conn.fetch(
        """
        SELECT 
            payment_id, contract_id, payment_reference, due_date,
            CAST(amount_due AS FLOAT) AS amount_due,
            CAST(amount_paid AS FLOAT) AS amount_paid,
            CAST(amount_due - amount_paid AS FLOAT) AS remaining_balance,
            paid_at, method, status
        FROM payments
        WHERE contract_id = $1
        ORDER BY due_date ASC
        """,
        contract_id
    )
    payments = [PaymentOut(**dict(r)) for r in pay_rows]

    # Commissions
    comm_rows = await conn.fetch(
        """
        SELECT 
            c.commission_id, c.contract_id, c.user_id,
            u.full_name AS user_name,
            c.commission_type,
            CAST(c.rate AS FLOAT) AS rate,
            CAST(c.amount AS FLOAT) AS amount,
            c.status, c.approved_at, c.paid_at
        FROM commissions c
        LEFT JOIN users u ON c.user_id = u.user_id
        WHERE c.contract_id = $1
        ORDER BY c.amount DESC
        """,
        contract_id
    )
    commissions = [CommissionOut(**dict(r)) for r in comm_rows]

    return ResponseEnvelope(
        data=ContractDetailOut(contract=contract, payments=payments, commissions=commissions),
        meta=BaseMeta()
    )

@router.post("/contracts", response_model=ResponseEnvelope[ContractOut], status_code=status.HTTP_201_CREATED)
async def create_contract(payload: ContractCreate, conn: asyncpg.Connection = Depends(get_db)):
    contract_id = await conn.fetchval(
        """
        INSERT INTO contracts (
            reservation_id, contract_number, contract_type,
            start_date, end_date, contract_value, signed_at, status
        ) VALUES (
            $1, $2, $3, $4, $5, $6, now(), $7
        ) RETURNING contract_id
        """,
        payload.reservation_id, payload.contract_number, payload.contract_type.upper(),
        payload.start_date, payload.end_date, payload.contract_value, payload.status.upper()
    )

    row = await conn.fetchrow(f"{CONTRACT_SELECT_QUERY} WHERE c.contract_id = $1", contract_id)
    return ResponseEnvelope(data=ContractOut(**dict(row)), meta=BaseMeta())

@router.post("/reservations/{reservation_id}/initiate-contract", response_model=ResponseEnvelope[ContractOut], status_code=status.HTTP_201_CREATED)
async def initiate_contract(
    reservation_id: str,
    payload: ConvertReservationIn,
    conn: asyncpg.Connection = Depends(get_db),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
):
    try:
        async with conn.transaction():
            res = await WorkflowEngine.initiate_contract_draft(
                conn=conn,
                reservation_id=reservation_id,
                contract_type=payload.contract_type or "SALE",
                contract_value=payload.contract_value,
                start_date=payload.start_date,
                end_date=payload.end_date,
                user_id=x_user_id
            )
            contract_id = res["contract_id"]
            row = await conn.fetchrow(f"{CONTRACT_SELECT_QUERY} WHERE c.contract_id = $1", contract_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ResponseEnvelope(data=ContractOut(**dict(row)), meta=BaseMeta())

@router.post("/contracts/{contract_id}/advance", response_model=ResponseEnvelope[dict])
async def advance_contract(
    contract_id: str,
    payload: AdvanceContractIn,
    conn: asyncpg.Connection = Depends(get_db),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
):
    try:
        async with conn.transaction():
            res = await WorkflowEngine.advance_contract_lifecycle(
                conn=conn,
                contract_id=contract_id,
                action=payload.action,
                payload={"notes": payload.notes} if payload.notes else None,
                user_id=x_user_id
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ResponseEnvelope(data=res, meta=BaseMeta())

@router.post("/reservations/{reservation_id}/convert-to-contract", response_model=ResponseEnvelope[ContractOut], status_code=status.HTTP_201_CREATED)
async def convert_reservation_to_contract(
    reservation_id: str,
    payload: ConvertReservationIn,
    conn: asyncpg.Connection = Depends(get_db),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id")
):
    async with conn.transaction():
        # 1. Fetch reservation
        res = await conn.fetchrow(
            """
            SELECT reservation_id, opportunity_id, unit_id, customer_id, deposit_amount, status
            FROM reservations
            WHERE reservation_id = $1
            """,
            reservation_id
        )
        if not res:
            raise HTTPException(status_code=404, detail="Reservation not found")
        if res["status"] == "CONVERTED":
            raise HTTPException(status_code=400, detail="Reservation has already been converted to a contract")

        # Guard against duplicate contracts for the same reservation
        existing_contract = await conn.fetchrow(
            """
            SELECT contract_id, contract_number, status 
            FROM contracts 
            WHERE reservation_id = $1 AND status NOT IN ('CANCELLED', 'TERMINATED')
            ORDER BY contract_id DESC LIMIT 1
            """,
            reservation_id
        )
        if existing_contract:
            raise HTTPException(
                status_code=400,
                detail=f"يوجد عقد مرتبط بهذا الحجز مسبقاً برقم {existing_contract['contract_number']} بحالة ({existing_contract['status']}). لا يمكن إنشاء عقد مكرر لنفس الحجز."
            )

        # 2. Get accepted offer price, opportunity expected_value, or unit asking price
        if payload.contract_value:
            contract_val = payload.contract_value
        else:
            offer_val = await conn.fetchval(
                "SELECT offer_amount FROM offers WHERE opportunity_id = $1 AND status = 'ACCEPTED' ORDER BY submitted_at DESC LIMIT 1",
                res["opportunity_id"]
            ) if res["opportunity_id"] else None
            if not offer_val and res["opportunity_id"]:
                offer_val = await conn.fetchval("SELECT expected_value FROM opportunities WHERE opportunity_id = $1", res["opportunity_id"])
            unit_price = await conn.fetchval("SELECT asking_price FROM units WHERE unit_id = $1", res["unit_id"])
            contract_val = float(offer_val) if offer_val else (float(unit_price) if unit_price else 500000.0)

        # 3. Generate contract number
        next_num = await conn.fetchval("SELECT count(*) + 1 FROM contracts")
        contract_number = payload.contract_number or f"CON-{next_num:06d}"

        # 4. Insert contract
        contract_id = await conn.fetchval(
            """
            INSERT INTO contracts (
                reservation_id, contract_number, contract_type,
                start_date, end_date, contract_value, signed_at, status
            ) VALUES (
                $1, $2, $3, $4, $5, $6, now(), 'SIGNED'
            ) RETURNING contract_id
            """,
            reservation_id, contract_number, payload.contract_type.upper(),
            payload.start_date or date.today(), payload.end_date, contract_val
        )

        # 5. Mark reservation as CONVERTED
        await conn.execute("UPDATE reservations SET status = 'CONVERTED' WHERE reservation_id = $1", reservation_id)

        # 6. Update Unit status to SOLD with unit_status_history
        await conn.execute("UPDATE units SET status = 'SOLD', updated_at = now() WHERE unit_id = $1", res["unit_id"])
        hist_id = await conn.fetchval("SELECT 'ush-' || nextval('seq_unit_status_history_id')")
        await conn.execute(
            """
            INSERT INTO unit_status_history (
                unit_status_history_id, unit_id, old_status, new_status,
                changed_by_user_id, changed_at, reason
            ) VALUES ($1, $2, 'RESERVED', 'SOLD', $3, now(), $4)
            """,
            hist_id, res["unit_id"], x_user_id, f"تم تحويل الحجز إلى عقد بيع نافذ {contract_number}"
        )

        # 7. Create default payment schedule (Installment 1 = deposit if any, Installment 2 = remaining)
        deposit = float(res["deposit_amount"] or 0)
        pay_idx = await conn.fetchval("SELECT count(*) + 1 FROM payments")
        if deposit > 0:
            await conn.execute(
                """
                INSERT INTO payments (contract_id, payment_reference, due_date, amount_due, amount_paid, paid_at, method, status)
                VALUES ($1, $2, CURRENT_DATE, $3, $3, now(), 'BANK_TRANSFER', 'PAID')
                """,
                contract_id, f"PAY-{pay_idx:06d}", deposit
            )
            pay_idx += 1
            remaining = max(0.0, contract_val - deposit)
            if remaining > 0:
                await conn.execute(
                    """
                    INSERT INTO payments (contract_id, payment_reference, due_date, amount_due, amount_paid, status)
                    VALUES ($1, $2, CURRENT_DATE + 30, $3, 0, 'DUE')
                    """,
                    contract_id, f"PAY-{pay_idx:06d}", remaining
                )
        else:
            await conn.execute(
                """
                INSERT INTO payments (contract_id, payment_reference, due_date, amount_due, amount_paid, status)
                VALUES ($1, $2, CURRENT_DATE + 14, $3, 0, 'DUE')
                """,
                contract_id, f"PAY-{pay_idx:06d}", contract_val
            )

        # 8. Assign default 2.5% broker commission to assigned unit agent or default agent
        agent_id = await conn.fetchval("SELECT assigned_user_id FROM units WHERE unit_id = $1", res["unit_id"])
        if not agent_id:
            agent_id = await conn.fetchval("SELECT user_id FROM users LIMIT 1")
        if agent_id:
            comm_amount = contract_val * 0.025
            await conn.execute(
                """
                INSERT INTO commissions (contract_id, user_id, commission_type, rate, amount, status)
                VALUES ($1, $2, 'SALES', 2.5, $3, 'PENDING')
                """,
                contract_id, agent_id, comm_amount
            )

        # 9. Register Activity ACT_CONTRACT_SIGNED
        opp_id = await conn.fetchval("SELECT opportunity_id FROM reservations WHERE reservation_id = $1", reservation_id)
        if opp_id:
            await conn.execute("UPDATE opportunities SET stage = 'CLOSED_WON', updated_at = NOW() WHERE opportunity_id = $1", opp_id)

        await WorkflowEngine.record_activity_from_template(
            conn=conn,
            template_id="ACT_CONTRACT_SIGNED",
            user_id=x_user_id or agent_id,
            customer_id=res["customer_id"],
            opportunity_id=opp_id,
            outcome="SIGNED",
            notes=f"تم توقيع العقد {contract_number} وإغلاق الصفقة بنجاح.",
            completed_at=datetime.now(timezone.utc)
        )

    row = await conn.fetchrow(f"{CONTRACT_SELECT_QUERY} WHERE c.contract_id = $1", contract_id)
    return ResponseEnvelope(data=ContractOut(**dict(row)), meta=BaseMeta())

@router.get("/payments", response_model=CollectionEnvelope[PaymentOut])
async def list_payments(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    contract_id: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"p.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if contract_id:
        conditions.append(f"p.contract_id = ${p_idx}")
        params.append(contract_id)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"""
        SELECT count(*) 
        FROM payments p
        LEFT JOIN contracts c ON p.contract_id = c.contract_id
        LEFT JOIN reservations r ON c.reservation_id = r.reservation_id
        LEFT JOIN customers cust ON r.customer_id = cust.customer_id
        LEFT JOIN units u ON r.unit_id = u.unit_id
        WHERE {where_clause}
        """,
        *params
    )

    query = f"""
        SELECT 
            p.payment_id, p.contract_id, p.payment_reference, p.due_date,
            CAST(p.amount_due AS FLOAT) AS amount_due,
            CAST(p.amount_paid AS FLOAT) AS amount_paid,
            CAST(p.amount_due - p.amount_paid AS FLOAT) AS remaining_balance,
            p.paid_at, p.method, p.status,
            c.contract_number,
            c.status AS contract_status,
            COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
            u.unit_number
        FROM payments p
        LEFT JOIN contracts c ON p.contract_id = c.contract_id
        LEFT JOIN reservations r ON c.reservation_id = r.reservation_id
        LEFT JOIN customers cust ON r.customer_id = cust.customer_id
        LEFT JOIN units u ON r.unit_id = u.unit_id
        WHERE {where_clause}
        ORDER BY p.due_date ASC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [PaymentOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/payments/{payment_id}/record-payment", response_model=ResponseEnvelope[PaymentOut])
async def record_payment(payment_id: str, payload: RecordPaymentIn, conn: asyncpg.Connection = Depends(get_db)):
    pay = await conn.fetchrow("SELECT amount_due, amount_paid FROM payments WHERE payment_id = $1", payment_id)
    if not pay:
        raise HTTPException(status_code=404, detail="Payment record not found")

    amount_due = float(pay["amount_due"])
    current_paid = float(pay["amount_paid"])
    new_paid = current_paid + payload.amount

    if new_paid > amount_due:
        raise HTTPException(
            status_code=422,
            detail=f"Amount exceeds outstanding balance. Outstanding: {amount_due - current_paid} SAR"
        )

    new_status = "PAID" if new_paid >= amount_due else "PARTIAL"
    await conn.execute(
        """
        UPDATE payments
        SET amount_paid = $1, status = $2, method = $3, paid_at = now()
        WHERE payment_id = $4
        """,
        new_paid, new_status, payload.method.upper(), payment_id
    )

    updated = await conn.fetchrow(
        """
        SELECT 
            p.payment_id, p.contract_id, p.payment_reference, p.due_date,
            CAST(p.amount_due AS FLOAT) AS amount_due,
            CAST(p.amount_paid AS FLOAT) AS amount_paid,
            CAST(p.amount_due - p.amount_paid AS FLOAT) AS remaining_balance,
            p.paid_at, p.method, p.status,
            c.contract_number,
            c.status AS contract_status,
            COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
            u.unit_number
        FROM payments p
        LEFT JOIN contracts c ON p.contract_id = c.contract_id
        LEFT JOIN reservations r ON c.reservation_id = r.reservation_id
        LEFT JOIN customers cust ON r.customer_id = cust.customer_id
        LEFT JOIN units u ON r.unit_id = u.unit_id
        WHERE p.payment_id = $1
        """,
        payment_id
    )
    return ResponseEnvelope(data=PaymentOut(**dict(updated)), meta=BaseMeta())

@router.get("/commissions", response_model=CollectionEnvelope[CommissionOut])
async def list_commissions(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    user_id: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"c.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if user_id:
        conditions.append(f"c.user_id = ${p_idx}")
        params.append(user_id)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"""
        SELECT count(*) 
        FROM commissions c 
        LEFT JOIN contracts con ON c.contract_id = con.contract_id
        LEFT JOIN reservations r ON con.reservation_id = r.reservation_id
        LEFT JOIN customers cust ON r.customer_id = cust.customer_id
        LEFT JOIN units un ON r.unit_id = un.unit_id
        WHERE {where_clause}
        """,
        *params
    )

    query = f"""
        SELECT 
            c.commission_id, c.contract_id, c.user_id,
            u.full_name AS user_name,
            c.commission_type,
            CAST(c.rate AS FLOAT) AS rate,
            CAST(c.amount AS FLOAT) AS amount,
            c.status, c.approved_at, c.paid_at,
            con.contract_number,
            con.status AS contract_status,
            COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
            un.unit_number
        FROM commissions c
        LEFT JOIN users u ON c.user_id = u.user_id
        LEFT JOIN contracts con ON c.contract_id = con.contract_id
        LEFT JOIN reservations r ON con.reservation_id = r.reservation_id
        LEFT JOIN customers cust ON r.customer_id = cust.customer_id
        LEFT JOIN units un ON r.unit_id = un.unit_id
        WHERE {where_clause}
        ORDER BY c.amount DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [CommissionOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/commissions/{commission_id}/approve", response_model=ResponseEnvelope[CommissionOut])
async def approve_commission(commission_id: str, conn: asyncpg.Connection = Depends(get_db)):
    await conn.execute("UPDATE commissions SET status = 'APPROVED', approved_at = now() WHERE commission_id = $1", commission_id)
    row = await conn.fetchrow(
        """
        SELECT 
            c.commission_id, c.contract_id, c.user_id,
            u.full_name AS user_name, c.commission_type,
            CAST(c.rate AS FLOAT) AS rate, CAST(c.amount AS FLOAT) AS amount,
            c.status, c.approved_at, c.paid_at,
            con.contract_number,
            con.status AS contract_status,
            COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
            un.unit_number
        FROM commissions c
        LEFT JOIN users u ON c.user_id = u.user_id
        LEFT JOIN contracts con ON c.contract_id = con.contract_id
        LEFT JOIN reservations r ON con.reservation_id = r.reservation_id
        LEFT JOIN customers cust ON r.customer_id = cust.customer_id
        LEFT JOIN units un ON r.unit_id = un.unit_id
        WHERE c.commission_id = $1
        """,
        commission_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Commission not found")
    return ResponseEnvelope(data=CommissionOut(**dict(row)), meta=BaseMeta())

@router.post("/commissions/{commission_id}/payout", response_model=ResponseEnvelope[CommissionOut])
async def payout_commission(commission_id: str, conn: asyncpg.Connection = Depends(get_db)):
    await conn.execute("UPDATE commissions SET status = 'PAID', paid_at = now() WHERE commission_id = $1", commission_id)
    con_ref = await conn.fetchval("SELECT contract_id FROM commissions WHERE commission_id = $1", commission_id)
    if con_ref:
        await conn.execute(
            """
            UPDATE tasks
            SET status = 'COMPLETED', completed_at = now()
            WHERE template_id = 'TASK_COMMISSION_SETTLEMENT'
              AND status IN ('PENDING', 'OPEN', 'IN_PROGRESS')
              AND (
                  opportunity_id IN (
                      SELECT opportunity_id FROM contracts WHERE contract_id = $1 OR contract_number = $1
                      UNION
                      SELECT r.opportunity_id FROM reservations r JOIN contracts c ON r.reservation_id = c.reservation_id WHERE c.contract_id = $1 OR c.contract_number = $1
                  )
                  OR lead_id IN (
                      SELECT l.lead_id FROM leads l
                      JOIN tenancies t ON l.customer_id = t.tenant_customer_id
                      WHERE t.tenancy_id = $1 OR t.contract_number = $1
                  )
                  OR customer_id IN (
                      SELECT tenant_customer_id FROM tenancies WHERE tenancy_id = $1 OR contract_number = $1
                  )
              )
            """,
            con_ref
        )
    row = await conn.fetchrow(
        """
        SELECT 
            c.commission_id, c.contract_id, c.user_id,
            u.full_name AS user_name, c.commission_type,
            CAST(c.rate AS FLOAT) AS rate, CAST(c.amount AS FLOAT) AS amount,
            c.status, c.approved_at, c.paid_at,
            con.contract_number,
            con.status AS contract_status,
            COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
            un.unit_number
        FROM commissions c
        LEFT JOIN users u ON c.user_id = u.user_id
        LEFT JOIN contracts con ON c.contract_id = con.contract_id
        LEFT JOIN reservations r ON con.reservation_id = r.reservation_id
        LEFT JOIN customers cust ON r.customer_id = cust.customer_id
        LEFT JOIN units un ON r.unit_id = un.unit_id
        WHERE c.commission_id = $1
        """,
        commission_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Commission not found")
    return ResponseEnvelope(data=CommissionOut(**dict(row)), meta=BaseMeta())


# =====================================================================
# Statutory Saudi Fees & Invoices Engine (Tax Invoices for Customer & Owner)
# =====================================================================

INVOICE_SELECT_QUERY = """
    SELECT 
        inv.invoice_id,
        inv.invoice_number,
        inv.invoice_type,
        inv.payer_type,
        inv.payer_customer_id,
        COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS payer_customer_name,
        cust.mobile AS payer_customer_mobile,
        inv.opportunity_id,
        inv.lead_id,
        inv.contract_id,
        inv.unit_id,
        u.unit_number,
        inv.transaction_type,
        CAST(COALESCE(inv.subtotal, 0) AS FLOAT) AS subtotal,
        CAST(COALESCE(inv.vat_rate, 0) AS FLOAT) AS vat_rate,
        CAST(COALESCE(inv.vat_amount, 0) AS FLOAT) AS vat_amount,
        CAST(COALESCE(inv.total_amount, 0) AS FLOAT) AS total_amount,
        CAST(COALESCE(inv.amount_paid, 0) AS FLOAT) AS amount_paid,
        inv.status,
        inv.line_items,
        inv.due_date,
        inv.paid_at,
        inv.payment_method,
        inv.payment_reference,
        inv.notes,
        inv.created_at
    FROM invoices inv
    LEFT JOIN customers cust ON inv.payer_customer_id = cust.customer_id
    LEFT JOIN units u ON inv.unit_id = u.unit_id
"""

def parse_invoice_line_items(row_dict: dict) -> dict:
    items = row_dict.get("line_items")
    if isinstance(items, str):
        try:
            row_dict["line_items"] = json.loads(items)
        except Exception:
            row_dict["line_items"] = []
    elif not isinstance(items, list):
        row_dict["line_items"] = []
    return row_dict

@router.get("/invoices", response_model=CollectionEnvelope[InvoiceOut])
async def list_invoices(
    payer_type: Optional[str] = None,
    status: Optional[str] = None,
    opportunity_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    unit_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    conditions = []
    params = []
    p_idx = 1

    if payer_type:
        conditions.append(f"inv.payer_type = ${p_idx}")
        params.append(payer_type.upper())
        p_idx += 1

    if status:
        conditions.append(f"inv.status = ${p_idx}")
        params.append(status.upper())
        p_idx += 1

    if opportunity_id:
        conditions.append(f"inv.opportunity_id = ${p_idx}")
        params.append(opportunity_id)
        p_idx += 1

    if lead_id:
        conditions.append(f"inv.lead_id = ${p_idx}")
        params.append(lead_id)
        p_idx += 1

    if unit_id:
        conditions.append(f"inv.unit_id = ${p_idx}")
        params.append(unit_id)
        p_idx += 1

    if search:
        conditions.append(f"(inv.invoice_number ILIKE ${p_idx} OR cust.first_name ILIKE ${p_idx} OR cust.last_name ILIKE ${p_idx} OR cust.company_name ILIKE ${p_idx} OR cust.mobile ILIKE ${p_idx})")
        params.append(f"%{search}%")
        p_idx += 1

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count_query = f"SELECT count(*) FROM invoices inv LEFT JOIN customers cust ON inv.payer_customer_id = cust.customer_id {where_clause}"
    total = await conn.fetchval(count_query, *params)

    query = f"{INVOICE_SELECT_QUERY} {where_clause} ORDER BY inv.created_at DESC LIMIT ${p_idx} OFFSET ${p_idx + 1}"
    rows = await conn.fetch(query, *params, limit, offset)

    items = [InvoiceOut(**parse_invoice_line_items(dict(r))) for r in rows]
    return CollectionEnvelope(
        data=items,
        meta=CollectionMeta(total=total, limit=limit, offset=offset)
    )

@router.get("/invoices/{invoice_id}", response_model=ResponseEnvelope[InvoiceOut])
async def get_invoice(
    invoice_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    row = await conn.fetchrow(f"{INVOICE_SELECT_QUERY} WHERE inv.invoice_id = $1", invoice_id)
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return ResponseEnvelope(data=InvoiceOut(**parse_invoice_line_items(dict(row))), meta=BaseMeta())

@router.post("/invoices/{invoice_id}/collect", response_model=ResponseEnvelope[InvoiceOut])
async def collect_invoice(
    invoice_id: str,
    payload: CollectInvoiceIn,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    try:
        res = await WorkflowEngine.collect_fee_invoice(
            conn=conn,
            invoice_id=invoice_id,
            payment_method=payload.payment_method,
            payment_reference=payload.payment_reference,
            amount=payload.amount,
            user_id=x_user_id,
            notes=payload.notes
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

    row = await conn.fetchrow(f"{INVOICE_SELECT_QUERY} WHERE inv.invoice_id = $1", invoice_id)
    return ResponseEnvelope(data=InvoiceOut(**parse_invoice_line_items(dict(row))), meta=BaseMeta())

@router.post("/opportunities/{opp_id}/generate-fee-invoices")
async def generate_opportunity_fee_invoices(
    opp_id: str,
    payload: GenerateFeeInvoicesIn,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    try:
        res = await WorkflowEngine.generate_saudi_fee_invoices(
            conn=conn,
            opportunity_id=opp_id,
            rett_exempt=payload.rett_exempt,
            rett_notes=payload.rett_notes,
            security_deposit=payload.security_deposit or 0.0,
            buyer_brokerage_percent=payload.buyer_brokerage_percent or 2.5,
            seller_brokerage_percent=payload.seller_brokerage_percent or 0.0,
            user_id=x_user_id,
            notes=payload.notes
        )
        return ResponseEnvelope(data=res, meta=BaseMeta())
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

@router.post("/leads/{lead_id}/generate-fee-invoices")
async def generate_lead_fee_invoices(
    lead_id: str,
    payload: GenerateFeeInvoicesIn,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    try:
        res = await WorkflowEngine.generate_saudi_fee_invoices(
            conn=conn,
            lead_id=lead_id,
            rett_exempt=payload.rett_exempt,
            rett_notes=payload.rett_notes,
            security_deposit=payload.security_deposit or 0.0,
            buyer_brokerage_percent=payload.buyer_brokerage_percent or 2.5,
            seller_brokerage_percent=payload.seller_brokerage_percent or 0.0,
            user_id=x_user_id,
            notes=payload.notes
        )
        return ResponseEnvelope(data=res, meta=BaseMeta())
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err))

