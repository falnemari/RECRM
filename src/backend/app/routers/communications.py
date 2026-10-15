from typing import Optional, List
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException, status, Header
import asyncpg
from app.database import get_db, get_next_id
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope
from app.routers.auth import check_user_scope_override
from app.schemas.communications import (
    TasksSummaryOut,
    TaskOut, TaskCreateIn, TaskUpdateIn,
    ActivityOut, ActivityCreateIn,
    CommunicationOut, CommunicationCreateIn
)

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
    assigned_user_id = await check_user_scope_override(conn, x_user_id, assigned_user_id)
    ag_cond = ""
    ag_params = []
    if assigned_user_id:
        ag_cond = " AND assigned_user_id = $1"
        ag_params = [assigned_user_id]

    open_tasks = await conn.fetchval(f"SELECT count(*) FROM tasks WHERE status = 'OPEN'{ag_cond}", *ag_params) or 0
    overdue_tasks = await conn.fetchval(f"SELECT count(*) FROM tasks WHERE status = 'OPEN' AND due_at < NOW(){ag_cond}", *ag_params) or 0
    completed_tasks = await conn.fetchval(f"SELECT count(*) FROM tasks WHERE status = 'COMPLETED'{ag_cond}", *ag_params) or 0
    
    act_user_cond = f" WHERE user_id = $1" if assigned_user_id else ""
    total_acts = await conn.fetchval(f"SELECT count(*) FROM activities{act_user_cond}", *ag_params) or 0
    
    viewing_act_cond = f" AND a.user_id = $1" if assigned_user_id else ""
    v_acts = await conn.fetchval(f"""
        SELECT count(*) FROM activities a
        JOIN activity_types at ON a.activity_type_id = at.activity_type_id
        WHERE at.code = 'VIEWING'{viewing_act_cond}
    """, *ag_params) or 0
    
    viewing_tbl_cond = f" WHERE agent_user_id = $1" if assigned_user_id else ""
    v_tbl = await conn.fetchval(f"SELECT count(*) FROM viewings{viewing_tbl_cond}", *ag_params) or 0
    total_viewings = v_acts + v_tbl

    total_comms = await conn.fetchval("SELECT count(*) FROM communications") or 0

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
    page_size: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    priority: Optional[str] = None,
    assigned_user_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    is_overdue: Optional[bool] = None,
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
        conditions.append(f"t.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if priority:
        conditions.append(f"t.priority = ${p_idx}")
        params.append(priority.upper())
        p_idx += 1

    if assigned_user_id:
        conditions.append(f"t.assigned_user_id = ${p_idx}")
        params.append(assigned_user_id)
        p_idx += 1

    if customer_id:
        conditions.append(f"t.customer_id = ${p_idx}")
        params.append(customer_id)
        p_idx += 1

    if is_overdue:
        conditions.append("t.status = 'OPEN' AND t.due_at < NOW()")

    if search:
        s = f"%{search.strip()}%"
        conditions.append(f"(t.title ILIKE ${p_idx} OR c.first_name ILIKE ${p_idx} OR c.last_name ILIKE ${p_idx} OR u.full_name ILIKE ${p_idx})")
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

    query = f"""
        SELECT 
            t.task_id,
            t.title,
            t.due_at,
            t.priority,
            t.status,
            t.assigned_user_id,
            u.full_name AS assigned_user_name,
            t.customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            t.lead_id,
            t.opportunity_id,
            CASE WHEN t.status = 'OPEN' AND t.due_at < NOW() THEN true ELSE false END AS is_overdue
        FROM tasks t
        LEFT JOIN users u ON t.assigned_user_id = u.user_id
        LEFT JOIN customers c ON t.customer_id = c.customer_id
        WHERE {where_clause}
        ORDER BY 
            CASE t.status WHEN 'OPEN' THEN 1 ELSE 2 END,
            CASE t.priority WHEN 'URGENT' THEN 1 WHEN 'HIGH' THEN 2 WHEN 'NORMAL' THEN 3 ELSE 4 END,
            t.due_at ASC NULLS LAST
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

    user_name = None
    if payload.assigned_user_id:
        usr = await conn.fetchrow("SELECT full_name FROM users WHERE user_id = $1", payload.assigned_user_id)
        if usr:
            user_name = usr["full_name"]

    cust_name = None
    if payload.customer_id:
        c = await conn.fetchrow("SELECT first_name, last_name, company_name FROM customers WHERE customer_id = $1", payload.customer_id)
        if c:
            cust_name = (f"{c['first_name'] or ''} {c['last_name'] or ''}").strip() or c["company_name"]

    await conn.execute(
        """
        INSERT INTO tasks (
            task_id, assigned_user_id, customer_id, lead_id, opportunity_id,
            title, due_at, priority, status
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        task_id, payload.assigned_user_id, payload.customer_id,
        payload.lead_id, payload.opportunity_id, payload.title,
        payload.due_at, pri, st
    )

    is_od = False
    if payload.due_at and payload.due_at < datetime.now(timezone.utc) and st == "OPEN":
        is_od = True

    out = TaskOut(
        task_id=task_id,
        title=payload.title,
        due_at=payload.due_at,
        priority=pri,
        status=st,
        assigned_user_id=payload.assigned_user_id,
        assigned_user_name=user_name,
        customer_id=payload.customer_id,
        customer_name=cust_name,
        lead_id=payload.lead_id,
        opportunity_id=payload.opportunity_id,
        is_overdue=is_od
    )
    return ResponseEnvelope(data=out)

@router.get("/tasks/{task_id}", response_model=ResponseEnvelope[TaskOut])
async def get_task(task_id: str, conn: asyncpg.Connection = Depends(get_db)):
    row = await conn.fetchrow(
        """
        SELECT 
            t.task_id,
            t.title,
            t.due_at,
            t.priority,
            t.status,
            t.assigned_user_id,
            u.full_name AS assigned_user_name,
            t.customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            t.lead_id,
            t.opportunity_id,
            CASE WHEN t.status = 'OPEN' AND t.due_at < NOW() THEN true ELSE false END AS is_overdue
        FROM tasks t
        LEFT JOIN users u ON t.assigned_user_id = u.user_id
        LEFT JOIN customers c ON t.customer_id = c.customer_id
        WHERE t.task_id = $1
        """,
        task_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return ResponseEnvelope(data=TaskOut(**dict(row)))

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
async def complete_task(task_id: str, conn: asyncpg.Connection = Depends(get_db)):
    t = await conn.fetchrow("SELECT task_id, title, customer_id, assigned_user_id FROM tasks WHERE task_id = $1", task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")

    now = datetime.now(timezone.utc)
    async with conn.transaction():
        await conn.execute("UPDATE tasks SET status = 'COMPLETED' WHERE task_id = $1", task_id)
        
        # Log completed task activity in activities table
        act_type = await conn.fetchrow("SELECT activity_type_id FROM activity_types WHERE code = 'FOLLOW_UP' LIMIT 1")
        act_type_id = act_type["activity_type_id"] if act_type else None
        
        completed_act_id = await get_next_id(conn, "activities", "activity")
        await conn.execute(
            """
            INSERT INTO activities (
                activity_id, user_id, customer_id, activity_type_id,
                subject, description, completed_at, status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'COMPLETED')
            """,
            completed_act_id, t["assigned_user_id"], t["customer_id"], act_type_id,
            f"Completed Task: {t['title']}", f"Task marked completed at {now.strftime('%Y-%m-%d %H:%M')}",
            now
        )

    return ResponseEnvelope(data={"task_id": str(task_id), "status": "COMPLETED"})


# ---------------------------------------------------------
# Activities
# ---------------------------------------------------------
@router.get("/activities", response_model=CollectionEnvelope[ActivityOut])
async def list_activities(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    activity_type: Optional[str] = None,
    user_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if activity_type:
        conditions.append(f"at.code = ${p_idx}")
        params.append(activity_type.upper())
        p_idx += 1

    if user_id:
        conditions.append(f"a.user_id = ${p_idx}")
        params.append(user_id)
        p_idx += 1

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
        conditions.append(f"(a.subject ILIKE ${p_idx} OR a.description ILIKE ${p_idx})")
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
            a.subject,
            a.description,
            a.activity_type_id,
            at.code AS activity_type_code,
            at.name AS activity_type_name,
            a.user_id,
            u.full_name AS user_name,
            a.customer_id,
            COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
            a.lead_id,
            a.opportunity_id,
            a.scheduled_at,
            a.completed_at,
            a.status
        FROM activities a
        LEFT JOIN activity_types at ON a.activity_type_id = at.activity_type_id
        LEFT JOIN users u ON a.user_id = u.user_id
        LEFT JOIN customers c ON a.customer_id = c.customer_id
        WHERE {where_clause}
        ORDER BY COALESCE(a.completed_at, a.scheduled_at) DESC NULLS LAST
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
@router.get("/communications", response_model=CollectionEnvelope[CommunicationOut])
async def list_communications(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    channel: Optional[str] = None,
    direction: Optional[str] = None,
    customer_id: Optional[str] = None,
    lead_id: Optional[str] = None,
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

    if search:
        s = f"%{search.strip()}%"
        conditions.append(f"(cm.subject ILIKE ${p_idx} OR cm.body ILIKE ${p_idx})")
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
            cm.sent_at,
            cm.delivery_status
        FROM communications cm
        LEFT JOIN customers c ON cm.customer_id = c.customer_id
        WHERE {where_clause}
        ORDER BY cm.sent_at DESC NULLS LAST
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [CommunicationOut(**dict(r)) for r in rows]

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

    cust_name = None
    if payload.customer_id:
        c = await conn.fetchrow("SELECT first_name, last_name, company_name FROM customers WHERE customer_id = $1", payload.customer_id)
        if c:
            cust_name = (f"{c['first_name'] or ''} {c['last_name'] or ''}").strip() or c["company_name"]

    await conn.execute(
        """
        INSERT INTO communications (
            communication_id, customer_id, lead_id, channel, direction,
            external_message_id, subject, body, sent_at, delivery_status
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """,
        comm_id, payload.customer_id, payload.lead_id, ch, dir_clean,
        f"MSG-{uuid4().hex[:12].upper()}", payload.subject, payload.body,
        now, payload.delivery_status or "SENT"
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
        lead_id=payload.lead_id,
        sent_at=now,
        delivery_status=payload.delivery_status or "SENT"
    )
    return ResponseEnvelope(data=out)

