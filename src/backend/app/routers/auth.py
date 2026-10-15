from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, Query, Header, HTTPException, status
import asyncpg
from app.database import get_db
from app.schemas.common import ResponseEnvelope, BaseMeta

router = APIRouter(tags=["Authentication & Session"])

def resolve_user_data_scope(role_codes: List[str]) -> str:
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

async def check_user_scope_override(
    conn: asyncpg.Connection,
    x_user_id: Optional[str],
    requested_assigned_user_id: Optional[str]
) -> Optional[str]:
    """
    Evaluates role-based data scoping for the active user:
    - If user has 'OWN' scope (e.g. SALES_AGENT, LEASING_AGENT), force assigned_user_id = x_user_id
      so they can only access their own records and never see another user's data.
    - If user has 'GLOBAL' or manager scope, respect requested_assigned_user_id (allows filtering
      to a specific agent or viewing all records).
    """
    if not x_user_id:
        return requested_assigned_user_id
    roles = await conn.fetch(
        "SELECT r.role_code FROM user_roles ur JOIN roles r ON ur.role_id = r.role_id WHERE ur.user_id = $1",
        x_user_id
    )
    role_codes = [r["role_code"] for r in roles]
    scope = resolve_user_data_scope(role_codes)
    if scope == "OWN":
        return x_user_id
    return requested_assigned_user_id

async def _fetch_user_profile(conn: asyncpg.Connection, target_user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    # If a specific user ID was requested:
    if target_user_id:
        user = await conn.fetchrow(
            """
            SELECT 
                u.user_id,
                u.employee_no,
                u.full_name,
                u.email,
                u.mobile,
                u.status,
                u.branch_id,
                b.name AS branch_name,
                o.organization_id,
                o.organization_code,
                o.legal_name AS organization_name,
                o.currency_code,
                o.timezone
            FROM users u
            JOIN organizations o ON u.organization_id = o.organization_id
            LEFT JOIN branches b ON u.branch_id = b.branch_id
            WHERE u.user_id = $1 AND u.status = 'ACTIVE'
            """,
            target_user_id
        )
    else:
        # Default priority: user-51 (Fahad Kh. Alnemari)
        user = await conn.fetchrow(
            """
            SELECT 
                u.user_id,
                u.employee_no,
                u.full_name,
                u.email,
                u.mobile,
                u.status,
                u.branch_id,
                b.name AS branch_name,
                o.organization_id,
                o.organization_code,
                o.legal_name AS organization_name,
                o.currency_code,
                o.timezone
            FROM users u
            JOIN organizations o ON u.organization_id = o.organization_id
            LEFT JOIN branches b ON u.branch_id = b.branch_id
            WHERE u.user_id = 'user-51' AND u.status = 'ACTIVE'
            """
        )
        if not user:
            # Fallback to earliest active user
            user = await conn.fetchrow(
                """
                SELECT 
                    u.user_id,
                    u.employee_no,
                    u.full_name,
                    u.email,
                    u.mobile,
                    u.status,
                    u.branch_id,
                    b.name AS branch_name,
                    o.organization_id,
                    o.organization_code,
                    o.legal_name AS organization_name,
                    o.currency_code,
                    o.timezone
                FROM users u
                JOIN organizations o ON u.organization_id = o.organization_id
                LEFT JOIN branches b ON u.branch_id = b.branch_id
                WHERE u.status = 'ACTIVE'
                ORDER BY u.created_at
                LIMIT 1
                """
            )

    if not user:
        return None

    user_dict = dict(user)

    # Fetch roles
    roles = await conn.fetch(
        """
        SELECT r.role_id, r.role_code, r.name
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.role_id
        WHERE ur.user_id = $1
        ORDER BY r.name
        """,
        user["user_id"]
    )
    user_dict["roles"] = [dict(r) for r in roles]
    role_codes = [r["role_code"] for r in roles]
    user_dict["role_codes"] = role_codes

    # Fetch effective permissions
    permissions = await conn.fetch(
        """
        SELECT DISTINCT p.permission_id, p.code, p.name
        FROM user_roles ur
        JOIN role_permissions rp ON ur.role_id = rp.role_id
        JOIN permissions p ON rp.permission_id = p.permission_id
        WHERE ur.user_id = $1
        ORDER BY p.code
        """,
        user["user_id"]
    )
    user_dict["permissions"] = [dict(p) for p in permissions]
    user_dict["permission_codes"] = [p["code"] for p in permissions]

    # Effective data scope
    user_dict["effective_scope"] = resolve_user_data_scope(role_codes)

    return user_dict

@router.get("/me", response_model=ResponseEnvelope[Dict[str, Any]])
@router.get("/auth/me", response_model=ResponseEnvelope[Dict[str, Any]])
async def get_current_user_profile(
    user_id: Optional[str] = Query(None, description="Optional user ID to switch active context (default: user-51)"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    target_id = user_id or x_user_id
    profile = await _fetch_user_profile(conn, target_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Active user profile not found")
    return ResponseEnvelope(data=profile, meta=BaseMeta())

@router.get("/auth/users", response_model=ResponseEnvelope[List[Dict[str, Any]]])
async def list_available_auth_users(conn: asyncpg.Connection = Depends(get_db)):
    rows = await conn.fetch(
        """
        SELECT 
            u.user_id,
            u.employee_no,
            u.full_name,
            u.email,
            u.mobile,
            u.status,
            u.branch_id,
            b.name AS branch_name,
            array_agg(r.role_code) as roles
        FROM users u
        LEFT JOIN branches b ON u.branch_id = b.branch_id
        LEFT JOIN user_roles ur ON u.user_id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.role_id
        WHERE u.status = 'ACTIVE'
        GROUP BY u.user_id, u.employee_no, u.full_name, u.email, u.mobile, u.status, u.branch_id, b.name
        ORDER BY CASE WHEN u.user_id = 'user-51' THEN 0 ELSE 1 END, u.user_id
        """
    )
    return ResponseEnvelope(data=[dict(r) for r in rows], meta=BaseMeta())
