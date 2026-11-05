from typing import Optional, List
from uuid import uuid4
from datetime import datetime, timezone
import json
import re
import logging
from fastapi import APIRouter, Depends, Query, HTTPException, status, Header
import asyncpg
from app.database import get_db, get_next_id
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope
from app.routers.auth import check_user_scope_override, resolve_user_data_scope, resolve_data_scope_filter
from app.schemas.communications import (
    TasksSummaryOut,
    TaskOut, TaskCreateIn, TaskUpdateIn, TaskCompleteIn, TaskReopenIn, TaskCancelIn,
    ActivityOut, ActivityCreateIn,
    CommunicationOut, CommunicationCreateIn,
    InternalPingCreateIn, InternalPingOut, InternalPingsInboxOut, InternalPingsSummary, CleanupExpiredPingsOut
)
from app.services.workflow_engine import WorkflowEngine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Tasks & Communications"])

# ---------------------------------------------------------
# Summary / KPIs
# ---------------------------------------------------------
@router.get("/tasks/summary", response_model=ResponseEnvelope[TasksSummaryOut])
async def get_tasks_summary(
    assigned_user_id: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    scope_info = await resolve_data_scope_filter(conn, x_user_id, assigned_user_id)
    ag_cond = ""
    ag_params = []
    if scope_info["scope_type"] == "OWN":
        ag_cond = " AND assigned_user_id = $1"
        ag_params = [scope_info["user_id"]]
    elif scope_info["scope_type"] == "BRANCH":
        ag_cond = " AND (assigned_user_id IN (SELECT user_id FROM users WHERE branch_id = $1) OR assigned_user_id = $2)"
        ag_params = [scope_info["branch_id"], scope_info.get("user_id") or ""]

    open_tasks = await conn.fetchval(f"SELECT count(*) FROM tasks WHERE status IN ('OPEN', 'PENDING', 'IN_PROGRESS'){ag_cond}", *ag_params) or 0
    overdue_tasks = await conn.fetchval(f"SELECT count(*) FROM tasks WHERE status IN ('OPEN', 'PENDING', 'IN_PROGRESS') AND due_at < NOW(){ag_cond}", *ag_params) or 0
    completed_tasks = await conn.fetchval(f"SELECT count(*) FROM tasks WHERE status = 'COMPLETED'{ag_cond}", *ag_params) or 0
    
    act_cond = ""
    act_params = []
    if scope_info["scope_type"] == "OWN":
        act_cond = " WHERE (user_id = $1 OR lead_id IN (SELECT lead_id FROM leads WHERE assigned_user_id = $1))"
        act_params = [scope_info["user_id"]]
    elif scope_info["scope_type"] == "BRANCH":
        act_cond = " WHERE (user_id IN (SELECT user_id FROM users WHERE branch_id = $1) OR user_id = $2 OR lead_id IN (SELECT lead_id FROM leads WHERE branch_id = $1 OR assigned_user_id IN (SELECT user_id FROM users WHERE branch_id = $1)))"
        act_params = [scope_info["branch_id"], scope_info.get("user_id") or ""]
    total_acts = await conn.fetchval(f"SELECT count(*) FROM activities{act_cond}", *act_params) or 0
    
    v_act_cond = " WHERE at.code = 'VIEWING'"
    v_act_params = []
    if scope_info["scope_type"] == "OWN":
        v_act_cond += " AND (a.user_id = $1 OR a.lead_id IN (SELECT lead_id FROM leads WHERE assigned_user_id = $1))"
        v_act_params = [scope_info["user_id"]]
    elif scope_info["scope_type"] == "BRANCH":
        v_act_cond += " AND (a.user_id IN (SELECT user_id FROM users WHERE branch_id = $1) OR a.user_id = $2 OR a.lead_id IN (SELECT lead_id FROM leads WHERE branch_id = $1 OR assigned_user_id IN (SELECT user_id FROM users WHERE branch_id = $1)))"
        v_act_params = [scope_info["branch_id"], scope_info.get("user_id") or ""]
    v_acts = await conn.fetchval(f"""
        SELECT count(*) FROM activities a
        JOIN activity_types at ON a.activity_type_id = at.activity_type_id
        {v_act_cond}
    """, *v_act_params) or 0
    
    v_tbl_cond = ""
    v_tbl_params = []
    if scope_info["scope_type"] == "OWN":
        v_tbl_cond = " WHERE agent_user_id = $1"
        v_tbl_params = [scope_info["user_id"]]
    elif scope_info["scope_type"] == "BRANCH":
        v_tbl_cond = " WHERE (agent_user_id IN (SELECT user_id FROM users WHERE branch_id = $1) OR agent_user_id = $2)"
        v_tbl_params = [scope_info["branch_id"], scope_info.get("user_id") or ""]
    v_tbl = await conn.fetchval(f"SELECT count(*) FROM viewings{v_tbl_cond}", *v_tbl_params) or 0
    total_viewings = v_acts + v_tbl

    comm_cond = ""
    comm_params = []
    if scope_info["scope_type"] == "OWN":
        comm_cond = " WHERE lead_id IN (SELECT lead_id FROM leads WHERE assigned_user_id = $1)"
        comm_params = [scope_info["user_id"]]
    elif scope_info["scope_type"] == "BRANCH":
        comm_cond = " WHERE lead_id IN (SELECT lead_id FROM leads WHERE branch_id = $1 OR assigned_user_id IN (SELECT user_id FROM users WHERE branch_id = $1))"
        comm_params = [scope_info["branch_id"]]
    total_comms = await conn.fetchval(f"SELECT count(*) FROM communications{comm_cond}", *comm_params) or 0

    return ResponseEnvelope(data=TasksSummaryOut(
        open_tasks=open_tasks,
        overdue_tasks=overdue_tasks,
        completed_tasks=completed_tasks,
        total_activities=total_acts,
        total_communications=total_comms,
        total_viewings=total_viewings
    ))


# ---------------------------------------------------------
# Tasks
# ---------------------------------------------------------
@router.get("/tasks", response_model=CollectionEnvelope[TaskOut])
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    status_filter: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    assigned_user_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    opportunity_id: Optional[str] = None,
    template_id: Optional[str] = None,
    is_overdue: Optional[bool] = None,
    search: Optional[str] = None,
    sort_by: Optional[str] = Query("created_desc"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    scope_info = await resolve_data_scope_filter(conn, x_user_id, assigned_user_id)
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        s_upper = status_filter.upper()
        if s_upper in ("OPEN", "ACTIVE"):
            conditions.append("t.status IN ('OPEN', 'PENDING', 'IN_PROGRESS')")
        else:
            conditions.append(f"t.status = ${p_idx}")
            params.append(s_upper)
            p_idx += 1

    if priority:
        conditions.append(f"t.priority = ${p_idx}")
        params.append(priority.upper())
        p_idx += 1

    if scope_info["scope_type"] == "OWN":
        conditions.append(f"t.assigned_user_id = ${p_idx}")
        params.append(scope_info["user_id"])
        p_idx += 1
    elif scope_info["scope_type"] == "BRANCH":
        conditions.append(
            f"(t.assigned_user_id IN (SELECT user_id FROM users WHERE branch_id = ${p_idx}) OR t.assigned_user_id = ${p_idx + 1})"
        )
        params.append(scope_info["branch_id"])
        params.append(scope_info.get("user_id") or "")
        p_idx += 2

    if customer_id:
        conditions.append(f"t.customer_id = ${p_idx}")
        params.append(customer_id)
        p_idx += 1

    if lead_id:
        conditions.append(f"t.lead_id = ${p_idx}")
        params.append(lead_id)
        p_idx += 1

    if opportunity_id:
        conditions.append(f"t.opportunity_id = ${p_idx}")
        params.append(opportunity_id)
        p_idx += 1

    if template_id:
        conditions.append(f"t.template_id = ${p_idx}")
        params.append(template_id)
        p_idx += 1

    if is_overdue:
        conditions.append("t.status IN ('OPEN', 'PENDING', 'IN_PROGRESS') AND t.due_at < NOW()")

    if search:
        s = f"%{search.strip()}%"
        conditions.append(
            f"(t.title ILIKE ${p_idx} OR t.task_id ILIKE ${p_idx} OR t.lead_id ILIKE ${p_idx} OR t.opportunity_id ILIKE ${p_idx} OR t.template_id ILIKE ${p_idx} OR c.first_name ILIKE ${p_idx} OR c.last_name ILIKE ${p_idx} OR c.company_name ILIKE ${p_idx} OR u.full_name ILIKE ${p_idx})"
        )
        params.append(s)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"""
        SELECT count(*) 
        FROM tasks t
        LEFT JOIN users u ON t.assigned_user_id = u.user_id
        LEFT JOIN customers c ON t.customer_id = c.customer_id
        WHERE {where_clause}
        """,
        *params
    )

    order_clause = "t.created_at DESC NULLS LAST, t.task_id DESC"
    if sort_by == "due_asc":
        order_clause = "t.due_at ASC NULLS LAST, t.created_at DESC"
    elif sort_by == "priority":
        order_clause = """
            CASE t.status WHEN 'OPEN' THEN 1 WHEN 'PENDING' THEN 1 WHEN 'IN_PROGRESS' THEN 1 ELSE 2 END,
            CASE t.priority WHEN 'URGENT' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'NORMAL' THEN 3 ELSE 4 END,
            t.due_at ASC NULLS LAST
        """
    elif sort_by == "created_asc":
        order_clause = "t.created_at ASC NULLS LAST, t.task_id ASC"

    query = f"""
        SELECT 
            t.task_id,
            t.template_id,
            t.title,
            t.due_at,
            t.created_at,
            t.completed_at,
            t.priority,
            t.status,
            COALESCE(t.escalation_level, 0) AS escalation_level,
            t.assigned_user_id,
            u.full_name AS assigned_user_name,
            t.customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            t.lead_id,
            t.opportunity_id,
            COALESCE(l.inquiry_type, lo.inquiry_type) AS inquiry_type,
            COALESCE(l.preferred_property_type_id, lo.preferred_property_type_id) AS preferred_property_type_id,
            pt.name_en AS preferred_property_type_name,
            pt.name_ar AS preferred_property_type_name_ar,
            t.parent_task_id,
            COALESCE(l.budget_max, lo.budget_max) AS lead_budget_max,
            o.expected_value AS opp_expected_value,
            o.stage AS opp_stage,
            CASE WHEN t.status IN ('OPEN', 'PENDING', 'IN_PROGRESS') AND t.due_at < NOW() THEN true ELSE false END AS is_overdue
        FROM tasks t
        LEFT JOIN users u ON t.assigned_user_id = u.user_id
        LEFT JOIN customers c ON t.customer_id = c.customer_id
        LEFT JOIN leads l ON t.lead_id = l.lead_id
        LEFT JOIN opportunities o ON t.opportunity_id = o.opportunity_id
        LEFT JOIN leads lo ON o.lead_id = lo.lead_id
        LEFT JOIN property_types pt ON COALESCE(l.preferred_property_type_id, lo.preferred_property_type_id) = pt.property_type_id
        WHERE {where_clause}
        ORDER BY {order_clause}
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [TaskOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/tasks", response_model=ResponseEnvelope[TaskOut], status_code=status.HTTP_201_CREATED)
async def create_task(payload: TaskCreateIn, conn: asyncpg.Connection = Depends(get_db)):
    task_id = await get_next_id(conn, "tasks", "task")
    pri = (payload.priority or "NORMAL").upper()
    st = (payload.status or "OPEN").upper()

    eff_lead = payload.lead_id
    eff_opp = payload.opportunity_id

    # Bidirectional synchronization between Lead and Opportunity
    if eff_lead and not eff_opp:
        eff_opp = await conn.fetchval(
            "SELECT opportunity_id FROM opportunities WHERE lead_id = $1 ORDER BY created_at DESC LIMIT 1",
            eff_lead
        )
    elif eff_opp and not eff_lead:
        eff_lead = await conn.fetchval(
            "SELECT lead_id FROM opportunities WHERE opportunity_id = $1",
            eff_opp
        )

    # Always inherit priority strictly from the associated lead
    if eff_lead:
        lead_pri = await conn.fetchval("SELECT priority FROM leads WHERE lead_id = $1", eff_lead)
        if lead_pri:
            pri = lead_pri.upper()

    # Also resolve customer_id if missing
    eff_cust = payload.customer_id
    if not eff_cust and eff_lead:
        eff_cust = await conn.fetchval("SELECT customer_id FROM leads WHERE lead_id = $1", eff_lead)
    elif not eff_cust and eff_opp:
        eff_cust = await conn.fetchval("SELECT customer_id FROM opportunities WHERE opportunity_id = $1", eff_opp)

    user_name = None
    if payload.assigned_user_id:
        usr = await conn.fetchrow("SELECT full_name FROM users WHERE user_id = $1", payload.assigned_user_id)
        if usr:
            user_name = usr["full_name"]

    cust_name = None
    if eff_cust:
        c = await conn.fetchrow("SELECT first_name, last_name, company_name FROM customers WHERE customer_id = $1", eff_cust)
        if c:
            cust_name = (f"{c['first_name'] or ''} {c['last_name'] or ''}").strip() or c["company_name"]

    await conn.execute(
        """
        INSERT INTO tasks (
            task_id, assigned_user_id, customer_id, lead_id, opportunity_id,
            title, due_at, priority, status, template_id, parent_task_id
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
        task_id, payload.assigned_user_id, eff_cust,
        eff_lead, eff_opp, payload.title,
        payload.due_at, pri, st, payload.template_id, payload.parent_task_id
    )

    is_od = False
    if payload.due_at and payload.due_at < datetime.now(timezone.utc) and st == "OPEN":
        is_od = True

    out = TaskOut(
        task_id=task_id,
        template_id=payload.template_id,
        title=payload.title,
        due_at=payload.due_at,
        priority=pri,
        status=st,
        assigned_user_id=payload.assigned_user_id,
        assigned_user_name=user_name,
        customer_id=eff_cust,
        customer_name=cust_name,
        lead_id=eff_lead,
        opportunity_id=eff_opp,
        parent_task_id=payload.parent_task_id,
        is_overdue=is_od
    )
    return ResponseEnvelope(data=out)

@router.get("/tasks/{task_id}", response_model=ResponseEnvelope[TaskOut])
async def get_task(
    task_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    row = await conn.fetchrow(
        """
        SELECT 
            t.task_id,
            t.template_id,
            t.title,
            t.due_at,
            t.created_at,
            t.completed_at,
            t.priority,
            t.status,
            COALESCE(t.escalation_level, 0) AS escalation_level,
            t.assigned_user_id,
            u.full_name AS assigned_user_name,
            t.customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            t.lead_id,
            t.opportunity_id,
            COALESCE(l.inquiry_type, lo.inquiry_type) AS inquiry_type,
            COALESCE(l.preferred_property_type_id, lo.preferred_property_type_id) AS preferred_property_type_id,
            pt.name_en AS preferred_property_type_name,
            pt.name_ar AS preferred_property_type_name_ar,
            t.parent_task_id,
            COALESCE(l.budget_max, lo.budget_max) AS lead_budget_max,
            o.expected_value AS opp_expected_value,
            o.stage AS opp_stage,
            CASE WHEN t.status IN ('OPEN', 'PENDING', 'IN_PROGRESS') AND t.due_at < NOW() THEN true ELSE false END AS is_overdue
        FROM tasks t
        LEFT JOIN users u ON t.assigned_user_id = u.user_id
        LEFT JOIN customers c ON t.customer_id = c.customer_id
        LEFT JOIN leads l ON t.lead_id = l.lead_id
        LEFT JOIN opportunities o ON t.opportunity_id = o.opportunity_id
        LEFT JOIN leads lo ON o.lead_id = lo.lead_id
        LEFT JOIN property_types pt ON COALESCE(l.preferred_property_type_id, lo.preferred_property_type_id) = pt.property_type_id
        WHERE t.task_id = $1
        """,
        task_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    if x_user_id:
        roles = await conn.fetch(
            "SELECT r.role_code FROM user_roles ur JOIN roles r ON ur.role_id = r.role_id WHERE ur.user_id = $1",
            x_user_id
        )
        scope = resolve_user_data_scope([r["role_code"] for r in roles])
        if scope == "OWN" and row["assigned_user_id"] != x_user_id:
            raise HTTPException(status_code=403, detail="Access denied: Task belongs to another agent")
    return ResponseEnvelope(data=TaskOut(**dict(row)))

@router.get("/tasks/{task_id}/completion-details", response_model=ResponseEnvelope[dict])
async def get_task_completion_details(
    task_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    Returns rich, comprehensive completion details, inputs, decisions, 
    linked activities, documents, and business objects for an executed task.
    """
    row = await conn.fetchrow(
        """
        SELECT 
            t.task_id,
            t.template_id,
            t.title,
            t.due_at,
            t.created_at,
            t.completed_at,
            t.priority,
            t.status,
            t.assigned_user_id,
            u.full_name AS assigned_user_name,
            t.customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            c.mobile AS customer_mobile,
            t.lead_id,
            t.opportunity_id,
            t.parent_task_id
        FROM tasks t
        LEFT JOIN users u ON t.assigned_user_id = u.user_id
        LEFT JOIN customers c ON t.customer_id = c.customer_id
        WHERE t.task_id = $1
        """,
        task_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    task_data = dict(row)

    # 1. Fetch linked Activity
    activity_row = await conn.fetchrow(
        """
        SELECT a.*, u.full_name AS agent_name
        FROM activities a
        LEFT JOIN users u ON a.user_id = u.user_id
        WHERE a.task_id = $1
        ORDER BY a.created_at DESC
        LIMIT 1
        """,
        task_id
    )
    activity_data = dict(activity_row) if activity_row else None

    # 2. Fetch linked Documents
    doc_rows = await conn.fetch(
        """
        SELECT d.document_id, d.file_name, d.notes, d.metadata, d.issued_at, d.created_at, dt.code AS document_type_code, dt.name AS document_type_name
        FROM documents d
        LEFT JOIN document_types dt ON d.document_type_id = dt.document_type_id
        WHERE d.task_id = $1
        ORDER BY d.created_at DESC
        """,
        task_id
    )
    if not doc_rows and (task_data.get("opportunity_id") or task_data.get("lead_id")):
        doc_rows = await conn.fetch(
            """
            SELECT d.document_id, d.file_name, d.notes, d.metadata, d.issued_at, d.created_at, dt.code AS document_type_code, dt.name AS document_type_name
            FROM documents d
            LEFT JOIN document_types dt ON d.document_type_id = dt.document_type_id
            WHERE (d.opportunity_id = $1 OR d.lead_id = $2)
            ORDER BY d.created_at DESC
            LIMIT 5
            """,
            task_data.get("opportunity_id"), task_data.get("lead_id")
        )

    documents = []
    for d in doc_rows:
        dd = dict(d)
        if isinstance(dd.get("metadata"), str):
            try:
                dd["metadata"] = json.loads(dd["metadata"])
            except Exception:
                pass
        documents.append(dd)

    # 3. Check for linked Contract / Tenancy
    tenancy = None
    contract = None
    installments = []

    c_num_match = re.search(r'(TEN-\d{4,6}-\d+|CON-\d{4,6})', (task_data.get("title") or "") + " " + ((activity_data or {}).get("description") or ""))
    c_num = c_num_match.group(1) if c_num_match else None

    if not c_num and documents:
        for d in documents:
            if isinstance(d.get("metadata"), dict) and d["metadata"].get("contract_number"):
                c_num = d["metadata"]["contract_number"]
                break

    if c_num:
        tenancy_row = await conn.fetchrow(
            """
            SELECT t.*, u.unit_number 
            FROM tenancies t 
            JOIN units u ON t.unit_id = u.unit_id 
            WHERE t.contract_number = $1 OR t.ejar_contract_number = $1 
            LIMIT 1
            """,
            c_num
        )
        if tenancy_row:
            tenancy = dict(tenancy_row)

        contract_row = await conn.fetchrow(
            """
            SELECT c.*, u.unit_number 
            FROM contracts c 
            LEFT JOIN units u ON c.contract_id = u.unit_id 
            WHERE c.contract_number = $1 
            LIMIT 1
            """,
            c_num
        )
        if contract_row:
            contract = dict(contract_row)

    if not tenancy and task_data.get("customer_id") and "RENT" in (task_data.get("template_id") or ""):
        tenancy_row = await conn.fetchrow(
            """
            SELECT t.*, u.unit_number 
            FROM tenancies t 
            JOIN units u ON t.unit_id = u.unit_id 
            WHERE t.tenant_customer_id = $1 
            ORDER BY t.start_date DESC, t.tenancy_id DESC 
            LIMIT 1
            """,
            task_data["customer_id"]
        )
        if tenancy_row:
            tenancy = dict(tenancy_row)

    if tenancy:
        rcs = await conn.fetch(
            """
            SELECT rent_collection_id, due_date, amount_due, amount_paid, paid_at, status 
            FROM rent_collections 
            WHERE tenancy_id = $1 
            ORDER BY due_date ASC
            """,
            tenancy["tenancy_id"]
        )
        installments = [dict(r) for r in rcs]

    # 4. Check for linked Viewing
    viewing = None
    if "VIEWING" in (task_data.get("template_id") or ""):
        v_row = await conn.fetchrow(
            """
            SELECT v.*, u.unit_number, COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name
            FROM viewings v
            LEFT JOIN units u ON v.unit_id = u.unit_id
            LEFT JOIN customers c ON v.customer_id = c.customer_id
            WHERE (v.opportunity_id = $1 OR v.lead_id = $2)
            ORDER BY v.scheduled_at DESC, v.created_at DESC
            LIMIT 1
            """,
            task_data.get("opportunity_id"), task_data.get("lead_id")
        )
        if v_row:
            viewing = dict(v_row)

    # 5. Check for linked Offer
    offer = None
    if "OFFER" in (task_data.get("template_id") or "") or "NEGOTIAT" in (task_data.get("template_id") or ""):
        o_row = await conn.fetchrow(
            """
            SELECT o.*, u.unit_number
            FROM offers o
            LEFT JOIN units u ON o.unit_id = u.unit_id
            WHERE o.opportunity_id = $1
            ORDER BY o.submitted_at DESC
            LIMIT 1
            """,
            task_data.get("opportunity_id")
        )
        if o_row:
            offer = dict(o_row)

    # 6. Check for linked Commission
    commission = None
    if "COMMISSION" in (task_data.get("template_id") or "") or "عمولة" in (task_data.get("title") or "") or "Commission" in (task_data.get("title") or ""):
        c_row = None
        if c_num:
            c_row = await conn.fetchrow(
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
                    COALESCE(un.unit_number, un2.unit_number) AS unit_number
                FROM commissions c
                LEFT JOIN users u ON c.user_id = u.user_id
                LEFT JOIN contracts con ON (c.contract_id = con.contract_id OR c.contract_id = con.contract_number)
                LEFT JOIN tenancies ten ON (con.contract_number = ten.contract_number OR c.contract_id = ten.tenancy_id OR c.contract_id = ten.contract_number)
                LEFT JOIN units un ON COALESCE(con.contract_id, ten.unit_id) = un.unit_id
                LEFT JOIN units un2 ON c.contract_id = un2.unit_id
                WHERE con.contract_number = $1 OR ten.contract_number = $1 OR c.contract_id = $1
                ORDER BY CAST(substring(c.commission_id from '[0-9]+') AS INTEGER) DESC
                LIMIT 1
                """,
                c_num
            )
        if not c_row and (task_data.get("opportunity_id") or task_data.get("lead_id")):
            c_row = await conn.fetchrow(
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
                    COALESCE(un.unit_number, un2.unit_number) AS unit_number
                FROM commissions c
                LEFT JOIN users u ON c.user_id = u.user_id
                LEFT JOIN contracts con ON (c.contract_id = con.contract_id OR c.contract_id = con.contract_number)
                LEFT JOIN reservations r ON con.reservation_id = r.reservation_id
                LEFT JOIN tenancies ten ON (con.contract_number = ten.contract_number OR c.contract_id = ten.tenancy_id OR c.contract_id = ten.contract_number)
                LEFT JOIN units un ON COALESCE(con.contract_id, ten.unit_id) = un.unit_id
                LEFT JOIN units un2 ON c.contract_id = un2.unit_id
                WHERE (r.opportunity_id = $1 OR con.opportunity_id = $1 OR con.lead_id = $2 OR (con.contract_number IN (SELECT contract_number FROM tenancies WHERE tenant_customer_id = $3)))
                ORDER BY CAST(substring(c.commission_id from '[0-9]+') AS INTEGER) DESC
                LIMIT 1
                """,
                task_data.get("opportunity_id"), task_data.get("lead_id"), task_data.get("customer_id")
            )
        if c_row:
            commission = dict(c_row)

    result = {
        "task": task_data,
        "activity": activity_data,
        "documents": documents,
        "tenancy": tenancy,
        "contract": contract,
        "installments": installments,
        "viewing": viewing,
        "offer": offer,
        "commission": commission
    }
    return ResponseEnvelope(data=result)

@router.patch("/tasks/{task_id}", response_model=ResponseEnvelope[dict])
async def update_task(task_id: str, payload: TaskUpdateIn, conn: asyncpg.Connection = Depends(get_db)):
    t = await conn.fetchrow("SELECT task_id, status FROM tasks WHERE task_id = $1", task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")

    sets = []
    params = []
    p_idx = 1

    if payload.title is not None:
        sets.append(f"title = ${p_idx}")
        params.append(payload.title)
        p_idx += 1

    if payload.due_at is not None:
        sets.append(f"due_at = ${p_idx}")
        params.append(payload.due_at)
        p_idx += 1

    if payload.priority is not None:
        sets.append(f"priority = ${p_idx}")
        params.append(payload.priority.upper())
        p_idx += 1

    if payload.status is not None:
        sets.append(f"status = ${p_idx}")
        params.append(payload.status.upper())
        p_idx += 1

    if payload.assigned_user_id is not None:
        sets.append(f"assigned_user_id = ${p_idx}")
        params.append(payload.assigned_user_id)
        p_idx += 1

    if sets:
        params.append(task_id)
        sql = f"UPDATE tasks SET {', '.join(sets)} WHERE task_id = ${p_idx}"
        await conn.execute(sql, *params)

    return ResponseEnvelope(data={"task_id": str(task_id), "updated": True})

@router.post("/tasks/{task_id}/complete", response_model=ResponseEnvelope[dict])
async def complete_task(
    task_id: str,
    payload: Optional[TaskCompleteIn] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    outcome = payload.outcome if (payload and payload.outcome) else "CONNECTED"
    notes = payload.notes if payload else None
    user_id = x_user_id or "user-51"

    q_data = None
    viewing_data = None
    if payload:
        q_data = {
            "budget_min": payload.budget_min,
            "budget_max": payload.budget_max,
            "preferred_property_type_id": payload.preferred_property_type_id,
            "preferred_city_id": payload.preferred_city_id
        }
        viewing_data = {
            "assigned_user_id": payload.assigned_user_id,
            "branch_id": payload.branch_id,
            "unit_id": payload.unit_id,
            "unit_ids": payload.unit_ids,
            "callback_at": payload.callback_at,
            "scheduled_start": payload.scheduled_start,
            "scheduled_end": payload.scheduled_end,
            "viewing_duration_minutes": payload.viewing_duration_minutes,
            "location_notes": payload.location_notes,
            "feedback_rating": payload.feedback_rating,
            "offer_amount": payload.offer_amount,
            "counter_amount": payload.counter_amount,
            "negotiated_price": payload.negotiated_price,
            "payment_terms": payload.payment_terms,
            "rent_amount": payload.rent_amount,
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "payment_frequency": payload.payment_frequency,
            "deposit_amount": payload.deposit_amount,
            "installments_count": payload.installments_count,
            "contract_number": payload.contract_number,
            "target_yield_percent": payload.target_yield_percent,
            "investment_horizon_years": payload.investment_horizon_years,
            "risk_tolerance": payload.risk_tolerance,
            "investment_strategy": payload.investment_strategy,
            "purchase_price": payload.purchase_price,
            "gross_annual_rent": payload.gross_annual_rent,
            "cash_invested": payload.cash_invested,
            "annual_pre_tax_cash_flow": payload.annual_pre_tax_cash_flow,
            "annual_operating_expenses": payload.annual_operating_expenses,
            "annual_vacancy_allowance": payload.annual_vacancy_allowance,
            "acquisition_costs": payload.acquisition_costs,
            "monthly_rent_forecast": payload.monthly_rent_forecast,
            "actual_rental_income": payload.actual_rental_income,
            "actual_expenses": payload.actual_expenses,
            # Investment Due Diligence Inspection fields
            "structural_condition": payload.structural_condition,
            "building_age_years": payload.building_age_years,
            "saudi_building_code_compliant": payload.saudi_building_code_compliant,
            "hvac_status": payload.hvac_status,
            "elevators_status": payload.elevators_status,
            "plumbing_network_status": payload.plumbing_network_status,
            "electrical_network_status": payload.electrical_network_status,
            "roofing_and_insulation_status": payload.roofing_and_insulation_status,
            "fire_safety_compliance": payload.fire_safety_compliance,
            "estimated_capex_sar": payload.estimated_capex_sar,
            "technical_notes": payload.technical_notes,
            "location_traffic_flow": payload.location_traffic_flow,
            "access_and_egress_quality": payload.access_and_egress_quality,
            "parking_availability": payload.parking_availability,
            "actual_occupancy_rate": payload.actual_occupancy_rate,
            "occupied_units_count": payload.occupied_units_count,
            "vacant_units_count": payload.vacant_units_count,
            "rent_roll_verified": payload.rent_roll_verified,
            "property_manager_interview_notes": payload.property_manager_interview_notes,
            "commercial_viability_score": payload.commercial_viability_score,
            "commercial_notes": payload.commercial_notes,
            "recommendation": payload.recommendation,
            "suggested_price_adjustment_sar": payload.suggested_price_adjustment_sar,
            "final_verdict_summary": payload.final_verdict_summary,
            "first_due_date": payload.first_due_date,
            "bank_name": payload.bank_name,
            "bank_iban": payload.bank_iban,
            "bank_beneficiary": payload.bank_beneficiary,
            "maintenance_terms": payload.maintenance_terms,
            "ejar_contract_number": payload.ejar_contract_number
        }
        if payload.viewing_data and isinstance(payload.viewing_data, dict):
            for k, v in payload.viewing_data.items():
                if v is not None:
                    viewing_data[k] = v

    async with conn.transaction():
        try:
            result = await WorkflowEngine.complete_task_with_outcome(
                conn=conn,
                task_id=task_id,
                user_id=user_id,
                outcome=outcome,
                notes=notes,
                qualification_data=q_data,
                viewing_data=viewing_data
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error completing task {task_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to complete task: {str(e)}")

    return ResponseEnvelope(data=result)


@router.post("/tasks/{task_id}/reopen", response_model=ResponseEnvelope[dict])
async def reopen_task_endpoint(
    task_id: str,
    payload: Optional[TaskReopenIn] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    Smart Reopen & Undo Endpoint:
    Reverts an erroneously completed task back to PENDING and safely rolls back
    unworked downstream jobs, stage advances, or scheduled viewings.
    """
    user_id = x_user_id or "user-51"
    reason = payload.reason if payload else None

    async with conn.transaction():
        try:
            result = await WorkflowEngine.reopen_task(
                conn=conn,
                task_id=task_id,
                user_id=user_id,
                reason=reason
            )
        except ValueError as e:
            msg = str(e)
            if "not found" in msg.lower() or "غير موجودة" in msg:
                raise HTTPException(status_code=404, detail=msg)
            raise HTTPException(status_code=400, detail=msg)

    return ResponseEnvelope(data=result)


@router.post("/tasks/{task_id}/cancel", response_model=ResponseEnvelope[dict])
async def cancel_task_endpoint(
    task_id: str,
    payload: Optional[TaskCancelIn] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    Cancel Task Endpoint:
    Cancels a task, logs ACT_TASK_CANCELLED, and optionally cascades to cancel the parent deal.
    """
    user_id = x_user_id or "user-51"
    reason = payload.reason if payload else "CANCELLED_BY_USER"
    notes = payload.notes if payload else None
    cascade = bool(payload and (payload.cascade_cancel_opportunity or payload.cancel_opportunity))

    async with conn.transaction():
        try:
            result = await WorkflowEngine.cancel_task(
                conn=conn,
                task_id=task_id,
                user_id=user_id,
                reason=reason,
                notes=notes,
                cancel_opportunity=cascade
            )
        except ValueError as e:
            msg = str(e)
            if "not found" in msg.lower() or "غير موجودة" in msg:
                raise HTTPException(status_code=404, detail=msg)
            raise HTTPException(status_code=400, detail=msg)
        except Exception as e:
            logger.error(f"Error cancelling task {task_id}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to cancel task: {str(e)}")

    return ResponseEnvelope(data=result)


# ---------------------------------------------------------
# Activities
# ---------------------------------------------------------
@router.get("/activities", response_model=CollectionEnvelope[ActivityOut])
async def list_activities(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    activity_type: Optional[str] = None,
    user_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = None,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    scope_info = await resolve_data_scope_filter(conn, x_user_id, user_id)
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if activity_type:
        conditions.append(f"at.code = ${p_idx}")
        params.append(activity_type.upper())
        p_idx += 1

    if scope_info["scope_type"] == "OWN":
        conditions.append(f"(a.user_id = ${p_idx} OR a.lead_id IN (SELECT lead_id FROM leads WHERE assigned_user_id = ${p_idx}))")
        params.append(scope_info["user_id"])
        p_idx += 1
    elif scope_info["scope_type"] == "BRANCH":
        conditions.append(
            f"(a.user_id IN (SELECT user_id FROM users WHERE branch_id = ${p_idx}) OR a.user_id = ${p_idx + 1} "
            f"OR a.lead_id IN (SELECT lead_id FROM leads WHERE branch_id = ${p_idx} OR assigned_user_id IN (SELECT user_id FROM users WHERE branch_id = ${p_idx})))"
        )
        params.append(scope_info["branch_id"])
        params.append(scope_info.get("user_id") or "")
        p_idx += 2

    if customer_id:
        conditions.append(f"a.customer_id = ${p_idx}")
        params.append(customer_id)
        p_idx += 1

    if lead_id:
        conditions.append(f"a.lead_id = ${p_idx}")
        params.append(lead_id)
        p_idx += 1

    if status_filter:
        conditions.append(f"a.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if search:
        s = f"%{search.strip()}%"
        conditions.append(f"(a.subject ILIKE ${p_idx} OR a.description ILIKE ${p_idx} OR a.lead_id ILIKE ${p_idx} OR a.opportunity_id ILIKE ${p_idx} OR a.template_id ILIKE ${p_idx} OR a.activity_id ILIKE ${p_idx})")
        params.append(s)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(
        f"""
        SELECT count(*) 
        FROM activities a
        LEFT JOIN activity_types at ON a.activity_type_id = at.activity_type_id
        WHERE {where_clause}
        """,
        *params
    )

    query = f"""
        SELECT 
            a.activity_id,
            a.template_id,
            a.subject,
            a.description,
            a.outcome,
            a.activity_type_id,
            at.code AS activity_type_code,
            at.name AS activity_type_name,
            a.user_id,
            u.full_name AS user_name,
            a.customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            a.lead_id,
            a.opportunity_id,
            COALESCE(l.inquiry_type, lo.inquiry_type) AS inquiry_type,
            COALESCE(l.preferred_property_type_id, lo.preferred_property_type_id) AS preferred_property_type_id,
            pt.name_en AS preferred_property_type_name,
            pt.name_ar AS preferred_property_type_name_ar,
            COALESCE(l.priority, lo.priority, 'NORMAL') AS priority,
            a.scheduled_at,
            a.completed_at,
            a.status
        FROM activities a
        LEFT JOIN activity_types at ON a.activity_type_id = at.activity_type_id
        LEFT JOIN users u ON a.user_id = u.user_id
        LEFT JOIN customers c ON a.customer_id = c.customer_id
        LEFT JOIN leads l ON a.lead_id = l.lead_id
        LEFT JOIN opportunities o ON a.opportunity_id = o.opportunity_id
        LEFT JOIN leads lo ON o.lead_id = lo.lead_id
        LEFT JOIN property_types pt ON COALESCE(l.preferred_property_type_id, lo.preferred_property_type_id) = pt.property_type_id
        WHERE {where_clause}
        ORDER BY COALESCE(a.completed_at, a.scheduled_at, a.created_at) DESC NULLS LAST
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [ActivityOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/activities", response_model=ResponseEnvelope[ActivityOut], status_code=status.HTTP_201_CREATED)
async def create_activity(payload: ActivityCreateIn, conn: asyncpg.Connection = Depends(get_db)):
    act_id = await get_next_id(conn, "activities", "activity")
    act_type_id = payload.activity_type_id
    code = (payload.activity_type_code or "CALL").upper()
    act_type_name = "Activity"

    if not act_type_id and code:
        at_row = await conn.fetchrow("SELECT activity_type_id, name FROM activity_types WHERE code = $1", code)
        if at_row:
            act_type_id = at_row["activity_type_id"]
            act_type_name = at_row["name"]

    user_name = None
    if payload.user_id:
        u = await conn.fetchrow("SELECT full_name FROM users WHERE user_id = $1", payload.user_id)
        if u:
            user_name = u["full_name"]

    cust_name = None
    if payload.customer_id:
        c = await conn.fetchrow("SELECT first_name, last_name, company_name FROM customers WHERE customer_id = $1", payload.customer_id)
        if c:
            cust_name = (f"{c['first_name'] or ''} {c['last_name'] or ''}").strip() or c["company_name"]

    now = datetime.now(timezone.utc)
    completed_at = payload.completed_at
    if payload.status == "COMPLETED" and not completed_at:
        completed_at = now

    await conn.execute(
        """
        INSERT INTO activities (
            activity_id, user_id, customer_id, lead_id, opportunity_id,
            activity_type_id, subject, description, scheduled_at, completed_at, status
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
        act_id, payload.user_id, payload.customer_id, payload.lead_id, payload.opportunity_id,
        act_type_id, payload.subject, payload.description, payload.scheduled_at, completed_at,
        payload.status or "COMPLETED"
    )

    out = ActivityOut(
        activity_id=act_id,
        subject=payload.subject,
        description=payload.description,
        activity_type_id=act_type_id,
        activity_type_code=code,
        activity_type_name=act_type_name,
        user_id=payload.user_id,
        user_name=user_name,
        customer_id=payload.customer_id,
        customer_name=cust_name,
        lead_id=payload.lead_id,
        opportunity_id=payload.opportunity_id,
        scheduled_at=payload.scheduled_at,
        completed_at=completed_at,
        status=payload.status or "COMPLETED"
    )
    return ResponseEnvelope(data=out)

@router.post("/activities/{activity_id}/complete", response_model=ResponseEnvelope[dict])
async def complete_activity(activity_id: str, conn: asyncpg.Connection = Depends(get_db)):
    act = await conn.fetchrow("SELECT activity_id FROM activities WHERE activity_id = $1", activity_id)
    if not act:
        raise HTTPException(status_code=404, detail="Activity not found")

    now = datetime.now(timezone.utc)
    await conn.execute("UPDATE activities SET status = 'COMPLETED', completed_at = $1 WHERE activity_id = $2", now, activity_id)
    return ResponseEnvelope(data={"activity_id": str(activity_id), "status": "COMPLETED", "completed_at": now.isoformat()})


# ---------------------------------------------------------
# Communications
# ---------------------------------------------------------
COMM_CAUSE_MAP = {
    "COMM_AUTO_ACK_WHATSAPP": "إشعار استلام الطلب وتوجيهه للوسيط / Lead Acknowledgment",
    "COMM_LEAD_ASSIGNED_WHATSAPP": "توجيه وإسناد الطلب للوسيط / Lead Assigned",
    "COMM_OPPORTUNITY_RECOMMENDATIONS": "ترشيح ومطابقة العقارات للعميل / Property Recommendations",
    "COMM_VIEWING_CONFIRMATION": "تأكيد موعد المعاينة الميدانية / Viewing Confirmation",
    "COMM_VIEWING_REMINDER": "تذكير بموعد المعاينة الميدانية / Viewing Reminder",
    "COMM_OFFER_PROPOSAL_SENT": "إرسال عرض السعر المالي المعتمد / Offer Proposal",
    "COMM_OFFER_DECISION_COMMUNICATED": "تأكيد قبول العرض وبدء الحجز / Offer Decision",
    "COMM_CONTRACT_REVIEW_REQUIRED": "مراجعة واعتماد مسودة العقد / Contract Review",
    "COMM_CONTRACT_SIGNATURE_INSTRUCTIONS": "رابط وإرشادات توقيع العقد النهائي / Contract Signature",
    "COMM_TENANCY_WELCOME": "ترحيب بالمستأجر وتأكيد استلام الوحدة / Tenancy Welcome",
    "COMM_RENT_DUE_REMINDER": "تذكير بموعد استحقاق دفعة الإيجار / Rent Due Reminder",
}

def resolve_comm_business_cause(template_id: Optional[str], subject: Optional[str], inquiry_type: Optional[str]) -> Optional[str]:
    if template_id and template_id in COMM_CAUSE_MAP:
        return COMM_CAUSE_MAP[template_id]
    if subject:
        return subject
    if inquiry_type:
        return f"معاملة {inquiry_type}"
    return None


@router.get("/communications", response_model=CollectionEnvelope[CommunicationOut])
async def list_communications(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    channel: Optional[str] = None,
    direction: Optional[str] = None,
    customer_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    opportunity_id: Optional[str] = None,
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if channel:
        conditions.append(f"cm.channel = ${p_idx}")
        params.append(channel.upper())
        p_idx += 1

    if direction:
        conditions.append(f"cm.direction = ${p_idx}")
        params.append(direction.upper())
        p_idx += 1

    if customer_id:
        conditions.append(f"cm.customer_id = ${p_idx}")
        params.append(customer_id)
        p_idx += 1

    if lead_id:
        conditions.append(f"cm.lead_id = ${p_idx}")
        params.append(lead_id)
        p_idx += 1

    if opportunity_id:
        conditions.append(f"cm.lead_id IN (SELECT lead_id FROM opportunities WHERE opportunity_id = ${p_idx})")
        params.append(opportunity_id)
        p_idx += 1

    if search:
        s = f"%{search.strip()}%"
        conditions.append(f"(cm.subject ILIKE ${p_idx} OR cm.body ILIKE ${p_idx} OR cm.lead_id ILIKE ${p_idx})")
        params.append(s)
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"SELECT count(*) FROM communications cm WHERE {where_clause}", *params)

    query = f"""
        SELECT 
            cm.communication_id,
            cm.channel,
            cm.direction,
            cm.external_message_id,
            cm.subject,
            cm.body,
            cm.customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            cm.lead_id,
            opp.opportunity_id,
            l.inquiry_type,
            cm.template_id,
            cm.sent_at,
            cm.delivery_status
        FROM communications cm
        LEFT JOIN customers c ON cm.customer_id = c.customer_id
        LEFT JOIN leads l ON cm.lead_id = l.lead_id
        LEFT JOIN LATERAL (
            SELECT opportunity_id FROM opportunities WHERE lead_id = cm.lead_id ORDER BY created_at DESC LIMIT 1
        ) opp ON true
        WHERE {where_clause}
        ORDER BY cm.sent_at DESC NULLS LAST
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = []
    for r in rows:
        d = dict(r)
        d["business_cause"] = resolve_comm_business_cause(d.get("template_id"), d.get("subject"), d.get("inquiry_type"))
        data.append(CommunicationOut(**d))

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/communications", response_model=ResponseEnvelope[CommunicationOut], status_code=status.HTTP_201_CREATED)
async def create_communication(payload: CommunicationCreateIn, conn: asyncpg.Connection = Depends(get_db)):
    comm_id = await get_next_id(conn, "communications", "communication")
    now = payload.sent_at or datetime.now(timezone.utc)
    ch = payload.channel.upper()
    dir_clean = payload.direction.upper()

    actual_lead_id = payload.lead_id
    if not actual_lead_id and payload.opportunity_id:
        actual_lead_id = await conn.fetchval(
            "SELECT lead_id FROM opportunities WHERE opportunity_id = $1",
            payload.opportunity_id
        )

    cust_name = None
    if payload.customer_id:
        c = await conn.fetchrow("SELECT first_name, last_name, company_name FROM customers WHERE customer_id = $1", payload.customer_id)
        if c:
            cust_name = (f"{c['first_name'] or ''} {c['last_name'] or ''}").strip() or c["company_name"]

    await conn.execute(
        """
        INSERT INTO communications (
            communication_id, customer_id, lead_id, channel, direction,
            external_message_id, subject, body, sent_at, delivery_status, template_id
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
        comm_id, payload.customer_id, actual_lead_id, ch, dir_clean,
        f"MSG-{uuid4().hex[:12].upper()}", payload.subject, payload.body,
        now, payload.delivery_status or "SENT", payload.template_id
    )

    out = CommunicationOut(
        communication_id=comm_id,
        channel=ch,
        direction=dir_clean,
        external_message_id=f"MSG-{uuid4().hex[:12].upper()}",
        subject=payload.subject,
        body=payload.body,
        customer_id=payload.customer_id,
        customer_name=cust_name,
        lead_id=actual_lead_id,
        opportunity_id=payload.opportunity_id,
        template_id=payload.template_id,
        business_cause=resolve_comm_business_cause(payload.template_id, payload.subject, None),
        sent_at=now,
        delivery_status=payload.delivery_status or "SENT"
    )
    return ResponseEnvelope(data=out)


# =========================================================================
# INTERNAL TASK REMINDER PINGS & NON-DESTRUCTIVE CONTEXTUAL MESSAGING
# =========================================================================

@router.post("/internal-pings", response_model=ResponseEnvelope[InternalPingOut], status_code=status.HTTP_201_CREATED)
async def create_internal_ping(
    payload: InternalPingCreateIn,
    x_user_id: Optional[str] = Header("user-51", alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    sender_id = x_user_id or "user-51"
    sender_name = await conn.fetchval("SELECT full_name FROM users WHERE user_id = $1", sender_id) or sender_id

    # Resolve recipient if not provided
    recipient_id = payload.recipient_user_id
    recipient_name = None

    if recipient_id:
        recipient_name = await conn.fetchval("SELECT full_name FROM users WHERE user_id = $1", recipient_id)
    else:
        # Auto-resolve by recipient_role
        role_code = payload.recipient_role.upper()
        if role_code in ("DIRECT_MANAGER", "SALES_MANAGER", "BRANCH_MANAGER"):
            sender_branch = await conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", sender_id)
            if sender_branch:
                row = await conn.fetchrow("""
                    SELECT u.user_id, u.full_name FROM users u
                    JOIN user_roles ur ON u.user_id = ur.user_id
                    JOIN roles r ON ur.role_id = r.role_id
                    WHERE u.branch_id = $1 AND r.role_code IN ('SALES_MANAGER', 'BRANCH_MANAGER', 'SYS_ADMIN')
                    LIMIT 1
                """, sender_branch)
                if row:
                    recipient_id = row["user_id"]
                    recipient_name = row["full_name"]
        elif role_code == "ACCOUNTANT":
            sender_branch = await conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", sender_id)
            if sender_branch:
                row = await conn.fetchrow("""
                    SELECT u.user_id, u.full_name FROM users u
                    JOIN user_roles ur ON u.user_id = ur.user_id
                    JOIN roles r ON ur.role_id = r.role_id
                    WHERE r.role_code = 'ACCOUNTANT' AND u.branch_id = $1
                    LIMIT 1
                """, sender_branch)
                if row:
                    recipient_id = row["user_id"]
                    recipient_name = row["full_name"]
            if not recipient_id:
                row = await conn.fetchrow("""
                    SELECT u.user_id, u.full_name FROM users u
                    JOIN user_roles ur ON u.user_id = ur.user_id
                    JOIN roles r ON ur.role_id = r.role_id
                    WHERE r.role_code = 'ACCOUNTANT'
                    LIMIT 1
                """)
                if row:
                    recipient_id = row["user_id"]
                    recipient_name = row["full_name"]
        elif role_code in ("ASSIGNED_AGENT", "AGENT"):
            # Try matching assignedUser from snapshot if present
            assigned_name = payload.context_snapshot.get("assignedUser") if isinstance(payload.context_snapshot, dict) else None
            if assigned_name and assigned_name != "--":
                row = await conn.fetchrow("SELECT user_id, full_name FROM users WHERE full_name ILIKE $1 LIMIT 1", f"%{assigned_name}%")
                if row:
                    recipient_id = row["user_id"]
                    recipient_name = row["full_name"]
            # Or look up context_id in reservations -> opportunities
            if not recipient_id and payload.context_id:
                cid = payload.context_id
                if cid.startswith("res-") or payload.context_type in ("RESERVATION", "RESERVATION_DEPOSIT"):
                    row = await conn.fetchrow("""
                        SELECT u.user_id, u.full_name 
                        FROM reservations r
                        JOIN opportunities o ON r.opportunity_id = o.opportunity_id
                        JOIN users u ON o.assigned_user_id = u.user_id
                        WHERE r.reservation_id = $1
                    """, cid)
                    if row:
                        recipient_id = row["user_id"]
                        recipient_name = row["full_name"]
                elif cid.startswith("lead-") or payload.context_type == "LEAD":
                    row = await conn.fetchrow("""
                        SELECT u.user_id, u.full_name
                        FROM leads l
                        JOIN users u ON l.assigned_agent_id = u.user_id
                        WHERE l.lead_id = $1
                    """, cid)
                    if row:
                        recipient_id = row["user_id"]
                        recipient_name = row["full_name"]
                elif cid.startswith("opp-") or payload.context_type == "OPPORTUNITY":
                    row = await conn.fetchrow("""
                        SELECT u.user_id, u.full_name
                        FROM opportunities o
                        JOIN users u ON o.assigned_user_id = u.user_id
                        WHERE o.opportunity_id = $1
                    """, cid)
                    if row:
                        recipient_id = row["user_id"]
                        recipient_name = row["full_name"]
        elif role_code == "PROPERTY_MANAGER":
            row = await conn.fetchrow("""
                SELECT u.user_id, u.full_name FROM users u
                JOIN user_roles ur ON u.user_id = ur.user_id
                JOIN roles r ON ur.role_id = r.role_id
                WHERE r.role_code = 'PROPERTY_MANAGER'
                LIMIT 1
            """)
            if row:
                recipient_id = row["user_id"]
                recipient_name = row["full_name"]
        elif role_code in ("GENERAL_MANAGER", "SYS_ADMIN"):
            row = await conn.fetchrow("""
                SELECT u.user_id, u.full_name FROM users u
                JOIN user_roles ur ON u.user_id = ur.user_id
                JOIN roles r ON ur.role_id = r.role_id
                WHERE r.role_code = 'SYS_ADMIN'
                LIMIT 1
            """)
            if row:
                recipient_id = row["user_id"]
                recipient_name = row["full_name"]
        
        # Fallback to general manager if still unresolved
        if not recipient_id:
            row = await conn.fetchrow("""
                SELECT u.user_id, u.full_name FROM users u
                JOIN user_roles ur ON u.user_id = ur.user_id
                JOIN roles r ON ur.role_id = r.role_id
                WHERE r.role_code = 'SYS_ADMIN'
                LIMIT 1
            """)
            if row:
                recipient_id = row["user_id"]
                recipient_name = row["full_name"]

    now = datetime.now(timezone.utc)
    ping_id = f"PNG-{now.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
    archived_at = now if payload.is_archived else None

    import json
    snapshot_json = json.dumps(payload.context_snapshot)

    await conn.execute("""
        INSERT INTO internal_task_pings (
            ping_id, sender_user_id, sender_name, recipient_role,
            recipient_user_id, recipient_name, context_type, context_id,
            context_snapshot, message_text, urgency_level, is_read,
            is_archived, archived_at, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, FALSE, $12, $13, $14)
    """, ping_id, sender_id, sender_name, payload.recipient_role,
        recipient_id, recipient_name, payload.context_type.upper(),
        payload.context_id, snapshot_json, payload.message_text,
        payload.urgency_level.upper(), payload.is_archived, archived_at, now)

    # Deliver CC copies to downward managers hierarchically (excluding the sending manager)
    cc_manager_ids = payload.context_snapshot.get("cc_manager_ids", []) if isinstance(payload.context_snapshot, dict) else []
    if isinstance(cc_manager_ids, list):
        for cc_uid in cc_manager_ids:
            if cc_uid and str(cc_uid) != str(sender_id) and str(cc_uid) != str(recipient_id):
                cc_row = await conn.fetchrow("SELECT full_name FROM users WHERE user_id = $1", str(cc_uid))
                if cc_row:
                    cc_ping_id = f"PNG-{now.strftime('%Y%m%d')}-{uuid4().hex[:6].upper()}"
                    await conn.execute("""
                        INSERT INTO internal_task_pings (
                            ping_id, sender_user_id, sender_name, recipient_role,
                            recipient_user_id, recipient_name, context_type, context_id,
                            context_snapshot, message_text, urgency_level, is_read,
                            is_archived, archived_at, created_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, FALSE, $12, $13, $14)
                    """, cc_ping_id, sender_id, sender_name, "CC_MANAGER",
                        str(cc_uid), cc_row["full_name"], payload.context_type.upper(),
                        payload.context_id, snapshot_json, f"[نسخة إشعار للمدير / CC Manager] {payload.message_text}",
                        payload.urgency_level.upper(), payload.is_archived, archived_at, now)

    out = InternalPingOut(
        ping_id=ping_id,
        sender_user_id=sender_id,
        sender_name=sender_name,
        recipient_role=payload.recipient_role,
        recipient_user_id=recipient_id,
        recipient_name=recipient_name,
        context_type=payload.context_type.upper(),
        context_id=payload.context_id,
        context_snapshot=payload.context_snapshot,
        message_text=payload.message_text,
        urgency_level=payload.urgency_level.upper(),
        is_read=False,
        is_archived=payload.is_archived,
        archived_at=archived_at,
        created_at=now
    )
    return ResponseEnvelope(data=out)


@router.get("/internal-pings/inbox", response_model=ResponseEnvelope[InternalPingsInboxOut])
async def get_internal_pings_inbox(
    filter_type: Optional[str] = Query("ALL", description="ALL, UNREAD, ARCHIVED, SENT"),
    limit: int = Query(50, ge=1, le=200),
    x_user_id: Optional[str] = Header("user-51", alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    uid = x_user_id or "user-51"

    # Base counts for user
    total_count = await conn.fetchval("""
        SELECT COUNT(*) FROM internal_task_pings
        WHERE recipient_user_id = $1 OR sender_user_id = $1
    """, uid) or 0

    unread_count = await conn.fetchval("""
        SELECT COUNT(*) FROM internal_task_pings
        WHERE recipient_user_id = $1 AND is_read = FALSE
    """, uid) or 0

    archived_count = await conn.fetchval("""
        SELECT COUNT(*) FROM internal_task_pings
        WHERE (recipient_user_id = $1 OR sender_user_id = $1) AND is_archived = TRUE
    """, uid) or 0

    import json
    ft = (filter_type or "ALL").upper()
    where_clause = ""
    params = [uid]

    if ft == "UNREAD":
        where_clause = "WHERE recipient_user_id = $1 AND is_read = FALSE"
    elif ft == "ARCHIVED":
        where_clause = "WHERE (recipient_user_id = $1 OR sender_user_id = $1) AND is_archived = TRUE"
    elif ft == "SENT":
        where_clause = "WHERE sender_user_id = $1"
    else:  # ALL
        where_clause = "WHERE recipient_user_id = $1 OR sender_user_id = $1"

    query = f"""
        SELECT ping_id, sender_user_id, sender_name, recipient_role,
               recipient_user_id, recipient_name, context_type, context_id,
               context_snapshot, message_text, urgency_level, is_read,
               read_at, is_archived, archived_at, created_at
        FROM internal_task_pings
        {where_clause}
        ORDER BY created_at DESC
        LIMIT {limit}
    """
    rows = await conn.fetch(query, *params)
    pings = []
    for r in rows:
        snapshot = r["context_snapshot"]
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except Exception:
                snapshot = {}
        elif not isinstance(snapshot, dict):
            snapshot = {}

        pings.append(InternalPingOut(
            ping_id=r["ping_id"],
            sender_user_id=r["sender_user_id"],
            sender_name=r["sender_name"],
            recipient_role=r["recipient_role"],
            recipient_user_id=r["recipient_user_id"],
            recipient_name=r["recipient_name"],
            context_type=r["context_type"],
            context_id=r["context_id"],
            context_snapshot=snapshot,
            message_text=r["message_text"],
            urgency_level=r["urgency_level"],
            is_read=r["is_read"],
            read_at=r["read_at"],
            is_archived=r["is_archived"],
            archived_at=r["archived_at"],
            created_at=r["created_at"]
        ))

    out = InternalPingsInboxOut(
        pings=pings,
        summary=InternalPingsSummary(
            total_count=total_count,
            unread_count=unread_count,
            archived_count=archived_count
        )
    )
    return ResponseEnvelope(data=out)


@router.patch("/internal-pings/{ping_id}/read", response_model=ResponseEnvelope[InternalPingOut])
async def toggle_ping_read(
    ping_id: str,
    conn: asyncpg.Connection = Depends(get_db)
):
    row = await conn.fetchrow("SELECT * FROM internal_task_pings WHERE ping_id = $1", ping_id)
    if not row:
        raise HTTPException(status_code=404, detail="Ping not found")

    new_state = not row["is_read"]
    now = datetime.now(timezone.utc) if new_state else None
    await conn.execute("""
        UPDATE internal_task_pings
        SET is_read = $1, read_at = $2
        WHERE ping_id = $3
    """, new_state, now, ping_id)

    updated = await conn.fetchrow("SELECT * FROM internal_task_pings WHERE ping_id = $1", ping_id)
    import json
    snapshot = updated["context_snapshot"]
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except Exception:
            snapshot = {}
    elif not isinstance(snapshot, dict):
        snapshot = {}

    out = InternalPingOut(
        ping_id=updated["ping_id"],
        sender_user_id=updated["sender_user_id"],
        sender_name=updated["sender_name"],
        recipient_role=updated["recipient_role"],
        recipient_user_id=updated["recipient_user_id"],
        recipient_name=updated["recipient_name"],
        context_type=updated["context_type"],
        context_id=updated["context_id"],
        context_snapshot=snapshot,
        message_text=updated["message_text"],
        urgency_level=updated["urgency_level"],
        is_read=updated["is_read"],
        read_at=updated["read_at"],
        is_archived=updated["is_archived"],
        archived_at=updated["archived_at"],
        created_at=updated["created_at"]
    )
    return ResponseEnvelope(data=out)


@router.patch("/internal-pings/{ping_id}/archive", response_model=ResponseEnvelope[InternalPingOut])
async def toggle_ping_archive(
    ping_id: str,
    conn: asyncpg.Connection = Depends(get_db)
):
    row = await conn.fetchrow("SELECT * FROM internal_task_pings WHERE ping_id = $1", ping_id)
    if not row:
        raise HTTPException(status_code=404, detail="Ping not found")

    new_state = not row["is_archived"]
    now = datetime.now(timezone.utc) if new_state else None
    await conn.execute("""
        UPDATE internal_task_pings
        SET is_archived = $1, archived_at = $2
        WHERE ping_id = $3
    """, new_state, now, ping_id)

    updated = await conn.fetchrow("SELECT * FROM internal_task_pings WHERE ping_id = $1", ping_id)
    import json
    snapshot = updated["context_snapshot"]
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except Exception:
            snapshot = {}
    elif not isinstance(snapshot, dict):
        snapshot = {}

    out = InternalPingOut(
        ping_id=updated["ping_id"],
        sender_user_id=updated["sender_user_id"],
        sender_name=updated["sender_name"],
        recipient_role=updated["recipient_role"],
        recipient_user_id=updated["recipient_user_id"],
        recipient_name=updated["recipient_name"],
        context_type=updated["context_type"],
        context_id=updated["context_id"],
        context_snapshot=snapshot,
        message_text=updated["message_text"],
        urgency_level=updated["urgency_level"],
        is_read=updated["is_read"],
        read_at=updated["read_at"],
        is_archived=updated["is_archived"],
        archived_at=updated["archived_at"],
        created_at=updated["created_at"]
    )
    return ResponseEnvelope(data=out)


@router.post("/internal-pings/cleanup-expired", response_model=ResponseEnvelope[CleanupExpiredPingsOut])
async def cleanup_expired_pings(
    retention_days: int = Query(90, ge=7, le=365, description="Days to retain read, non-archived transient pings"),
    conn: asyncpg.Connection = Depends(get_db)
):
    # Purge read, non-archived pings older than retention_days
    res = await conn.execute(f"""
        DELETE FROM internal_task_pings
        WHERE is_read = TRUE
          AND is_archived = FALSE
          AND created_at < NOW() - INTERVAL '{retention_days} days'
    """)
    purged_count = int(res.split(" ")[-1]) if res and "DELETE" in res else 0

    retained_proofs_count = await conn.fetchval("""
        SELECT COUNT(*) FROM internal_task_pings WHERE is_archived = TRUE
    """) or 0

    out = CleanupExpiredPingsOut(
        purged_count=purged_count,
        retained_proofs_count=retained_proofs_count,
        message=f"Cleaned up {purged_count} transient pings older than {retention_days} days. {retained_proofs_count} documented proofs retained indefinitely."
    )
    return ResponseEnvelope(data=out)


@router.get("/internal-pings/row-thread", response_model=ResponseEnvelope[list[InternalPingOut]])
async def get_row_pings_thread(
    context_type: str = Query(..., description="Operational category e.g. TASK, RENT_COLLECTION"),
    context_id: str = Query(..., description="Row ID e.g. TSK-102"),
    conn: asyncpg.Connection = Depends(get_db)
):
    import json
    rows = await conn.fetch("""
        SELECT ping_id, sender_user_id, sender_name, recipient_role,
               recipient_user_id, recipient_name, context_type, context_id,
               context_snapshot, message_text, urgency_level, is_read,
               read_at, is_archived, archived_at, created_at
        FROM internal_task_pings
        WHERE UPPER(context_type) = UPPER($1) AND UPPER(context_id) = UPPER($2)
        ORDER BY created_at ASC
    """, context_type, context_id)

    pings = []
    for r in rows:
        snapshot = r["context_snapshot"]
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except Exception:
                snapshot = {}
        elif not isinstance(snapshot, dict):
            snapshot = {}

        pings.append(InternalPingOut(
            ping_id=r["ping_id"],
            sender_user_id=r["sender_user_id"],
            sender_name=r["sender_name"],
            recipient_role=r["recipient_role"],
            recipient_user_id=r["recipient_user_id"],
            recipient_name=r["recipient_name"],
            context_type=r["context_type"],
            context_id=r["context_id"],
            context_snapshot=snapshot,
            message_text=r["message_text"],
            urgency_level=r["urgency_level"],
            is_read=r["is_read"],
            read_at=r["read_at"],
            is_archived=r["is_archived"],
            archived_at=r["archived_at"],
            created_at=r["created_at"]
        ))
    return ResponseEnvelope(data=pings)


