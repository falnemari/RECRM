import uuid
import json
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException, status, Header
from fastapi.responses import HTMLResponse
import asyncpg
from app.database import get_db
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.schemas.contracts import (
    ContractOut, ContractCreate, ContractDetailOut, ConvertReservationIn, AdvanceContractIn,
    PaymentOut, PaymentCreate, RecordPaymentIn,
    CommissionOut, CommissionCreate,
    FinanceSummary,
    InvoiceOut, CollectInvoiceIn, GenerateFeeInvoicesIn, EditReferenceIn
)
from app.services.workflow_engine import WorkflowEngine
from app.services.calculation_service import CalculationService
from app.services.document_templates import render_invoice_document, render_commission_settlement, render_payment_receipt_document, get_base_html_wrapper

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
        COALESCE(r.customer_id, ten.tenant_customer_id, opp_r.customer_id, dir_l.customer_id) AS customer_id,
        COALESCE(
            NULLIF(TRIM(cust.first_name || ' ' || cust.last_name), ''), cust.company_name,
            NULLIF(TRIM(ten_cust.first_name || ' ' || ten_cust.last_name), ''), ten_cust.company_name,
            NULLIF(TRIM(opp_cust.first_name || ' ' || opp_cust.last_name), ''), opp_cust.company_name,
            NULLIF(TRIM(dir_l_cust.first_name || ' ' || dir_l_cust.last_name), ''), dir_l_cust.company_name
        ) AS customer_name,
        COALESCE(cust.mobile, ten_cust.mobile, opp_cust.mobile, dir_l_cust.mobile) AS customer_mobile,
        COALESCE(r.unit_id, ten.unit_id, opp_u.unit_id, dir_l_u.unit_id) AS unit_id,
        COALESCE(u.unit_number, ten_u.unit_number, opp_u.unit_number, dir_l_u.unit_number) AS unit_number,
        COALESCE(u.owner_customer_id, ten_u.owner_customer_id, opp_u.owner_customer_id, dir_l_u.owner_customer_id) AS owner_customer_id,
        COALESCE(
            NULLIF(TRIM(CONCAT(owner_cust.first_name, ' ', owner_cust.last_name)), ''), owner_cust.company_name,
            NULLIF(TRIM(CONCAT(ten_owner.first_name, ' ', ten_owner.last_name)), ''), ten_owner.company_name,
            NULLIF(TRIM(CONCAT(opp_owner.first_name, ' ', opp_owner.last_name)), ''), opp_owner.company_name,
            NULLIF(TRIM(CONCAT(dir_l_owner.first_name, ' ', dir_l_owner.last_name)), ''), dir_l_owner.company_name
        ) AS unit_owner_name,
        COALESCE(owner_cust.mobile, ten_owner.mobile, opp_owner.mobile, dir_l_owner.mobile) AS unit_owner_mobile,
        c.contract_number,
        c.contract_type,
        c.start_date,
        c.end_date,
        CAST(COALESCE(c.contract_value, 0) AS FLOAT) AS contract_value,
        c.signed_at,
        c.status,
        CAST(COALESCE((SELECT SUM(amount_paid) FROM payments WHERE contract_id = c.contract_id), (SELECT SUM(amount_paid) FROM rent_collections rc WHERE rc.tenancy_id = ten.tenancy_id), 0) AS FLOAT) AS total_paid,
        CAST(COALESCE(c.contract_value, 0) - COALESCE((SELECT SUM(amount_paid) FROM payments WHERE contract_id = c.contract_id), (SELECT SUM(amount_paid) FROM rent_collections rc WHERE rc.tenancy_id = ten.tenancy_id), 0) AS FLOAT) AS outstanding_balance,
        ten.payment_frequency,
        ten.bank_name,
        ten.bank_iban,
        ten.bank_beneficiary,
        ten.maintenance_terms,
        COALESCE(ten.notes, '') AS notes,
        COALESCE(ten.ejar_contract_number, c.contract_number) AS ejar_contract_number,
        COALESCE(c.opportunity_id, r.opportunity_id, ten.opportunity_id, (SELECT opportunity_id FROM opportunities WHERE customer_id = ten_cust.customer_id ORDER BY created_at DESC LIMIT 1)) AS opportunity_id,
        COALESCE(c.lead_id, opp_r.lead_id, ten.lead_id, dir_l.lead_id, (SELECT lead_id FROM leads WHERE customer_id = ten_cust.customer_id ORDER BY created_at DESC LIMIT 1)) AS lead_id
    FROM contracts c
    LEFT JOIN reservations r ON c.reservation_id = r.reservation_id
    LEFT JOIN opportunities opp_r ON COALESCE(c.opportunity_id, r.opportunity_id) = opp_r.opportunity_id
    LEFT JOIN leads dir_l ON COALESCE(c.lead_id, opp_r.lead_id) = dir_l.lead_id
    LEFT JOIN customers cust ON r.customer_id = cust.customer_id
    LEFT JOIN units u ON r.unit_id = u.unit_id
    LEFT JOIN customers owner_cust ON u.owner_customer_id = owner_cust.customer_id
    LEFT JOIN tenancies ten ON (c.contract_number = ten.contract_number OR c.contract_id = ten.contract_number)
    LEFT JOIN customers ten_cust ON ten.tenant_customer_id = ten_cust.customer_id
    LEFT JOIN units ten_u ON ten.unit_id = ten_u.unit_id
    LEFT JOIN customers ten_owner ON ten_u.owner_customer_id = ten_owner.customer_id
    LEFT JOIN customers opp_cust ON opp_r.customer_id = opp_cust.customer_id
    LEFT JOIN units opp_u ON (SELECT unit_id FROM opportunity_units WHERE opportunity_id = opp_r.opportunity_id ORDER BY is_primary DESC LIMIT 1) = opp_u.unit_id
    LEFT JOIN customers opp_owner ON opp_u.owner_customer_id = opp_owner.customer_id
    LEFT JOIN customers dir_l_cust ON dir_l.customer_id = dir_l_cust.customer_id
    LEFT JOIN units dir_l_u ON dir_l.unit_id = dir_l_u.unit_id
    LEFT JOIN customers dir_l_owner ON dir_l_u.owner_customer_id = dir_l_owner.customer_id
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
    page_size: int = Query(50, ge=1, le=1000),
    status_filter: Optional[str] = Query(None, alias="status"),
    contract_type: Optional[str] = None,
    lead_id: Optional[str] = None,
    opportunity_id: Optional[str] = None,
    search: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    offset = (page - 1) * page_size
    conditions = ["1=1", "(c.lead_id IS NOT NULL OR c.opportunity_id IS NOT NULL OR r.opportunity_id IS NOT NULL OR ten.lead_id IS NOT NULL OR ten.opportunity_id IS NOT NULL OR ten_cust.customer_id IS NOT NULL)"]
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

    if lead_id:
        conditions.append(f"(c.lead_id = ${p_idx} OR opp_r.lead_id = ${p_idx} OR ten.lead_id = ${p_idx} OR dir_l.lead_id = ${p_idx} OR EXISTS (SELECT 1 FROM leads WHERE customer_id = ten_cust.customer_id AND lead_id = ${p_idx}))")
        params.append(lead_id)
        p_idx += 1

    if opportunity_id:
        conditions.append(f"(c.opportunity_id = ${p_idx} OR r.opportunity_id = ${p_idx} OR ten.opportunity_id = ${p_idx} OR EXISTS (SELECT 1 FROM opportunities WHERE customer_id = ten_cust.customer_id AND opportunity_id = ${p_idx}))")
        params.append(opportunity_id)
        p_idx += 1

    if search:
        conditions.append(f"""(
            c.contract_number ILIKE ${p_idx} 
            OR c.contract_id ILIKE ${p_idx}
            OR c.lead_id ILIKE ${p_idx}
            OR c.opportunity_id ILIKE ${p_idx}
            OR r.opportunity_id ILIKE ${p_idx}
            OR opp_r.lead_id ILIKE ${p_idx}
            OR cust.first_name ILIKE ${p_idx} 
            OR cust.last_name ILIKE ${p_idx} 
            OR cust.company_name ILIKE ${p_idx} 
            OR ten_cust.first_name ILIKE ${p_idx} 
            OR ten_cust.last_name ILIKE ${p_idx} 
            OR ten_cust.company_name ILIKE ${p_idx} 
            OR opp_cust.first_name ILIKE ${p_idx}
            OR opp_cust.last_name ILIKE ${p_idx}
            OR opp_cust.company_name ILIKE ${p_idx}
            OR u.unit_number ILIKE ${p_idx}
            OR ten_u.unit_number ILIKE ${p_idx}
            OR opp_u.unit_number ILIKE ${p_idx}
        )""")
        params.append(f"%{search}%")
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"""
        SELECT count(*) 
        FROM contracts c 
        LEFT JOIN reservations r ON c.reservation_id = r.reservation_id 
        LEFT JOIN opportunities opp_r ON COALESCE(c.opportunity_id, r.opportunity_id) = opp_r.opportunity_id
        LEFT JOIN leads dir_l ON COALESCE(c.lead_id, opp_r.lead_id) = dir_l.lead_id
        LEFT JOIN customers cust ON r.customer_id = cust.customer_id 
        LEFT JOIN units u ON r.unit_id = u.unit_id 
        LEFT JOIN tenancies ten ON (c.contract_number = ten.contract_number OR c.contract_id = ten.contract_number)
        LEFT JOIN customers ten_cust ON ten.tenant_customer_id = ten_cust.customer_id
        LEFT JOIN units ten_u ON ten.unit_id = ten_u.unit_id
        LEFT JOIN customers opp_cust ON opp_r.customer_id = opp_cust.customer_id
        LEFT JOIN units opp_u ON (SELECT unit_id FROM opportunity_units WHERE opportunity_id = opp_r.opportunity_id ORDER BY is_primary DESC LIMIT 1) = opp_u.unit_id
        WHERE {where_clause}
        """,
        *params
    )

    query = f"""
        {CONTRACT_SELECT_QUERY}
        WHERE {where_clause}
        ORDER BY CAST(substring(c.contract_id from '[0-9]+') AS INTEGER) DESC, c.signed_at DESC NULLS LAST
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
    if not pay_rows and c_row and c_row["contract_number"]:
        rc_rows = await conn.fetch(
            """
            SELECT 
                rc.rent_collection_id AS payment_id,
                $1 AS contract_id,
                rc.rent_collection_id AS payment_reference,
                rc.due_date,
                CAST(rc.amount_due AS FLOAT) AS amount_due,
                CAST(rc.amount_paid AS FLOAT) AS amount_paid,
                CAST(rc.amount_due - rc.amount_paid AS FLOAT) AS remaining_balance,
                rc.paid_at,
                'RENT_INSTALLMENT' AS method,
                rc.status
            FROM rent_collections rc
            JOIN tenancies ten ON rc.tenancy_id = ten.tenancy_id
            WHERE ten.contract_number = $2 OR ten.tenancy_id = $2
            ORDER BY rc.due_date ASC
            """,
            contract_id, c_row["contract_number"]
        )
        payments = [PaymentOut(**dict(r)) for r in rc_rows]
    else:
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
            c.status, c.approved_at, c.paid_at,
            c.compensation_type,
            CAST(c.gross_deal_value AS FLOAT) AS gross_deal_value,
            CAST(c.gross_brokerage_amount AS FLOAT) AS gross_brokerage_amount,
            CAST(c.gov_fees_deducted AS FLOAT) AS gov_fees_deducted,
            CAST(c.net_commission_base AS FLOAT) AS net_commission_base,
            c.calculation_notes
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

        # 8. Calculate and assign broker commission based on agent compensation profile
        agent_id = await conn.fetchval("SELECT assigned_user_id FROM units WHERE unit_id = $1", res["unit_id"])
        if not agent_id:
            agent_id = await conn.fetchval("SELECT user_id FROM users LIMIT 1")
        if agent_id:
            agent_profile = await conn.fetchrow("""
                SELECT user_id, full_name, compensation_type, 
                       CAST(base_salary AS FLOAT) AS base_salary,
                       CAST(sales_commission_rate AS FLOAT) AS sales_commission_rate,
                       CAST(rent_commission_rate AS FLOAT) AS rent_commission_rate,
                       CAST(sales_fixed_cut AS FLOAT) AS sales_fixed_cut,
                       CAST(rent_fixed_cut AS FLOAT) AS rent_fixed_cut
                FROM users WHERE user_id = $1
            """, agent_id)

            calc = CalculationService.calculate_agent_commission(
                transaction_type="SALE",
                deal_value=contract_val,
                agent_profile=dict(agent_profile) if agent_profile else None
            )

            comm_id = await conn.fetchval("SELECT ('comm-' || nextval('seq_commissions_id'))")
            await conn.execute(
                """
                INSERT INTO commissions (
                    commission_id, contract_id, user_id, commission_type, rate, amount, status,
                    compensation_type, gross_deal_value, gross_brokerage_amount,
                    gov_fees_deducted, net_commission_base, calculation_notes
                )
                VALUES ($1, $2, $3, 'SALES', $4, $5, $6, $7, $8, $9, $10, $11, $12)
                """,
                comm_id, contract_id, agent_id, calc["rate"], calc["amount"], calc["status"],
                calc["compensation_type"], calc["gross_deal_value"], calc["gross_brokerage_amount"],
                calc["gov_fees_deducted"], calc["net_commission_base"], calc["calculation_notes"]
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
    page_size: int = Query(50, ge=1, le=1000),
    status_filter: Optional[str] = Query(None, alias="status"),
    contract_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    opportunity_id: Optional[str] = None,
    search: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    offset = (page - 1) * page_size
    conditions = ["1=1", "(p.lead_id IS NOT NULL OR p.opportunity_id IS NOT NULL)"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"p.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if contract_id:
        conditions.append(f"(p.contract_id = ${p_idx} OR p.contract_number = ${p_idx})")
        params.append(contract_id)
        p_idx += 1

    if lead_id and opportunity_id:
        conditions.append(f"(p.lead_id = ${p_idx} OR p.opportunity_id = ${p_idx + 1})")
        params.extend([lead_id, opportunity_id])
        p_idx += 2
    elif lead_id:
        conditions.append(f"p.lead_id = ${p_idx}")
        params.append(lead_id)
        p_idx += 1
    elif opportunity_id:
        conditions.append(f"p.opportunity_id = ${p_idx}")
        params.append(opportunity_id)
        p_idx += 1

    if search and search.strip():
        s_term = f"%{search.strip()}%"
        conditions.append(f"""(
            p.payment_reference ILIKE ${p_idx} OR
            p.payment_id ILIKE ${p_idx} OR
            p.contract_number ILIKE ${p_idx} OR
            p.customer_name ILIKE ${p_idx} OR
            p.unit_number ILIKE ${p_idx} OR
            p.lead_id ILIKE ${p_idx} OR
            p.opportunity_id ILIKE ${p_idx}
        )""")
        params.append(s_term)
        p_idx += 1

    where_clause = " AND ".join(conditions)

    unified_from = """
        FROM (
            SELECT 
                p.payment_id, p.contract_id, p.payment_reference, p.due_date,
                CAST(p.amount_due AS FLOAT) AS amount_due,
                CAST(p.amount_paid AS FLOAT) AS amount_paid,
                CAST(p.amount_due - p.amount_paid AS FLOAT) AS remaining_balance,
                p.paid_at, p.method, p.status,
                c.contract_number,
                c.status AS contract_status,
                COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
                u.unit_number,
                c.lead_id,
                c.opportunity_id
            FROM payments p
            LEFT JOIN contracts c ON p.contract_id = c.contract_id
            LEFT JOIN reservations r ON c.reservation_id = r.reservation_id
            LEFT JOIN customers cust ON r.customer_id = cust.customer_id
            LEFT JOIN units u ON r.unit_id = u.unit_id

            UNION ALL

            SELECT 
                rc.rent_collection_id AS payment_id,
                COALESCE(con.contract_id, ten.tenancy_id, rc.tenancy_id) AS contract_id,
                rc.rent_collection_id AS payment_reference,
                rc.due_date,
                CAST(rc.amount_due AS FLOAT) AS amount_due,
                CAST(rc.amount_paid AS FLOAT) AS amount_paid,
                CAST(rc.amount_due - rc.amount_paid AS FLOAT) AS remaining_balance,
                rc.paid_at,
                'RENT_INSTALLMENT' AS method,
                rc.status,
                ten.contract_number,
                ten.status AS contract_status,
                COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
                u.unit_number,
                COALESCE(con.lead_id, ten.lead_id) AS lead_id,
                COALESCE(con.opportunity_id, ten.opportunity_id) AS opportunity_id
            FROM rent_collections rc
            JOIN tenancies ten ON rc.tenancy_id = ten.tenancy_id
            LEFT JOIN contracts con ON (ten.contract_number = con.contract_number OR ten.tenancy_id = con.contract_number)
            LEFT JOIN customers cust ON ten.tenant_customer_id = cust.customer_id
            LEFT JOIN units u ON ten.unit_id = u.unit_id
        ) p
    """

    total = await conn.fetchval(
        f"SELECT count(*) {unified_from} WHERE {where_clause}",
        *params
    )

    query = f"""
        SELECT 
            p.payment_id, p.contract_id, p.payment_reference, p.due_date,
            p.amount_due, p.amount_paid, p.remaining_balance,
            p.paid_at, p.method, p.status,
            p.contract_number, p.contract_status,
            p.customer_name, p.unit_number,
            p.lead_id, p.opportunity_id
        {unified_from}
        WHERE {where_clause}
        ORDER BY CAST(substring(p.payment_id from '[0-9]+') AS INTEGER) DESC, p.due_date DESC NULLS LAST
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
        rc = await conn.fetchrow("SELECT amount_due, amount_paid, tenancy_id FROM rent_collections WHERE rent_collection_id = $1", payment_id)
        if not rc:
            raise HTTPException(status_code=404, detail="Payment record not found")
        amount_due = float(rc["amount_due"])
        current_paid = float(rc["amount_paid"] or 0)
        new_paid = current_paid + payload.amount
        if new_paid > amount_due:
            raise HTTPException(status_code=400, detail=f"Amount exceeds remaining balance. Max allowed: {amount_due - current_paid}")
        new_status = "PAID" if new_paid >= amount_due else "PARTIAL"
        now_dt = datetime.now(timezone.utc)
        await conn.execute(
            """
            UPDATE rent_collections
            SET amount_paid = $1, status = $2, paid_at = $3
            WHERE rent_collection_id = $4
            """,
            new_paid, new_status, now_dt, payment_id
        )
        row = await conn.fetchrow(
            """
            SELECT 
                rc.rent_collection_id AS payment_id,
                con.contract_id,
                rc.rent_collection_id AS payment_reference,
                rc.due_date,
                CAST(rc.amount_due AS FLOAT) AS amount_due,
                CAST(rc.amount_paid AS FLOAT) AS amount_paid,
                CAST(rc.amount_due - rc.amount_paid AS FLOAT) AS remaining_balance,
                rc.paid_at,
                'RENT_INSTALLMENT' AS method,
                rc.status,
                ten.contract_number,
                ten.status AS contract_status,
                COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
                u.unit_number
            FROM rent_collections rc
            JOIN tenancies ten ON rc.tenancy_id = ten.tenancy_id
            LEFT JOIN contracts con ON (ten.contract_number = con.contract_number OR ten.tenancy_id = con.contract_number)
            LEFT JOIN customers cust ON ten.tenant_customer_id = cust.customer_id
            LEFT JOIN units u ON ten.unit_id = u.unit_id
            WHERE rc.rent_collection_id = $1
            """,
            payment_id
        )
        return ResponseEnvelope(data=PaymentOut(**dict(row)), meta=BaseMeta())

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

@router.get("/payments/{payment_id}/html", response_class=HTMLResponse)
async def get_payment_html(
    payment_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    # Check rent_collections first if starts with rent_collection
    row = None
    if payment_id.startswith("rent_collection-"):
        row = await conn.fetchrow(
            """
            SELECT 
                rc.rent_collection_id AS payment_id,
                rc.rent_collection_id AS payment_reference,
                CAST(rc.amount_due AS FLOAT) AS amount_due,
                CAST(rc.amount_paid AS FLOAT) AS amount_paid,
                CAST(rc.amount_due - rc.amount_paid AS FLOAT) AS remaining_balance,
                rc.due_date,
                rc.paid_at,
                rc.status,
                'EJAR_ONLINE' AS method,
                ten.contract_number,
                COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
                u.unit_number,
                ten.bank_name,
                ten.bank_iban,
                'دفعة إيجار تعاقدية' AS installment_label
            FROM rent_collections rc
            JOIN tenancies ten ON rc.tenancy_id = ten.tenancy_id
            LEFT JOIN customers cust ON ten.tenant_customer_id = cust.customer_id
            LEFT JOIN units u ON ten.unit_id = u.unit_id
            WHERE rc.rent_collection_id = $1
            """,
            payment_id
        )
    if not row:
        row = await conn.fetchrow(
            """
            SELECT 
                p.payment_id,
                p.payment_reference,
                CAST(p.amount_due AS FLOAT) AS amount_due,
                CAST(p.amount_paid AS FLOAT) AS amount_paid,
                CAST(p.amount_due - p.amount_paid AS FLOAT) AS remaining_balance,
                p.due_date,
                p.paid_at,
                p.status,
                p.method,
                c.contract_number,
                COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
                u.unit_number,
                c.bank_name,
                c.bank_iban,
                'دفعة تعاقدية مبيعات' AS installment_label
            FROM payments p
            LEFT JOIN contracts c ON p.contract_id = c.contract_id
            LEFT JOIN reservations r ON c.reservation_id = r.reservation_id
            LEFT JOIN customers cust ON r.customer_id = cust.customer_id
            LEFT JOIN units u ON r.unit_id = u.unit_id
            WHERE p.payment_id = $1
            """,
            payment_id
        )

    if not row:
        raise HTTPException(status_code=404, detail="Payment receipt record not found")

    pay_dict = dict(row)
    rec_num = pay_dict.get("payment_reference") or pay_dict.get("payment_id")
    meta_dict = {
        "receipt_number": f"REC-{rec_num}",
        "payment_date": str((pay_dict.get("paid_at") or pay_dict.get("due_date") or date.today()))[:10],
        "amount_paid": float(pay_dict.get("amount_paid") or pay_dict.get("amount_due") or 0.0),
        "amount_due": float(pay_dict.get("amount_due") or 0.0),
        "remaining_balance": float(pay_dict.get("remaining_balance") or 0.0),
        "customer_name": pay_dict.get("customer_name") or "العميل",
        "contract_number": pay_dict.get("contract_number") or "--",
        "unit_number": pay_dict.get("unit_number") or "--",
        "payment_method": pay_dict.get("method") or "BANK_TRANSFER",
        "bank_name": pay_dict.get("bank_name") or "مصرف الراجحي",
        "bank_iban": pay_dict.get("bank_iban") or "SA0380000000608010167890",
        "installment_label": pay_dict.get("installment_label") or "دفعة تعاقدية",
        "notes": f"سداد الدفعة المتعلقة بالعقد {pay_dict.get('contract_number', '')} وقيد السداد في النظام المحاسبي."
    }

    html_content = render_payment_receipt_document(pay_dict, meta=meta_dict)
    full_html = get_base_html_wrapper(
        title=f"سند قبض مالي - {meta_dict['receipt_number']}",
        content=html_content,
        doc_ref=meta_dict["receipt_number"],
        doc_date=meta_dict["payment_date"]
    )
    return HTMLResponse(content=full_html)

@router.get("/commissions", response_model=CollectionEnvelope[CommissionOut])
async def list_commissions(
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
    status_filter: Optional[str] = Query(None, alias="status"),
    user_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    opportunity_id: Optional[str] = None,
    search: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    offset = (page - 1) * page_size
    conditions = ["1=1", "(con.lead_id IS NOT NULL OR con.opportunity_id IS NOT NULL OR r.opportunity_id IS NOT NULL OR ten.lead_id IS NOT NULL OR ten.opportunity_id IS NOT NULL OR cust.customer_id IS NOT NULL)"]
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

    if lead_id:
        conditions.append(f"(con.lead_id = ${p_idx} OR opp_con.lead_id = ${p_idx} OR ten.lead_id = ${p_idx} OR EXISTS (SELECT 1 FROM leads WHERE customer_id = cust.customer_id AND lead_id = ${p_idx}))")
        params.append(lead_id)
        p_idx += 1

    if opportunity_id:
        conditions.append(f"(con.opportunity_id = ${p_idx} OR r.opportunity_id = ${p_idx} OR ten.opportunity_id = ${p_idx} OR EXISTS (SELECT 1 FROM opportunities WHERE customer_id = cust.customer_id AND opportunity_id = ${p_idx}))")
        params.append(opportunity_id)
        p_idx += 1

    if search and search.strip():
        s_term = f"%{search.strip()}%"
        conditions.append(f"""(
            c.commission_id ILIKE ${p_idx} OR
            u.full_name ILIKE ${p_idx} OR
            con.contract_number ILIKE ${p_idx} OR
            con.lead_id ILIKE ${p_idx} OR
            con.opportunity_id ILIKE ${p_idx} OR
            r.opportunity_id ILIKE ${p_idx} OR
            opp_con.lead_id ILIKE ${p_idx} OR
            cust.first_name ILIKE ${p_idx} OR
            cust.last_name ILIKE ${p_idx} OR
            cust.company_name ILIKE ${p_idx} OR
            un.unit_number ILIKE ${p_idx}
        )""")
        params.append(s_term)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"""
        SELECT count(*) 
        FROM commissions c 
        LEFT JOIN users u ON c.user_id = u.user_id
        LEFT JOIN contracts con ON c.contract_id = con.contract_id
        LEFT JOIN reservations r ON con.reservation_id = r.reservation_id
        LEFT JOIN opportunities opp_con ON COALESCE(con.opportunity_id, r.opportunity_id) = opp_con.opportunity_id
        LEFT JOIN tenancies ten ON (con.contract_number = ten.contract_number OR con.contract_id = ten.contract_number)
        LEFT JOIN customers cust ON COALESCE(r.customer_id, ten.tenant_customer_id) = cust.customer_id
        LEFT JOIN units un ON COALESCE(r.unit_id, ten.unit_id) = un.unit_id
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
            c.compensation_type,
            CAST(c.gross_deal_value AS FLOAT) AS gross_deal_value,
            CAST(c.gross_brokerage_amount AS FLOAT) AS gross_brokerage_amount,
            CAST(c.gov_fees_deducted AS FLOAT) AS gov_fees_deducted,
            CAST(c.net_commission_base AS FLOAT) AS net_commission_base,
            c.calculation_notes,
            con.contract_number,
            con.status AS contract_status,
            COALESCE(NULLIF(TRIM(cust.first_name || ' ' || cust.last_name), ''), cust.company_name, NULLIF(TRIM(opp_cust.first_name || ' ' || opp_cust.last_name), ''), opp_cust.company_name, NULLIF(TRIM(dir_l_cust.first_name || ' ' || dir_l_cust.last_name), ''), dir_l_cust.company_name) AS customer_name,
            COALESCE(un.unit_number, opp_u.unit_number, dir_l_u.unit_number) AS unit_number,
            COALESCE(con.lead_id, opp_con.lead_id, ten.lead_id, dir_l.lead_id, (SELECT lead_id FROM leads WHERE customer_id = cust.customer_id ORDER BY created_at DESC LIMIT 1)) AS lead_id,
            COALESCE(con.opportunity_id, r.opportunity_id, ten.opportunity_id, (SELECT opportunity_id FROM opportunities WHERE customer_id = cust.customer_id ORDER BY created_at DESC LIMIT 1)) AS opportunity_id
        FROM commissions c
        LEFT JOIN users u ON c.user_id = u.user_id
        LEFT JOIN contracts con ON c.contract_id = con.contract_id
        LEFT JOIN reservations r ON con.reservation_id = r.reservation_id
        LEFT JOIN opportunities opp_con ON COALESCE(con.opportunity_id, r.opportunity_id) = opp_con.opportunity_id
        LEFT JOIN leads dir_l ON COALESCE(con.lead_id, opp_con.lead_id) = dir_l.lead_id
        LEFT JOIN tenancies ten ON (con.contract_number = ten.contract_number OR con.contract_id = ten.contract_number)
        LEFT JOIN customers cust ON COALESCE(r.customer_id, ten.tenant_customer_id) = cust.customer_id
        LEFT JOIN customers opp_cust ON opp_con.customer_id = opp_cust.customer_id
        LEFT JOIN customers dir_l_cust ON dir_l.customer_id = dir_l_cust.customer_id
        LEFT JOIN units un ON COALESCE(r.unit_id, ten.unit_id) = un.unit_id
        LEFT JOIN units opp_u ON (SELECT unit_id FROM opportunity_units WHERE opportunity_id = opp_con.opportunity_id ORDER BY is_primary DESC LIMIT 1) = opp_u.unit_id
        LEFT JOIN units dir_l_u ON dir_l.unit_id = dir_l_u.unit_id
        WHERE {where_clause}
        ORDER BY CAST(substring(c.commission_id from '[0-9]+') AS INTEGER) DESC
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
            c.compensation_type,
            CAST(c.gross_deal_value AS FLOAT) AS gross_deal_value,
            CAST(c.gross_brokerage_amount AS FLOAT) AS gross_brokerage_amount,
            CAST(c.gov_fees_deducted AS FLOAT) AS gov_fees_deducted,
            CAST(c.net_commission_base AS FLOAT) AS net_commission_base,
            c.calculation_notes,
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

@router.get("/commissions/{commission_id}/html", response_class=HTMLResponse)
async def get_commission_html(
    commission_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    row = await conn.fetchrow(
        """
        SELECT 
            c.commission_id, c.contract_id, c.user_id,
            u.full_name AS user_name, c.commission_type,
            CAST(c.rate AS FLOAT) AS rate, CAST(c.amount AS FLOAT) AS amount,
            c.status, c.approved_at, c.paid_at,
            c.compensation_type,
            CAST(c.gross_deal_value AS FLOAT) AS gross_deal_value,
            CAST(c.gross_brokerage_amount AS FLOAT) AS gross_brokerage_amount,
            CAST(c.gov_fees_deducted AS FLOAT) AS gov_fees_deducted,
            CAST(c.net_commission_base AS FLOAT) AS net_commission_base,
            c.calculation_notes,
            COALESCE(con.contract_number, ten.contract_number, c.contract_id) AS contract_number,
            COALESCE(con.status, ten.status) AS contract_status,
            COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
            COALESCE(un.unit_number, un2.unit_number) AS unit_number
        FROM commissions c
        LEFT JOIN users u ON c.user_id = u.user_id
        LEFT JOIN contracts con ON (c.contract_id = con.contract_id OR c.contract_id = con.contract_number)
        LEFT JOIN reservations r ON con.reservation_id = r.reservation_id
        LEFT JOIN tenancies ten ON (con.contract_number = ten.contract_number OR c.contract_id = ten.tenancy_id OR c.contract_id = ten.contract_number)
        LEFT JOIN customers cust ON COALESCE(r.customer_id, ten.tenant_customer_id) = cust.customer_id
        LEFT JOIN units un ON COALESCE(con.contract_id, ten.unit_id) = un.unit_id
        LEFT JOIN units un2 ON c.contract_id = un2.unit_id
        WHERE c.commission_id = $1
        """,
        commission_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Commission not found")

    comm_dict = dict(row)
    html_content = render_commission_settlement(comm_dict, meta=comm_dict)
    full_html = get_base_html_wrapper(
        title=f"سند صرف عمولة - {commission_id}",
        content=html_content,
        doc_ref=comm_dict.get("commission_id", commission_id),
        doc_date=str((comm_dict.get("paid_at") or comm_dict.get("approved_at") or date.today()))[:10]
    )
    return HTMLResponse(content=full_html)

@router.post("/commissions/{commission_id}/payout", response_model=ResponseEnvelope[CommissionOut])
async def payout_commission(commission_id: str, conn: asyncpg.Connection = Depends(get_db)):
    await conn.execute("UPDATE commissions SET status = 'PAID', paid_at = now() WHERE commission_id = $1", commission_id)
    con_ref = await conn.fetchval("SELECT contract_id FROM commissions WHERE commission_id = $1", commission_id)
    task_id = None
    if con_ref:
        task_row = await conn.fetchrow(
            """
            SELECT task_id FROM tasks
            WHERE template_id = 'TASK_COMMISSION_SETTLEMENT'
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
            ORDER BY task_id DESC LIMIT 1
            """,
            con_ref
        )
        if task_row:
            task_id = task_row["task_id"]

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
            c.compensation_type,
            CAST(c.gross_deal_value AS FLOAT) AS gross_deal_value,
            CAST(c.gross_brokerage_amount AS FLOAT) AS gross_brokerage_amount,
            CAST(c.gov_fees_deducted AS FLOAT) AS gov_fees_deducted,
            CAST(c.net_commission_base AS FLOAT) AS net_commission_base,
            c.calculation_notes,
            COALESCE(con.contract_number, ten.contract_number, c.contract_id) AS contract_number,
            COALESCE(con.status, ten.status) AS contract_status,
            COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
            COALESCE(un.unit_number, un2.unit_number) AS unit_number,
            COALESCE(con.opportunity_id, r.opportunity_id) AS opp_id,
            COALESCE(con.lead_id, cust.customer_id) AS lead_or_cust_id,
            COALESCE(r.customer_id, ten.tenant_customer_id) AS cust_id,
            COALESCE(con.contract_id, ten.unit_id) AS u_id
        FROM commissions c
        LEFT JOIN users u ON c.user_id = u.user_id
        LEFT JOIN contracts con ON (c.contract_id = con.contract_id OR c.contract_id = con.contract_number)
        LEFT JOIN reservations r ON con.reservation_id = r.reservation_id
        LEFT JOIN tenancies ten ON (con.contract_number = ten.contract_number OR c.contract_id = ten.tenancy_id OR c.contract_id = ten.contract_number)
        LEFT JOIN customers cust ON COALESCE(r.customer_id, ten.tenant_customer_id) = cust.customer_id
        LEFT JOIN units un ON COALESCE(con.contract_id, ten.unit_id) = un.unit_id
        LEFT JOIN units un2 ON c.contract_id = un2.unit_id
        WHERE c.commission_id = $1
        """,
        commission_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Commission not found")

    comm_dict = dict(row)
    # Archive official Commission Settlement Document
    await WorkflowEngine.archive_workflow_document(
        conn=conn,
        doc_type_code="COMMISSION_SETTLEMENT",
        file_name=f"سند_صرف_عمولة_وسيط_{commission_id}.pdf",
        lead_id=comm_dict.get("lead_or_cust_id") if str(comm_dict.get("lead_or_cust_id", "")).startswith("lead-") else None,
        opportunity_id=comm_dict.get("opp_id"),
        task_id=task_id,
        customer_id=comm_dict.get("cust_id"),
        unit_id=comm_dict.get("u_id"),
        contract_id=con_ref,
        notes=f"سند اعتماد وصرف عمولة الوسيط المرخص فال بقيمة {float(comm_dict['amount']):,.2f} ريال سعودي.",
        metadata={
            "commission_id": commission_id,
            "contract_id": con_ref,
            "contract_number": comm_dict.get("contract_number"),
            "unit_number": comm_dict.get("unit_number"),
            "user_name": comm_dict.get("user_name"),
            "broker_name": comm_dict.get("user_name"),
            "user_id": comm_dict.get("user_id"),
            "commission_amount": float(comm_dict["amount"]),
            "gross_deal_value": float(comm_dict.get("gross_deal_value") or 0.0),
            "gross_brokerage_amount": float(comm_dict.get("gross_brokerage_amount") or 0.0),
            "gov_fees_deducted": float(comm_dict.get("gov_fees_deducted") or 0.0),
            "net_commission_base": float(comm_dict.get("net_commission_base") or 0.0),
            "rate": float(comm_dict.get("rate") or 0.0),
            "compensation_type": comm_dict.get("compensation_type"),
            "fal_license_number": "1200018890",
            "iban": "SA0380000000608010167519",
            "status": "PAID",
            "paid_at": datetime.now(timezone.utc).isoformat(),
            "calculation_notes": comm_dict.get("calculation_notes")
        }
    )

    return ResponseEnvelope(data=CommissionOut(**comm_dict), meta=BaseMeta())


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
    row_dict["payer_name"] = row_dict.get("payer_customer_name")
    row_dict["payer_mobile"] = row_dict.get("payer_customer_mobile")
    return row_dict

@router.get("/invoices", response_model=CollectionEnvelope[InvoiceOut])
async def list_invoices(
    payer_type: Optional[str] = None,
    status: Optional[str] = None,
    opportunity_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    unit_id: Optional[str] = None,
    contract_id: Optional[str] = None,
    tenancy_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    page_size: Optional[int] = None,
    offset: int = 0,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    effective_limit = page_size if page_size is not None else limit
    conditions = ["(inv.lead_id IS NOT NULL OR inv.opportunity_id IS NOT NULL)"]
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
        conditions.append(f"""(
            inv.opportunity_id = ${p_idx} OR
            inv.unit_id IN (SELECT unit_id FROM opportunity_units WHERE opportunity_id = ${p_idx})
        )""")
        params.append(opportunity_id)
        p_idx += 1

    if lead_id:
        conditions.append(f"""(
            inv.lead_id = ${p_idx} OR
            inv.unit_id IN (SELECT unit_id FROM lead_units WHERE lead_id = ${p_idx} UNION SELECT unit_id FROM leads WHERE lead_id = ${p_idx} AND unit_id IS NOT NULL)
        )""")
        params.append(lead_id)
        p_idx += 1

    if unit_id:
        conditions.append(f"inv.unit_id = ${p_idx}")
        params.append(unit_id)
        p_idx += 1

    if contract_id:
        conditions.append(f"inv.contract_id = ${p_idx}")
        params.append(contract_id)
        p_idx += 1

    if tenancy_id:
        conditions.append(f"""(
            inv.contract_id = ${p_idx} OR
            inv.contract_id IN (SELECT contract_number FROM tenancies WHERE tenancy_id = ${p_idx}) OR
            inv.unit_id IN (SELECT unit_id FROM tenancies WHERE tenancy_id = ${p_idx})
        )""")
        params.append(tenancy_id)
        p_idx += 1

    if search and search.strip():
        s_term = f"%{search.strip()}%"
        conditions.append(f"""(
            inv.invoice_number ILIKE ${p_idx} OR
            inv.invoice_id ILIKE ${p_idx} OR
            cust.first_name ILIKE ${p_idx} OR
            cust.last_name ILIKE ${p_idx} OR
            cust.company_name ILIKE ${p_idx} OR
            cust.mobile ILIKE ${p_idx} OR
            u.unit_number ILIKE ${p_idx} OR
            inv.unit_id ILIKE ${p_idx} OR
            inv.opportunity_id ILIKE ${p_idx} OR
            inv.lead_id ILIKE ${p_idx} OR
            inv.contract_id ILIKE ${p_idx} OR
            inv.notes ILIKE ${p_idx}
        )""")
        params.append(s_term)
        p_idx += 1

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count_query = f"SELECT count(*) FROM invoices inv LEFT JOIN customers cust ON inv.payer_customer_id = cust.customer_id LEFT JOIN units u ON inv.unit_id = u.unit_id {where_clause}"
    total = await conn.fetchval(count_query, *params)

    query = f"{INVOICE_SELECT_QUERY} {where_clause} ORDER BY CAST(substring(inv.invoice_id from '[0-9]+') AS INTEGER) DESC, inv.created_at DESC LIMIT ${p_idx} OFFSET ${p_idx + 1}"
    rows = await conn.fetch(query, *params, effective_limit, offset)

    items = [InvoiceOut(**parse_invoice_line_items(dict(r))) for r in rows]
    return CollectionEnvelope(
        data=items,
        meta=CollectionMeta(total=total, limit=effective_limit, offset=offset)
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

@router.get("/invoices/{invoice_id}/html", response_class=HTMLResponse)
async def get_invoice_html(
    invoice_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    await verify_finance_access(conn, x_user_id)
    row = await conn.fetchrow(f"{INVOICE_SELECT_QUERY} WHERE inv.invoice_id = $1", invoice_id)
    if not row:
        raise HTTPException(status_code=404, detail="Invoice not found")

    inv_dict = parse_invoice_line_items(dict(row))
    html_content = render_invoice_document(inv_dict, meta=inv_dict)
    full_html = get_base_html_wrapper(
        title=f"فاتورة ضريبية - {inv_dict.get('invoice_number', invoice_id)}",
        content=html_content,
        doc_ref=inv_dict.get("invoice_number", invoice_id),
        doc_date=str(inv_dict.get("due_date") or date.today())
    )
    return HTMLResponse(content=full_html)

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

@router.patch("/finance/reference/{entity_type}/{entity_id}", response_model=ResponseEnvelope[dict])
async def update_reference_number(
    entity_type: str,
    entity_id: str,
    payload: EditReferenceIn,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    Allows editing reference numbers, secondary references, payment methods, and notes
    across pending and executed transactions (payments, invoices, contracts, commissions, reservations).
    """
    await verify_finance_access(conn, x_user_id)
    entity_type = entity_type.lower().strip()
    updated_fields = {}

    if entity_type == "payment":
        sets = []
        params = []
        p_idx = 1
        if payload.reference_number is not None:
            sets.append(f"payment_reference = ${p_idx}")
            params.append(payload.reference_number.strip())
            updated_fields["payment_reference"] = payload.reference_number.strip()
            p_idx += 1
        if payload.payment_method is not None:
            sets.append(f"method = ${p_idx}")
            params.append(payload.payment_method.strip())
            updated_fields["method"] = payload.payment_method.strip()
            p_idx += 1
        if sets:
            params.append(entity_id)
            await conn.execute(f"UPDATE payments SET {', '.join(sets)} WHERE payment_id = ${p_idx}", *params)

    elif entity_type == "invoice":
        sets = ["updated_at = NOW()"]
        params = []
        p_idx = 1
        if payload.reference_number is not None:
            sets.append(f"invoice_number = ${p_idx}")
            params.append(payload.reference_number.strip())
            updated_fields["invoice_number"] = payload.reference_number.strip()
            p_idx += 1
        if payload.secondary_reference is not None:
            sets.append(f"payment_reference = ${p_idx}")
            params.append(payload.secondary_reference.strip())
            updated_fields["payment_reference"] = payload.secondary_reference.strip()
            p_idx += 1
        if payload.payment_method is not None:
            sets.append(f"payment_method = ${p_idx}")
            params.append(payload.payment_method.strip())
            updated_fields["payment_method"] = payload.payment_method.strip()
            p_idx += 1
        if payload.notes is not None:
            sets.append(f"notes = ${p_idx}")
            params.append(payload.notes.strip())
            updated_fields["notes"] = payload.notes.strip()
            p_idx += 1
        params.append(entity_id)
        await conn.execute(f"UPDATE invoices SET {', '.join(sets)} WHERE invoice_id = ${p_idx}", *params)

    elif entity_type == "contract":
        sets = []
        params = []
        p_idx = 1
        if payload.reference_number is not None:
            sets.append(f"contract_number = ${p_idx}")
            params.append(payload.reference_number.strip())
            updated_fields["contract_number"] = payload.reference_number.strip()
            p_idx += 1
        if sets:
            params.append(entity_id)
            await conn.execute(f"UPDATE contracts SET {', '.join(sets)} WHERE contract_id = ${p_idx}", *params)

    elif entity_type == "commission":
        sets = []
        params = []
        p_idx = 1
        if payload.notes is not None:
            sets.append(f"calculation_notes = ${p_idx}")
            params.append(payload.notes.strip())
            updated_fields["calculation_notes"] = payload.notes.strip()
            p_idx += 1
        if sets:
            params.append(entity_id)
            await conn.execute(f"UPDATE commissions SET {', '.join(sets)} WHERE commission_id = ${p_idx}", *params)

    elif entity_type == "reservation":
        sets = []
        params = []
        p_idx = 1
        if payload.reference_number is not None:
            sets.append(f"reservation_number = ${p_idx}")
            params.append(payload.reference_number.strip())
            updated_fields["reservation_number"] = payload.reference_number.strip()
            p_idx += 1
        if payload.secondary_reference is not None:
            sets.append(f"payment_ref = ${p_idx}")
            params.append(payload.secondary_reference.strip())
            updated_fields["payment_ref"] = payload.secondary_reference.strip()
            p_idx += 1
        if payload.notes is not None:
            sets.append(f"receipt_number = ${p_idx}")
            params.append(payload.notes.strip())
            updated_fields["receipt_number"] = payload.notes.strip()
            p_idx += 1
        if payload.payment_method is not None:
            sets.append(f"payment_method = ${p_idx}")
            params.append(payload.payment_method.strip())
            updated_fields["payment_method"] = payload.payment_method.strip()
            p_idx += 1
        if sets:
            params.append(entity_id)
            await conn.execute(f"UPDATE reservations SET {', '.join(sets)} WHERE reservation_id = ${p_idx}", *params)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported entity type '{entity_type}'")

    return ResponseEnvelope(
        data={"entity_type": entity_type, "entity_id": entity_id, "updated": updated_fields},
        meta=BaseMeta()
    )



