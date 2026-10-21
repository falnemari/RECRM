from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, Query, Header, HTTPException, status
import asyncpg
from app.database import get_db
from app.schemas.common import ResponseEnvelope, BaseMeta

router = APIRouter(tags=["Authentication & Session"])

def resolve_user_data_scope(role_codes: List[str]) -> str:
    codes = set(r.upper() for r in role_codes)
    # 1. Executive and organization-wide governance roles have global visibility
    if any(r in codes for r in ("SYS_ADMIN", "ADMIN", "GENERAL_MANAGER", "AUDITOR", "VIEWER")):
        return "GLOBAL"
    # 2. Branch sales managers oversee their branch pipeline
    if any(r in codes for r in ("SALES_MANAGER", "BRANCH_MANAGER")):
        return "BRANCH"
    # 3. Organization-wide functional specialists (Marketing & Central Finance)
    if any(r in codes for r in ("MARKETING", "ACCOUNTANT")):
        return "GLOBAL"
    # 4. Regional / Team directors
    if "SALES_DIRECTOR" in codes:
        return "TEAM"
    # 5. Branch operations (Property Managers & Document Controllers)
    if any(r in codes for r in ("PROPERTY_MANAGER", "DOCUMENT_CONTROL")):
        return "BRANCH"
    # 6. Frontline individual agents (isolated to their own records)
    if any(r in codes for r in ("SALES_AGENT", "LEASING_AGENT")):
        return "OWN"
    return "GLOBAL"

async def resolve_data_scope_filter(
    conn: asyncpg.Connection,
    x_user_id: Optional[str],
    requested_user_id: Optional[str]
) -> Dict[str, Any]:
    """
    Resolves data scoping considering both the active authenticated user (x_user_id)
    and any requested target user filter (requested_user_id).
    
    Returns a dict with:
      - scope_type: 'GLOBAL' | 'BRANCH' | 'OWN' | 'ALL'
      - branch_id: Optional[str]
      - user_id: Optional[str]
      - organization_id: Optional[str]
    """
    active_row = None
    if x_user_id:
        active_row = await conn.fetchrow(
            """
            SELECT u.user_id, u.branch_id, u.organization_id, array_agg(r.role_code) as roles
            FROM users u
            LEFT JOIN user_roles ur ON u.user_id = ur.user_id
            LEFT JOIN roles r ON ur.role_id = r.role_id
            WHERE u.user_id = $1
            GROUP BY u.user_id, u.branch_id, u.organization_id
            """,
            x_user_id
        )

    target_row = None
    if requested_user_id and requested_user_id.strip():
        target_row = await conn.fetchrow(
            """
            SELECT u.user_id, u.branch_id, u.organization_id, array_agg(r.role_code) as roles
            FROM users u
            LEFT JOIN user_roles ur ON u.user_id = ur.user_id
            LEFT JOIN roles r ON ur.role_id = r.role_id
            WHERE u.user_id = $1
            GROUP BY u.user_id, u.branch_id, u.organization_id
            """,
            requested_user_id.strip()
        )

    # 1. If active user has 'OWN' scope (e.g. SALES_AGENT), they are strictly isolated to their own records
    if active_row:
        active_roles = [r for r in (active_row["roles"] or []) if r]
        active_scope = resolve_user_data_scope(active_roles)
        if active_scope == "OWN":
            return {
                "scope_type": "OWN",
                "user_id": x_user_id,
                "branch_id": active_row["branch_id"],
                "organization_id": active_row["organization_id"]
            }

    # 2. If a specific target user filter was requested:
    if target_row:
        target_roles = [r for r in (target_row["roles"] or []) if r]

        # General Manager / SysAdmin: encompasses the whole organization
        if any(r in ("SYS_ADMIN", "GENERAL_MANAGER", "ADMIN") for r in target_roles):
            return {
                "scope_type": "GLOBAL",
                "user_id": target_row["user_id"],
                "branch_id": target_row["branch_id"],
                "organization_id": target_row["organization_id"]
            }

        # Branch Manager: encompasses their entire branch
        if any(r in ("SALES_MANAGER", "BRANCH_MANAGER") for r in target_roles):
            return {
                "scope_type": "BRANCH",
                "user_id": target_row["user_id"],
                "branch_id": target_row["branch_id"],
                "organization_id": target_row["organization_id"]
            }

        # All other individual staff (agents, accountants, document control, etc.): isolated to that user
        return {
            "scope_type": "OWN",
            "user_id": target_row["user_id"],
            "branch_id": target_row["branch_id"],
            "organization_id": target_row["organization_id"]
        }

    # 3. If no target user filter was requested, respect the active user's scope:
    if active_row:
        active_roles = [r for r in (active_row["roles"] or []) if r]
        active_scope = resolve_user_data_scope(active_roles)

        if active_scope == "BRANCH":
            return {
                "scope_type": "BRANCH",
                "user_id": active_row["user_id"],
                "branch_id": active_row["branch_id"],
                "organization_id": active_row["organization_id"]
            }

        return {
            "scope_type": "GLOBAL",
            "user_id": active_row["user_id"],
            "branch_id": active_row["branch_id"],
            "organization_id": active_row["organization_id"]
        }

    # Default fallback: Unrestricted Global
    return {
        "scope_type": "ALL",
        "user_id": None,
        "branch_id": None,
        "organization_id": None
    }

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
    scope_info = await resolve_data_scope_filter(conn, x_user_id, requested_assigned_user_id)
    if scope_info["scope_type"] == "OWN":
        return scope_info["user_id"]
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
            b.branch_code AS branch_code,
            array_remove(array_agg(DISTINCT r.name), NULL) as role_names,
            array_remove(array_agg(DISTINCT r.role_code), NULL) as roles
        FROM users u
        LEFT JOIN branches b ON u.branch_id = b.branch_id
        LEFT JOIN user_roles ur ON u.user_id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.role_id
        WHERE u.status = 'ACTIVE'
        GROUP BY u.user_id, u.employee_no, u.full_name, u.email, u.mobile, u.status, u.branch_id, b.name, b.branch_code
        ORDER BY CASE WHEN u.user_id = 'user-51' THEN 0 ELSE 1 END, b.branch_code, u.full_name
        """
    )
    result = []
    for r in rows:
        d = dict(r)
        d["effective_scope"] = resolve_user_data_scope(d.get("roles") or [])
        result.append(d)
    return ResponseEnvelope(data=result, meta=BaseMeta())
