from typing import Dict, Any
from fastapi import APIRouter, Depends
import asyncpg
from app.database import get_db
from app.schemas.common import ResponseEnvelope, BaseMeta

router = APIRouter(tags=["Authentication & Session"])

@router.get("/me", response_model=ResponseEnvelope[Dict[str, Any]])
async def get_current_user_profile(conn: asyncpg.Connection = Depends(get_db)):
    # In full OAuth2/SSO mode, token is decoded. For baseline, we return the primary admin / demo user context.
    user = await conn.fetchrow(
        """
        SELECT 
            u.user_id,
            u.employee_no,
            u.full_name,
            u.email,
            u.mobile,
            u.status,
            o.organization_id,
            o.organization_code,
            o.legal_name AS organization_name,
            o.currency_code,
            o.timezone
        FROM users u
        JOIN organizations o ON u.organization_id = o.organization_id
        WHERE u.status = 'ACTIVE'
        ORDER BY u.created_at
        LIMIT 1
        """
    )
    if not user:
        return ResponseEnvelope(data={}, meta=BaseMeta())

    user_dict = dict(user)
    # Fetch roles
    roles = await conn.fetch(
        """
        SELECT r.role_id, r.role_code, r.name
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.role_id
        WHERE ur.user_id = $1
        """,
        user["user_id"]
    )
    user_dict["roles"] = [dict(r) for r in roles]

    return ResponseEnvelope(data=user_dict, meta=BaseMeta())

