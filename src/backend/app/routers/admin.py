import json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, status, Request
import asyncpg
from app.database import get_db, get_next_id
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope, BaseMeta
from app.schemas.admin import (
    BranchOut, BranchCreateIn, BranchUpdateIn,
    PermissionOut, RoleOut, RoleCreateIn, RoleUpdateIn,
    UserOut, UserCreateIn, UserUpdateIn, UserRoleBrief,
    DataScopeRule, UserScopeEvaluationOut,
    AuditLogOut, AdminSummaryOut,
    LoginEventOut, LoginEventCreateIn,
    OrganizationOut, OrganizationUpdateIn
)

router = APIRouter(prefix="/admin", tags=["Administration, Security & Governance"])

# -------------------------------------------------------------
# Module categorization helper for permissions
# -------------------------------------------------------------
PERMISSION_MODULE_MAP = {
    "CUSTOMER_READ": "CRM / Customers",
    "CUSTOMER_WRITE": "CRM / Customers",
    "LEAD_READ": "Leads & Inquiry",
    "LEAD_WRITE": "Leads & Inquiry",
    "PROPERTY_READ": "Properties & Inventory",
    "PROPERTY_WRITE": "Properties & Inventory",
    "SALES_WRITE": "Sales & Pipeline",
    "PAYMENT_READ": "Finance & Contracts",
    "PAYMENT_WRITE": "Finance & Contracts",
    "PM_WRITE": "Property Management",
    "DOCUMENT_READ": "Documents & Files",
    "DOCUMENT_WRITE": "Documents & Files",
    "MARKETING_WRITE": "Marketing & Attribution",
    "REPORT_READ": "Reports & Analytics",
    "USER_MANAGE": "Security & Users",
    "ROLE_MANAGE": "Security & Roles",
    "ADMIN": "System Administration",
    "AUDIT_READ": "Audit & Compliance"
}

# -------------------------------------------------------------
# Data Scope definitions
# -------------------------------------------------------------
DATA_SCOPE_DEFINITIONS = [
    DataScopeRule(
        scope_code="GLOBAL",
        name_en="Global (Organization-Wide)",
        name_ar="شامل (على مستوى كامل المنظمة)",
        description_en="Full visibility across all branches, agents, inventory, and customers with no restrictions.",
        description_ar="صلاحية كاملة للاطلاع والإدارة عبر جميع الفروع والوسطاء والمخزون بدون أي قيود جغرافية أو إدارية.",
        level=1,
        applicable_roles=["SYS_ADMIN", "AUDITOR", "VIEWER", "EXECUTIVE"]
    ),
    DataScopeRule(
        scope_code="BRANCH",
        name_en="Branch Scoped",
        name_ar="على مستوى الفرع المحدد",
        description_en="Visibility restricted to records, agents, viewings, and leads belonging to the user's assigned branch.",
        description_ar="تقتصر الرؤية على السجلات والموظفين والطلبات والوحدات التابعة للفرع المحدد للمستخدم فقط.",
        level=2,
        applicable_roles=["SALES_MANAGER", "BRANCH_MANAGER"]
    ),
    DataScopeRule(
        scope_code="TEAM",
        name_en="Team & Direct Reports",
        name_ar="فريق العمل والموظفون التابعون",
        description_en="Visibility encompasses the manager's own records plus all records assigned to subordinate team members.",
        description_ar="تشمل الرؤية سجلات المسؤول بالإضافة إلى جميع السجلات المسندة لأعضاء فريقه الخاضعين لإشرافه المباشر.",
        level=3,
        applicable_roles=["SALES_DIRECTOR", "TEAM_LEAD"]
    ),
    DataScopeRule(
        scope_code="OWN",
        name_en="Assigned / Individual (Least Privilege)",
        name_ar="شخصي / مسند فقط (الحد الأدنى للصلاحيات)",
        description_en="Strict personal scope: agent can only view and manage leads, viewings, and contracts directly assigned to them.",
        description_ar="نطاق شخصي مقيد: يحق للوسيط فقط معاينة وإدارة الطلبات والمهام والمعاينات المسندة له شخصياً.",
        level=4,
        applicable_roles=["SALES_AGENT", "LEASING_AGENT"]
    )
]

def resolve_effective_scope(role_codes: List[str]) -> str:
    codes = set(r.upper() for r in role_codes)
    if "SYS_ADMIN" in codes or "ADMIN" in codes or "AUDITOR" in codes or "VIEWER" in codes:
        return "GLOBAL"
    if "SALES_MANAGER" in codes or "BRANCH_MANAGER" in codes:
        return "BRANCH"
    if "SALES_DIRECTOR" in codes:
        return "TEAM"
    if "SALES_AGENT" in codes or "LEASING_AGENT" in codes:
        return "OWN"
    return "GLOBAL"

async def log_audit_event(
    conn: asyncpg.Connection,
    org_id: str,
    user_id: Optional[str],
    entity_type: str,
    entity_id: Optional[str],
    action: str,
    old_val: Optional[Any] = None,
    new_val: Optional[Any] = None,
    ip: str = "127.0.0.1"
):
    audit_id = await get_next_id(conn, "audit_logs", "audit_log")
    try:
        old_json = json.dumps(old_val, default=str) if old_val is not None else None
    except Exception:
        old_json = str(old_val) if old_val is not None else None
    try:
        new_json = json.dumps(new_val, default=str) if new_val is not None else None
    except Exception:
        new_json = str(new_val) if new_val is not None else None

    await conn.execute("""
        INSERT INTO audit_logs (
            audit_log_id, organization_id, user_id, entity_type, entity_id, action,
            old_value_json, new_value_json, ip_address, created_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, now())
    """, audit_id, org_id, user_id, entity_type, str(entity_id) if entity_id else None,
         action, old_json, new_json, ip)


# =============================================================
# 1. Admin Summary & KPIs
# =============================================================
@router.get("/summary", response_model=ResponseEnvelope[AdminSummaryOut])
async def get_admin_summary(conn: asyncpg.Connection = Depends(get_db)):
    total_branches = await conn.fetchval("SELECT count(*) FROM branches") or 0
    total_users = await conn.fetchval("SELECT count(*) FROM users") or 0
    active_users = await conn.fetchval("SELECT count(*) FROM users WHERE status = 'ACTIVE'") or 0
    total_roles = await conn.fetchval("SELECT count(*) FROM roles") or 0
    total_permissions = await conn.fetchval("SELECT count(*) FROM permissions") or 0
    recent_audits = await conn.fetchval("SELECT count(*) FROM audit_logs WHERE created_at >= now() - INTERVAL '30 days'") or 0
    total_login_events = await conn.fetchval("SELECT count(*) FROM login_events") or 0
    successful_logins = await conn.fetchval("SELECT count(*) FROM login_events WHERE success = true") or 0
    failed_logins = await conn.fetchval("SELECT count(*) FROM login_events WHERE success = false") or 0

    out = AdminSummaryOut(
        total_branches=total_branches,
        total_users=total_users,
        active_users=active_users,
        total_roles=total_roles,
        total_permissions=total_permissions,
        recent_audit_events_count=recent_audits,
        total_login_events=total_login_events,
        successful_logins=successful_logins,
        failed_logins=failed_logins
    )
    return ResponseEnvelope(data=out, meta=BaseMeta())


# =============================================================
# 2. Branches Management
# =============================================================
@router.get("/branches", response_model=CollectionEnvelope[BranchOut])
async def list_branches(
    status_filter: Optional[str] = Query(None, alias="status"),
    city_id: Optional[str] = None,
    search: Optional[str] = None,
    conn: asyncpg.Connection = Depends(get_db)
):
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"b.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if city_id:
        conditions.append(f"b.city_id = ${p_idx}")
        params.append(city_id)
        p_idx += 1

    if search:
        conditions.append(f"(b.name ILIKE ${p_idx} OR b.branch_code ILIKE ${p_idx} OR b.branch_id ILIKE ${p_idx})")
        params.append(f"%{search}%")
        p_idx += 1

    where_clause = " AND ".join(conditions)
    query = f"""
        SELECT 
            b.branch_id,
            b.organization_id,
            b.branch_code,
            b.name,
            b.city_id,
            c.name_en AS city_name,
            b.address_line,
            b.phone,
            b.status,
            (SELECT count(*) FROM users u WHERE u.branch_id = b.branch_id) AS users_count
        FROM branches b
        LEFT JOIN cities c ON b.city_id = c.city_id
        WHERE {where_clause}
        ORDER BY b.branch_code
    """
    rows = await conn.fetch(query, *params)
    data = [BranchOut(**dict(r)) for r in rows]
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/branches/{branch_id}", response_model=ResponseEnvelope[BranchOut])
async def get_branch(branch_id: str, conn: asyncpg.Connection = Depends(get_db)):
    query = """
        SELECT 
            b.branch_id,
            b.organization_id,
            b.branch_code,
            b.name,
            b.city_id,
            c.name_en AS city_name,
            b.address_line,
            b.phone,
            b.status,
            (SELECT count(*) FROM users u WHERE u.branch_id = b.branch_id) AS users_count
        FROM branches b
        LEFT JOIN cities c ON b.city_id = c.city_id
        WHERE b.branch_id = $1
    """
    row = await conn.fetchrow(query, branch_id)
    if not row:
        raise HTTPException(status_code=404, detail="Branch not found")
    return ResponseEnvelope(data=BranchOut(**dict(row)), meta=BaseMeta())

@router.post("/branches", response_model=ResponseEnvelope[BranchOut], status_code=status.HTTP_201_CREATED)
async def create_branch(
    payload: BranchCreateIn,
    request: Request,
    conn: asyncpg.Connection = Depends(get_db)
):
    org_id = await conn.fetchval("SELECT organization_id FROM organizations ORDER BY created_at ASC LIMIT 1")
    if not org_id:
        raise HTTPException(status_code=500, detail="Organization not found")

    existing = await conn.fetchval("SELECT branch_id FROM branches WHERE LOWER(branch_code) = LOWER($1)", payload.branch_code.strip())
    if existing:
        raise HTTPException(status_code=409, detail=f"Branch code '{payload.branch_code}' already exists.")

    branch_id = await get_next_id(conn, "branches", "branch")
    st = (payload.status or "ACTIVE").upper()

    await conn.execute("""
        INSERT INTO branches (
            branch_id, organization_id, branch_code, name, city_id, address_line, phone, status
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """, branch_id, org_id, payload.branch_code.strip(), payload.name.strip(),
         payload.city_id, payload.address_line, payload.phone, st)

    # Audit log
    await log_audit_event(conn, org_id, None, "BRANCH", branch_id, "CREATE", None, payload.model_dump())

    row = await conn.fetchrow("""
        SELECT 
            b.branch_id, b.organization_id, b.branch_code, b.name, b.city_id,
            c.name_en AS city_name, b.address_line, b.phone, b.status, 0 AS users_count
        FROM branches b
        LEFT JOIN cities c ON b.city_id = c.city_id
        WHERE b.branch_id = $1
    """, branch_id)
    return ResponseEnvelope(data=BranchOut(**dict(row)), meta=BaseMeta())

@router.put("/branches/{branch_id}", response_model=ResponseEnvelope[BranchOut])
async def update_branch(
    branch_id: str,
    payload: BranchUpdateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    current = await conn.fetchrow("SELECT * FROM branches WHERE branch_id = $1", branch_id)
    if not current:
        raise HTTPException(status_code=404, detail="Branch not found")

    if payload.branch_code:
        dup = await conn.fetchval("SELECT branch_id FROM branches WHERE LOWER(branch_code) = LOWER($1) AND branch_id != $2",
                                  payload.branch_code.strip(), branch_id)
        if dup:
            raise HTTPException(status_code=409, detail=f"Branch code '{payload.branch_code}' already exists.")

    updates = []
    params = []
    p_idx = 1

    field_map = {
        "branch_code": payload.branch_code.strip() if payload.branch_code else None,
        "name": payload.name.strip() if payload.name else None,
        "city_id": payload.city_id,
        "address_line": payload.address_line,
        "phone": payload.phone,
        "status": payload.status.upper() if payload.status else None
    }

    for k, v in payload.model_dump(exclude_unset=True).items():
        if k in field_map:
            updates.append(f"{k} = ${p_idx}")
            params.append(field_map[k])
            p_idx += 1

    if updates:
        params.append(branch_id)
        await conn.execute(f"UPDATE branches SET {', '.join(updates)} WHERE branch_id = ${p_idx}", *params)
        await log_audit_event(conn, current["organization_id"], None, "BRANCH", branch_id, "UPDATE", dict(current), payload.model_dump(exclude_unset=True))

    row = await conn.fetchrow("""
        SELECT 
            b.branch_id, b.organization_id, b.branch_code, b.name, b.city_id,
            c.name_en AS city_name, b.address_line, b.phone, b.status,
            (SELECT count(*) FROM users u WHERE u.branch_id = b.branch_id) AS users_count
        FROM branches b
        LEFT JOIN cities c ON b.city_id = c.city_id
        WHERE b.branch_id = $1
    """, branch_id)
    return ResponseEnvelope(data=BranchOut(**dict(row)), meta=BaseMeta())

@router.delete("/branches/{branch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_branch(branch_id: str, conn: asyncpg.Connection = Depends(get_db)):
    users_cnt = await conn.fetchval("SELECT count(*) FROM users WHERE branch_id = $1", branch_id)
    if users_cnt > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete branch: {users_cnt} user(s) currently assigned to it. Reassign users or set status to INACTIVE.")
    
    current = await conn.fetchrow("SELECT * FROM branches WHERE branch_id = $1", branch_id)
    if not current:
        raise HTTPException(status_code=404, detail="Branch not found")

    await conn.execute("DELETE FROM branches WHERE branch_id = $1", branch_id)
    await log_audit_event(conn, current["organization_id"], None, "BRANCH", branch_id, "DELETE", dict(current), None)


# =============================================================
# 3. Users & Staff Management
# =============================================================
@router.get("/users", response_model=CollectionEnvelope[UserOut])
async def list_admin_users(
    branch_id: Optional[str] = None,
    role_id: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if status_filter:
        conditions.append(f"u.status = ${p_idx}")
        params.append(status_filter.upper())
        p_idx += 1

    if branch_id:
        conditions.append(f"u.branch_id = ${p_idx}")
        params.append(branch_id)
        p_idx += 1

    if role_id:
        conditions.append(f"EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id = u.user_id AND ur.role_id = ${p_idx})")
        params.append(role_id)
        p_idx += 1

    if search:
        conditions.append(f"(u.full_name ILIKE ${p_idx} OR u.email ILIKE ${p_idx} OR u.employee_no ILIKE ${p_idx} OR u.user_id ILIKE ${p_idx})")
        params.append(f"%{search}%")
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"SELECT count(*) FROM users u WHERE {where_clause}", *params)

    query = f"""
        SELECT 
            u.user_id,
            u.organization_id,
            u.branch_id,
            b.branch_code,
            b.name AS branch_name,
            u.employee_no,
            u.full_name,
            u.email,
            u.mobile,
            u.status,
            u.manager_user_id,
            mgr.full_name AS manager_name,
            u.created_at,
            u.updated_at
        FROM users u
        LEFT JOIN branches b ON u.branch_id = b.branch_id
        LEFT JOIN users mgr ON u.manager_user_id = mgr.user_id
        WHERE {where_clause}
        ORDER BY u.created_at ASC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)

    # Fetch roles for all fetched users in batch
    user_ids = [r["user_id"] for r in rows]
    role_map = {}
    if user_ids:
        r_rows = await conn.fetch("""
            SELECT ur.user_id, r.role_id, r.role_code, r.name
            FROM user_roles ur
            JOIN roles r ON ur.role_id = r.role_id
            WHERE ur.user_id = ANY($1)
            ORDER BY r.role_code
        """, user_ids)
        for rr in r_rows:
            uid = rr["user_id"]
            if uid not in role_map:
                role_map[uid] = []
            role_map[uid].append(UserRoleBrief(role_id=rr["role_id"], role_code=rr["role_code"], name=rr["name"]))

    data = []
    for r in rows:
        uid = r["user_id"]
        assigned_roles = role_map.get(uid, [])
        role_codes = [ar.role_code for ar in assigned_roles]
        scope = resolve_effective_scope(role_codes)
        item = dict(r)
        item["roles"] = assigned_roles
        item["effective_scope"] = scope
        data.append(UserOut(**item))

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.get("/users/{user_id}", response_model=ResponseEnvelope[UserOut])
async def get_admin_user(user_id: str, conn: asyncpg.Connection = Depends(get_db)):
    query = """
        SELECT 
            u.user_id,
            u.organization_id,
            u.branch_id,
            b.branch_code,
            b.name AS branch_name,
            u.employee_no,
            u.full_name,
            u.email,
            u.mobile,
            u.status,
            u.manager_user_id,
            mgr.full_name AS manager_name,
            u.created_at,
            u.updated_at
        FROM users u
        LEFT JOIN branches b ON u.branch_id = b.branch_id
        LEFT JOIN users mgr ON u.manager_user_id = mgr.user_id
        WHERE u.user_id = $1
    """
    row = await conn.fetchrow(query, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    r_rows = await conn.fetch("""
        SELECT r.role_id, r.role_code, r.name
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.role_id
        WHERE ur.user_id = $1
        ORDER BY r.role_code
    """, user_id)
    assigned_roles = [UserRoleBrief(**dict(rr)) for rr in r_rows]
    scope = resolve_effective_scope([ar.role_code for ar in assigned_roles])

    item = dict(row)
    item["roles"] = assigned_roles
    item["effective_scope"] = scope
    return ResponseEnvelope(data=UserOut(**item), meta=BaseMeta())

@router.post("/users", response_model=ResponseEnvelope[UserOut], status_code=status.HTTP_201_CREATED)
async def create_admin_user(
    payload: UserCreateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    org_id = await conn.fetchval("SELECT organization_id FROM organizations ORDER BY created_at ASC LIMIT 1")
    if not org_id:
        raise HTTPException(status_code=500, detail="Organization not found")

    dup_email = await conn.fetchval("SELECT user_id FROM users WHERE LOWER(email) = LOWER($1)", payload.email.strip())
    if dup_email:
        raise HTTPException(status_code=409, detail=f"Email '{payload.email}' already registered.")

    if payload.branch_id:
        b_exists = await conn.fetchval("SELECT branch_id FROM branches WHERE branch_id = $1", payload.branch_id)
        if not b_exists:
            raise HTTPException(status_code=400, detail=f"Branch '{payload.branch_id}' does not exist.")

    if payload.manager_user_id:
        m_exists = await conn.fetchval("SELECT user_id FROM users WHERE user_id = $1", payload.manager_user_id)
        if not m_exists:
            raise HTTPException(status_code=400, detail=f"Manager user '{payload.manager_user_id}' does not exist.")

    user_id = await get_next_id(conn, "users", "user")
    st = (payload.status or "ACTIVE").upper()

    async with conn.transaction():
        await conn.execute("""
            INSERT INTO users (
                user_id, organization_id, branch_id, employee_no, full_name, email, mobile, status, manager_user_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """, user_id, org_id, payload.branch_id, payload.employee_no, payload.full_name.strip(),
             payload.email.strip(), payload.mobile, st, payload.manager_user_id)

        if payload.role_ids:
            for r_id in payload.role_ids:
                await conn.execute("""
                    INSERT INTO user_roles (user_id, role_id) VALUES ($1, $2) ON CONFLICT DO NOTHING
                """, user_id, r_id)

    await log_audit_event(conn, org_id, None, "USER", user_id, "CREATE", None, payload.model_dump())

    # Return refreshed user
    return await get_admin_user(user_id, conn)

@router.put("/users/{user_id}", response_model=ResponseEnvelope[UserOut])
async def update_admin_user(
    user_id: str,
    payload: UserUpdateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    current = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
    if not current:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.email:
        dup = await conn.fetchval("SELECT user_id FROM users WHERE LOWER(email) = LOWER($1) AND user_id != $2",
                                  payload.email.strip(), user_id)
        if dup:
            raise HTTPException(status_code=409, detail=f"Email '{payload.email}' already used by another user.")

    updates = []
    params = []
    p_idx = 1

    field_map = {
        "full_name": payload.full_name.strip() if payload.full_name else None,
        "email": payload.email.strip() if payload.email else None,
        "mobile": payload.mobile,
        "employee_no": payload.employee_no,
        "branch_id": payload.branch_id,
        "manager_user_id": payload.manager_user_id,
        "status": payload.status.upper() if payload.status else None
    }

    payload_dict = payload.model_dump(exclude_unset=True)
    for k in payload_dict.keys():
        if k in field_map:
            updates.append(f"{k} = ${p_idx}")
            params.append(field_map[k])
            p_idx += 1

    async with conn.transaction():
        if updates:
            updates.append("updated_at = now()")
            params.append(user_id)
            await conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id = ${p_idx}", *params)

        if payload.role_ids is not None:
            await conn.execute("DELETE FROM user_roles WHERE user_id = $1", user_id)
            for r_id in payload.role_ids:
                await conn.execute("INSERT INTO user_roles (user_id, role_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", user_id, r_id)

    await log_audit_event(conn, current["organization_id"], None, "USER", user_id, "UPDATE", dict(current), payload_dict)
    return await get_admin_user(user_id, conn)

@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_user(user_id: str, conn: asyncpg.Connection = Depends(get_db)):
    current = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
    if not current:
        raise HTTPException(status_code=404, detail="User not found")

    # Soft-delete user to maintain foreign key integrity with historical sales & communications
    await conn.execute("UPDATE users SET status = 'INACTIVE', updated_at = now() WHERE user_id = $1", user_id)
    await log_audit_event(conn, current["organization_id"], None, "USER", user_id, "DEACTIVATE", dict(current), {"status": "INACTIVE"})


# =============================================================
# 4. Roles & Permissions (RBAC)
# =============================================================
@router.get("/permissions", response_model=CollectionEnvelope[PermissionOut])
async def list_permissions(conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch("SELECT permission_id, code, name FROM permissions ORDER BY code")
    data = []
    for r in rows:
        mod = PERMISSION_MODULE_MAP.get(r["code"], "General Operations")
        data.append(PermissionOut(permission_id=r["permission_id"], code=r["code"], name=r["name"], module=mod))
    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/roles", response_model=CollectionEnvelope[RoleOut])
async def list_roles(conn: asyncpg.Connection = Depends(get_db)):
    roles_rows = await conn.fetch("""
        SELECT 
            r.role_id,
            r.organization_id,
            r.role_code,
            r.name,
            r.description,
            (SELECT count(*) FROM user_roles ur WHERE ur.role_id = r.role_id) AS users_count
        FROM roles r
        ORDER BY r.role_code
    """)

    perm_rows = await conn.fetch("""
        SELECT rp.role_id, p.permission_id, p.code, p.name
        FROM role_permissions rp
        JOIN permissions p ON rp.permission_id = p.permission_id
        ORDER BY p.code
    """)
    perm_map = {}
    for pr in perm_rows:
        rid = pr["role_id"]
        if rid not in perm_map:
            perm_map[rid] = []
        mod = PERMISSION_MODULE_MAP.get(pr["code"], "General Operations")
        perm_map[rid].append(PermissionOut(permission_id=pr["permission_id"], code=pr["code"], name=pr["name"], module=mod))

    data = []
    for r in roles_rows:
        rid = r["role_id"]
        scope = resolve_effective_scope([r["role_code"]])
        data.append(RoleOut(
            role_id=r["role_id"],
            organization_id=r["organization_id"],
            role_code=r["role_code"],
            name=r["name"],
            description=r["description"],
            default_scope=scope,
            users_count=r["users_count"],
            permissions=perm_map.get(rid, [])
        ))

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=1, page_size=len(data), total=len(data))
    )

@router.get("/roles/{role_id}", response_model=ResponseEnvelope[RoleOut])
async def get_role(role_id: str, conn: asyncpg.Connection = Depends(get_db)):
    r = await conn.fetchrow("""
        SELECT 
            r.role_id, r.organization_id, r.role_code, r.name, r.description,
            (SELECT count(*) FROM user_roles ur WHERE ur.role_id = r.role_id) AS users_count
        FROM roles r
        WHERE r.role_id = $1
    """, role_id)
    if not r:
        raise HTTPException(status_code=404, detail="Role not found")

    perm_rows = await conn.fetch("""
        SELECT p.permission_id, p.code, p.name
        FROM role_permissions rp
        JOIN permissions p ON rp.permission_id = p.permission_id
        WHERE rp.role_id = $1
        ORDER BY p.code
    """, role_id)
    perms = [
        PermissionOut(permission_id=pr["permission_id"], code=pr["code"], name=pr["name"], module=PERMISSION_MODULE_MAP.get(pr["code"], "General"))
        for pr in perm_rows
    ]
    scope = resolve_effective_scope([r["role_code"]])
    out = RoleOut(
        role_id=r["role_id"],
        organization_id=r["organization_id"],
        role_code=r["role_code"],
        name=r["name"],
        description=r["description"],
        default_scope=scope,
        users_count=r["users_count"],
        permissions=perms
    )
    return ResponseEnvelope(data=out, meta=BaseMeta())

@router.post("/roles", response_model=ResponseEnvelope[RoleOut], status_code=status.HTTP_201_CREATED)
async def create_role(payload: RoleCreateIn, conn: asyncpg.Connection = Depends(get_db)):
    org_id = await conn.fetchval("SELECT organization_id FROM organizations ORDER BY created_at ASC LIMIT 1")
    code = payload.role_code.strip().upper()

    dup = await conn.fetchval("SELECT role_id FROM roles WHERE role_code = $1", code)
    if dup:
        raise HTTPException(status_code=409, detail=f"Role code '{code}' already exists.")

    role_id = await get_next_id(conn, "roles", "role")

    async with conn.transaction():
        await conn.execute("""
            INSERT INTO roles (role_id, organization_id, role_code, name, description)
            VALUES ($1, $2, $3, $4, $5)
        """, role_id, org_id, code, payload.name.strip(), payload.description)

        if payload.permission_ids:
            for pid in payload.permission_ids:
                await conn.execute("""
                    INSERT INTO role_permissions (role_id, permission_id) VALUES ($1, $2) ON CONFLICT DO NOTHING
                """, role_id, pid)

    await log_audit_event(conn, org_id, None, "ROLE", role_id, "CREATE", None, payload.model_dump())
    return await get_role(role_id, conn)

@router.put("/roles/{role_id}", response_model=ResponseEnvelope[RoleOut])
async def update_role(role_id: str, payload: RoleUpdateIn, conn: asyncpg.Connection = Depends(get_db)):
    current = await conn.fetchrow("SELECT * FROM roles WHERE role_id = $1", role_id)
    if not current:
        raise HTTPException(status_code=404, detail="Role not found")

    async with conn.transaction():
        if payload.name or payload.description is not None:
            new_name = payload.name.strip() if payload.name else current["name"]
            new_desc = payload.description if payload.description is not None else current["description"]
            await conn.execute("UPDATE roles SET name = $1, description = $2 WHERE role_id = $3", new_name, new_desc, role_id)

        if payload.permission_ids is not None:
            await conn.execute("DELETE FROM role_permissions WHERE role_id = $1", role_id)
            for pid in payload.permission_ids:
                await conn.execute("INSERT INTO role_permissions (role_id, permission_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", role_id, pid)

    await log_audit_event(conn, current["organization_id"], None, "ROLE", role_id, "UPDATE", dict(current), payload.model_dump(exclude_unset=True))
    return await get_role(role_id, conn)

@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: str, conn: asyncpg.Connection = Depends(get_db)):
    current = await conn.fetchrow("SELECT * FROM roles WHERE role_id = $1", role_id)
    if not current:
        raise HTTPException(status_code=404, detail="Role not found")

    if current["role_code"] in ("SYS_ADMIN", "ADMIN"):
        raise HTTPException(status_code=400, detail="Cannot delete core system administrator role.")

    users_cnt = await conn.fetchval("SELECT count(*) FROM user_roles WHERE role_id = $1", role_id)
    if users_cnt > 0:
        raise HTTPException(status_code=400, detail=f"Cannot delete role: {users_cnt} user(s) currently hold this role.")

    async with conn.transaction():
        await conn.execute("DELETE FROM role_permissions WHERE role_id = $1", role_id)
        await conn.execute("DELETE FROM roles WHERE role_id = $1", role_id)

    await log_audit_event(conn, current["organization_id"], None, "ROLE", role_id, "DELETE", dict(current), None)


# =============================================================
# 5. Data Scope & Scope Evaluation
# =============================================================
@router.get("/data-scopes", response_model=ResponseEnvelope[List[DataScopeRule]])
async def list_data_scopes():
    return ResponseEnvelope(data=DATA_SCOPE_DEFINITIONS, meta=BaseMeta())

@router.get("/users/{user_id}/scope", response_model=ResponseEnvelope[UserScopeEvaluationOut])
async def evaluate_user_scope_endpoint(user_id: str, conn: asyncpg.Connection = Depends(get_db)):
    user = await conn.fetchrow("""
        SELECT u.user_id, u.full_name, u.branch_id, b.name AS branch_name
        FROM users u
        LEFT JOIN branches b ON u.branch_id = b.branch_id
        WHERE u.user_id = $1
    """, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    r_rows = await conn.fetch("""
        SELECT r.role_code
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.role_id
        WHERE ur.user_id = $1
    """, user_id)
    role_codes = [r["role_code"] for r in r_rows]
    eff_scope = resolve_effective_scope(role_codes)

    # Subordinate team user IDs
    team_rows = await conn.fetch("""
        WITH RECURSIVE subordinates AS (
            SELECT user_id FROM users WHERE manager_user_id = $1
            UNION
            SELECT u.user_id FROM users u
            INNER JOIN subordinates s ON s.user_id = u.manager_user_id
        )
        SELECT user_id FROM subordinates
    """, user_id)
    team_ids = [tr["user_id"] for tr in team_rows]

    # Effective permissions
    p_rows = await conn.fetch("""
        SELECT DISTINCT p.code
        FROM user_roles ur
        JOIN role_permissions rp ON ur.role_id = rp.role_id
        JOIN permissions p ON rp.permission_id = p.permission_id
        WHERE ur.user_id = $1
        ORDER BY p.code
    """, user_id)
    perm_codes = [pr["code"] for pr in p_rows]

    out = UserScopeEvaluationOut(
        user_id=user["user_id"],
        full_name=user["full_name"],
        effective_scope=eff_scope,
        branch_id=user["branch_id"],
        branch_name=user["branch_name"],
        team_user_ids=team_ids,
        roles=role_codes,
        permissions=perm_codes
    )
    return ResponseEnvelope(data=out, meta=BaseMeta())


# =============================================================
# 6. Audit Trail & Compliance Logs
# =============================================================
@router.get("/audit-logs", response_model=CollectionEnvelope[AuditLogOut])
async def list_audit_logs(
    entity_type: Optional[str] = None,
    action: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if entity_type:
        conditions.append(f"al.entity_type = ${p_idx}")
        params.append(entity_type.upper())
        p_idx += 1

    if action:
        conditions.append(f"al.action = ${p_idx}")
        params.append(action.upper())
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"SELECT count(*) FROM audit_logs al WHERE {where_clause}", *params)

    query = f"""
        SELECT 
            al.audit_log_id,
            al.organization_id,
            al.user_id,
            u.full_name AS user_name,
            al.entity_type,
            al.entity_id,
            al.action,
            al.old_value_json,
            al.new_value_json,
            al.ip_address,
            al.user_agent,
            al.created_at
        FROM audit_logs al
        LEFT JOIN users u ON al.user_id = u.user_id
        WHERE {where_clause}
        ORDER BY al.created_at DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [AuditLogOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )


# =============================================================
# 7. Authentication History & Login Events
# =============================================================
@router.get("/login-events", response_model=CollectionEnvelope[LoginEventOut])
async def list_login_events(
    user_id: Optional[str] = None,
    success: Optional[bool] = None,
    event_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = ["1=1"]
    params = []
    p_idx = 1

    if user_id:
        conditions.append(f"le.user_id = ${p_idx}")
        params.append(user_id)
        p_idx += 1

    if success is not None:
        conditions.append(f"le.success = ${p_idx}")
        params.append(success)
        p_idx += 1

    if event_type:
        conditions.append(f"le.event_type = ${p_idx}")
        params.append(event_type.upper())
        p_idx += 1

    where_clause = " AND ".join(conditions)
    total = await conn.fetchval(f"SELECT count(*) FROM login_events le WHERE {where_clause}", *params)

    query = f"""
        SELECT 
            le.login_event_id,
            le.user_id,
            u.full_name AS user_name,
            u.email AS user_email,
            le.event_type,
            le.ip_address,
            le.occurred_at,
            le.success
        FROM login_events le
        LEFT JOIN users u ON le.user_id = u.user_id
        WHERE {where_clause}
        ORDER BY le.occurred_at DESC
        LIMIT ${p_idx} OFFSET ${p_idx + 1}
    """
    params.extend([page_size, offset])
    rows = await conn.fetch(query, *params)
    data = [LoginEventOut(**dict(r)) for r in rows]

    return CollectionEnvelope(
        data=data,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )

@router.post("/login-events", response_model=ResponseEnvelope[LoginEventOut], status_code=status.HTTP_201_CREATED)
async def create_login_event(payload: LoginEventCreateIn, conn: asyncpg.Connection = Depends(get_db)):
    event_id = await get_next_id(conn, "login_events", "login_event")
    await conn.execute("""
        INSERT INTO login_events (login_event_id, user_id, event_type, ip_address, occurred_at, success)
        VALUES ($1, $2, $3, $4, now(), $5)
    """, event_id, payload.user_id, payload.event_type.upper(), payload.ip_address, payload.success)

    row = await conn.fetchrow("""
        SELECT 
            le.login_event_id,
            le.user_id,
            u.full_name AS user_name,
            u.email AS user_email,
            le.event_type,
            le.ip_address,
            le.occurred_at,
            le.success
        FROM login_events le
        LEFT JOIN users u ON le.user_id = u.user_id
        WHERE le.login_event_id = $1
    """, event_id)
    return ResponseEnvelope(data=LoginEventOut(**dict(row)), meta=BaseMeta())


# =============================================================
# 8. Organization Identity & Configuration
# =============================================================
@router.get("/organization", response_model=ResponseEnvelope[OrganizationOut])
async def get_organization(conn: asyncpg.Connection = Depends(get_db)):
    row = await conn.fetchrow("""
        SELECT organization_id, organization_code, legal_name, trade_name, country_code,
               timezone, currency_code, tax_number, status, created_at, updated_at
        FROM organizations
        ORDER BY created_at ASC
        LIMIT 1
    """)
    if not row:
        raise HTTPException(status_code=404, detail="Organization record not found")
    return ResponseEnvelope(data=OrganizationOut(**dict(row)), meta=BaseMeta())

@router.put("/organization", response_model=ResponseEnvelope[OrganizationOut])
async def update_organization(payload: OrganizationUpdateIn, conn: asyncpg.Connection = Depends(get_db)):
    org = await conn.fetchrow("SELECT organization_id, legal_name, trade_name, tax_number, timezone, currency_code FROM organizations LIMIT 1")
    if not org:
        raise HTTPException(status_code=404, detail="Organization record not found")
    org_id = org["organization_id"]

    updates = []
    params = []
    p_idx = 1
    if payload.legal_name is not None:
        updates.append(f"legal_name = ${p_idx}")
        params.append(payload.legal_name)
        p_idx += 1
    if payload.trade_name is not None:
        updates.append(f"trade_name = ${p_idx}")
        params.append(payload.trade_name)
        p_idx += 1
    if payload.tax_number is not None:
        updates.append(f"tax_number = ${p_idx}")
        params.append(payload.tax_number)
        p_idx += 1
    if payload.timezone is not None:
        updates.append(f"timezone = ${p_idx}")
        params.append(payload.timezone)
        p_idx += 1
    if payload.currency_code is not None:
        updates.append(f"currency_code = ${p_idx}")
        params.append(payload.currency_code.upper())
        p_idx += 1

    if updates:
        updates.append("updated_at = now()")
        params.append(org_id)
        await conn.execute(f"UPDATE organizations SET {', '.join(updates)} WHERE organization_id = ${p_idx}", *params)
        await log_audit_event(
            conn, org_id, None, "organizations", org_id, "UPDATE",
            old_val=dict(org), new_val=payload.model_dump(exclude_unset=True)
        )

    row = await conn.fetchrow("""
        SELECT organization_id, organization_code, legal_name, trade_name, country_code,
               timezone, currency_code, tax_number, status, created_at, updated_at
        FROM organizations
        WHERE organization_id = $1
    """, org_id)
    return ResponseEnvelope(data=OrganizationOut(**dict(row)), meta=BaseMeta())


