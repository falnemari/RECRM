from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# ==========================================
# Branches
# ==========================================
class BranchOut(BaseModel):
    branch_id: str
    organization_id: str
    branch_code: str
    name: str
    city_id: Optional[str] = None
    city_name: Optional[str] = None
    address_line: Optional[str] = None
    phone: Optional[str] = None
    status: str
    users_count: int = 0

class BranchCreateIn(BaseModel):
    branch_code: str
    name: str
    city_id: Optional[str] = None
    address_line: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = "ACTIVE"

class BranchUpdateIn(BaseModel):
    branch_code: Optional[str] = None
    name: Optional[str] = None
    city_id: Optional[str] = None
    address_line: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None


# ==========================================
# Permissions & Roles (RBAC)
# ==========================================
class PermissionOut(BaseModel):
    permission_id: str
    code: str
    name: str
    module: str = "GENERAL"

class RoleOut(BaseModel):
    role_id: str
    organization_id: str
    role_code: str
    name: str
    description: Optional[str] = None
    default_scope: str = "GLOBAL"
    users_count: int = 0
    permissions: List[PermissionOut] = []

class RoleCreateIn(BaseModel):
    role_code: str
    name: str
    description: Optional[str] = None
    default_scope: Optional[str] = "GLOBAL"
    permission_ids: Optional[List[str]] = []

class RoleUpdateIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    default_scope: Optional[str] = None
    permission_ids: Optional[List[str]] = None


# ==========================================
# Users & User-Roles
# ==========================================
class UserRoleBrief(BaseModel):
    role_id: str
    role_code: str
    name: str

class UserOut(BaseModel):
    user_id: str
    organization_id: str
    branch_id: Optional[str] = None
    branch_code: Optional[str] = None
    branch_name: Optional[str] = None
    employee_no: Optional[str] = None
    full_name: str
    email: str
    mobile: Optional[str] = None
    status: str
    manager_user_id: Optional[str] = None
    manager_name: Optional[str] = None
    effective_scope: str = "GLOBAL"
    roles: List[UserRoleBrief] = []
    compensation_type: Optional[str] = "COMMISSION"
    base_salary: Optional[float] = 0.0
    sales_commission_rate: Optional[float] = 25.0
    rent_commission_rate: Optional[float] = 25.0
    sales_fixed_cut: Optional[float] = 0.0
    rent_fixed_cut: Optional[float] = 0.0
    created_at: datetime
    updated_at: datetime

class UserCreateIn(BaseModel):
    full_name: str
    email: str
    mobile: Optional[str] = None
    employee_no: Optional[str] = None
    branch_id: Optional[str] = None
    manager_user_id: Optional[str] = None
    role_ids: Optional[List[str]] = []
    status: Optional[str] = "ACTIVE"
    compensation_type: Optional[str] = "COMMISSION"
    base_salary: Optional[float] = 0.0
    sales_commission_rate: Optional[float] = 25.0
    rent_commission_rate: Optional[float] = 25.0
    sales_fixed_cut: Optional[float] = 0.0
    rent_fixed_cut: Optional[float] = 0.0

class UserUpdateIn(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    employee_no: Optional[str] = None
    branch_id: Optional[str] = None
    manager_user_id: Optional[str] = None
    role_ids: Optional[List[str]] = None
    status: Optional[str] = None
    compensation_type: Optional[str] = None
    base_salary: Optional[float] = None
    sales_commission_rate: Optional[float] = None
    rent_commission_rate: Optional[float] = None
    sales_fixed_cut: Optional[float] = None
    rent_fixed_cut: Optional[float] = None


# ==========================================
# Data Scope
# ==========================================
class DataScopeRule(BaseModel):
    scope_code: str
    name_en: str
    name_ar: str
    description_en: str
    description_ar: str
    level: int
    applicable_roles: List[str]

class UserScopeEvaluationOut(BaseModel):
    user_id: str
    full_name: str
    effective_scope: str
    branch_id: Optional[str] = None
    branch_name: Optional[str] = None
    team_user_ids: List[str] = []
    roles: List[str] = []
    permissions: List[str] = []


# ==========================================
# Audit Logs & Admin Summary
# ==========================================
class AuditLogOut(BaseModel):
    audit_log_id: str
    organization_id: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    entity_type: str
    entity_id: Optional[str] = None
    action: str
    old_value_json: Optional[Any] = None
    new_value_json: Optional[Any] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

class AdminSummaryOut(BaseModel):
    total_branches: int
    total_users: int
    active_users: int
    total_roles: int
    total_permissions: int
    recent_audit_events_count: int
    total_login_events: int = 0
    successful_logins: int = 0
    failed_logins: int = 0


# ==========================================
# Login Events & Authentication
# ==========================================
class LoginEventOut(BaseModel):
    login_event_id: str
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    event_type: str
    ip_address: Optional[str] = None
    occurred_at: datetime
    success: bool

class LoginEventCreateIn(BaseModel):
    user_id: Optional[str] = None
    event_type: str = "LOGIN"
    ip_address: Optional[str] = None
    success: bool = True


# ==========================================
# Organization Profile & Settings
# ==========================================
class OrganizationOut(BaseModel):
    organization_id: str
    organization_code: str
    legal_name: str
    trade_name: Optional[str] = None
    country_code: str
    timezone: str
    currency_code: str
    tax_number: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime

class OrganizationUpdateIn(BaseModel):
    legal_name: Optional[str] = None
    trade_name: Optional[str] = None
    tax_number: Optional[str] = None
    timezone: Optional[str] = None
    currency_code: Optional[str] = None


