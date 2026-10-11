import uuid
from datetime import datetime, date
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException, status
import asyncpg
from app.database import get_db
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.schemas.contracts import (
    ContractOut, ContractCreate, ContractDetailOut, ConvertReservationIn,
    PaymentOut, PaymentCreate, RecordPaymentIn,
    CommissionOut, CommissionCreate,
    FinanceSummary
)

router = APIRouter(tags=["Contracts, Payments & Commissions"])

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
"""

@router.get("/finance/summary", response_model=ResponseEnvelope[FinanceSummary])
async def get_finance_summary(conn: asyncpg.Connection = Depends(get_db)):
    total_contracts = await conn.fetchval("SELECT count(*) FROM contracts")
    total_contract_value = await conn.fetchval("SELECT COALESCE(SUM(contract_value), 0) FROM contracts")
    
    total_payments_due = await conn.fetchval("SELECT COALESCE(SUM(amount_due), 0) FROM payments")
    total_payments_collected = await conn.fetchval("SELECT COALESCE(SUM(amount_paid), 0) FROM payments")
    outstanding_receivables = float(total_payments_due) - float(total_payments_collected)

    total_commissions_amount = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM commissions")
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
    conn: asyncpg.Connection = Depends(get_db)
):
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
async def get_contract_detail(contract_id: str, conn: asyncpg.Connection = Depends(get_db)):
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

@router.post("/reservations/{reservation_id}/convert-to-contract", response_model=ResponseEnvelope[ContractOut], status_code=status.HTTP_201_CREATED)
async def convert_reservation_to_contract(
    reservation_id: str,
    payload: ConvertReservationIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    async with conn.transaction():
        # 1. Fetch reservation
        res = await conn.fetchrow(
            """
            SELECT reservation_id, unit_id, customer_id, deposit_amount, status
            FROM reservations
            WHERE reservation_id = $1
            """,
            reservation_id
        )
        if not res:
            raise HTTPException(status_code=404, detail="Reservation not found")
        if res["status"] == "CONVERTED":
            raise HTTPException(status_code=400, detail="Reservation has already been converted to a contract")

        # 2. Get unit asking/sale price if contract_value is not specified
        unit_price = await conn.fetchval("SELECT asking_price FROM units WHERE unit_id = $1", res["unit_id"])
        contract_val = payload.contract_value or (float(unit_price) if unit_price else 500000.0)

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

        # 6. Update Unit status to SOLD
        await conn.execute("UPDATE units SET status = 'SOLD', updated_at = now() WHERE unit_id = $1", res["unit_id"])

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

    row = await conn.fetchrow(f"{CONTRACT_SELECT_QUERY} WHERE c.contract_id = $1", contract_id)
    return ResponseEnvelope(data=ContractOut(**dict(row)), meta=BaseMeta())

@router.get("/payments", response_model=CollectionEnvelope[PaymentOut])
async def list_payments(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    contract_id: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if contract_id:
        conditions.append(f"contract_id = ${p_idx}")
        params.append(contract_id)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"SELECT count(*) FROM payments WHERE {where_clause}", *params)

    query = f"""
        SELECT 
            payment_id, contract_id, payment_reference, due_date,
            CAST(amount_due AS FLOAT) AS amount_due,
            CAST(amount_paid AS FLOAT) AS amount_paid,
            CAST(amount_due - amount_paid AS FLOAT) AS remaining_balance,
            paid_at, method, status
        FROM payments
        WHERE {where_clause}
        ORDER BY due_date ASC
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
            payment_id, contract_id, payment_reference, due_date,
            CAST(amount_due AS FLOAT) AS amount_due,
            CAST(amount_paid AS FLOAT) AS amount_paid,
            CAST(amount_due - amount_paid AS FLOAT) AS remaining_balance,
            paid_at, method, status
        FROM payments
        WHERE payment_id = $1
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
    conn: asyncpg.Connection = Depends(get_db)
):
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
    total = await conn.fetchval(f"SELECT count(*) FROM commissions c WHERE {where_clause}", *params)

    query = f"""
        SELECT 
            c.commission_id, c.contract_id, c.user_id,
            u.full_name AS user_name,
            c.commission_type,
            CAST(c.rate AS FLOAT) AS rate,
            CAST(c.amount AS FLOAT) AS amount,
            c.status, c.approved_at, c.paid_at
        FROM commissions c
        LEFT JOIN users u ON c.user_id = u.user_id
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
            c.status, c.approved_at, c.paid_at
        FROM commissions c
        LEFT JOIN users u ON c.user_id = u.user_id
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
    row = await conn.fetchrow(
        """
        SELECT 
            c.commission_id, c.contract_id, c.user_id,
            u.full_name AS user_name, c.commission_type,
            CAST(c.rate AS FLOAT) AS rate, CAST(c.amount AS FLOAT) AS amount,
            c.status, c.approved_at, c.paid_at
        FROM commissions c
        LEFT JOIN users u ON c.user_id = u.user_id
        WHERE c.commission_id = $1
        """,
        commission_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Commission not found")
    return ResponseEnvelope(data=CommissionOut(**dict(row)), meta=BaseMeta())

