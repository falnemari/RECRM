from datetime import datetime, date
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field

class ManagementSummaryOut(BaseModel):
    active_tenancies: int
    total_active_rent_amount: float
    open_maintenance_tickets: int
    overdue_rent_collections: int
    total_vendors: int
    active_management_contracts: int

class TenancyOut(BaseModel):
    tenancy_id: str
    unit_id: str
    unit_number: Optional[str] = None
    tenant_customer_id: str
    tenant_name: Optional[str] = None
    tenant_mobile: Optional[str] = None
    contract_number: str
    start_date: date
    end_date: Optional[date] = None
    rent_amount: float
    payment_frequency: Optional[str] = None
    deposit_amount: Optional[float] = None
    status: str

class TenancyCreateIn(BaseModel):
    unit_id: str
    tenant_customer_id: str
    contract_number: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    rent_amount: float = Field(..., gt=0)
    payment_frequency: Optional[str] = "ANNUAL"
    deposit_amount: Optional[float] = 0.0
    status: Optional[str] = "ACTIVE"
    generate_installments: Optional[bool] = True
    installments_count: Optional[int] = Field(1, ge=1, le=12)
    lead_id: Optional[str] = None
    opportunity_id: Optional[str] = None

class RentCollectionOut(BaseModel):
    rent_collection_id: str
    tenancy_id: str
    contract_number: Optional[str] = None
    unit_number: Optional[str] = None
    tenant_name: Optional[str] = None
    due_date: date
    amount_due: float
    amount_paid: float
    paid_at: Optional[datetime] = None
    status: str

class RentCollectionCreateIn(BaseModel):
    tenancy_id: str
    due_date: date
    amount_due: float = Field(..., gt=0)

class RentCollectionPaymentIn(BaseModel):
    amount_paid: float = Field(..., gt=0)

class MaintenanceTicketOut(BaseModel):
    ticket_id: str
    unit_id: str
    unit_number: Optional[str] = None
    reported_by_customer_id: Optional[str] = None
    reported_by_name: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None
    priority: str
    category: Optional[str] = None
    description: str
    opened_at: datetime
    due_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    status: str
    work_orders_count: Optional[int] = 0

class MaintenanceTicketCreateIn(BaseModel):
    unit_id: str
    reported_by_customer_id: Optional[str] = None
    assigned_user_id: Optional[str] = None
    priority: Optional[str] = "NORMAL"
    category: Optional[str] = "GENERAL"
    description: str = Field(..., min_length=3)
    due_at: Optional[datetime] = None

class MaintenanceTicketUpdateIn(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_user_id: Optional[str] = None
    category: Optional[str] = None
    closed_at: Optional[datetime] = None

class VendorOut(BaseModel):
    vendor_id: str
    organization_id: str
    vendor_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    tax_number: Optional[str] = None
    status: str
    work_orders_count: Optional[int] = 0

class VendorCreateIn(BaseModel):
    vendor_name: str = Field(..., min_length=2)
    phone: Optional[str] = None
    email: Optional[str] = None
    tax_number: Optional[str] = None
    status: Optional[str] = "ACTIVE"

class WorkOrderOut(BaseModel):
    work_order_id: str
    ticket_id: str
    ticket_description: Optional[str] = None
    unit_number: Optional[str] = None
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None
    quoted_amount: Optional[float] = None
    approved_amount: Optional[float] = None
    completed_at: Optional[datetime] = None
    status: str

class WorkOrderCreateIn(BaseModel):
    ticket_id: str
    vendor_id: Optional[str] = None
    assigned_user_id: Optional[str] = None
    quoted_amount: Optional[float] = None
    approved_amount: Optional[float] = None
    status: Optional[str] = "REQUESTED"

class WorkOrderUpdateIn(BaseModel):
    status: Optional[str] = None
    approved_amount: Optional[float] = None
    completed_at: Optional[datetime] = None

class ManagementContractOut(BaseModel):
    management_contract_id: str
    customer_id: str
    owner_name: Optional[str] = None
    contract_number: str
    start_date: date
    end_date: Optional[date] = None
    fee_type: str
    fee_rate: Optional[float] = None
    status: str
    managed_units_count: Optional[int] = 0

class ManagementContractCreateIn(BaseModel):
    customer_id: str
    contract_number: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    fee_type: Optional[str] = "PERCENT"
    fee_rate: Optional[float] = 5.0
    unit_ids: Optional[List[str]] = []
    status: Optional[str] = "ACTIVE"
