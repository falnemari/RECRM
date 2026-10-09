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
    tenancy_id: UUID
    unit_id: UUID
    unit_number: Optional[str] = None
    tenant_customer_id: UUID
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
    unit_id: UUID
    tenant_customer_id: UUID
    contract_number: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    rent_amount: float = Field(..., gt=0)
    payment_frequency: Optional[str] = "ANNUAL"
    deposit_amount: Optional[float] = 0.0
    status: Optional[str] = "ACTIVE"
    generate_installments: Optional[bool] = True
    installments_count: Optional[int] = Field(1, ge=1, le=12)

class RentCollectionOut(BaseModel):
    rent_collection_id: UUID
    tenancy_id: UUID
    contract_number: Optional[str] = None
    unit_number: Optional[str] = None
    tenant_name: Optional[str] = None
    due_date: date
    amount_due: float
    amount_paid: float
    paid_at: Optional[datetime] = None
    status: str

class RentCollectionCreateIn(BaseModel):
    tenancy_id: UUID
    due_date: date
    amount_due: float = Field(..., gt=0)

class RentCollectionPaymentIn(BaseModel):
    amount_paid: float = Field(..., gt=0)

class MaintenanceTicketOut(BaseModel):
    ticket_id: UUID
    unit_id: UUID
    unit_number: Optional[str] = None
    reported_by_customer_id: Optional[UUID] = None
    reported_by_name: Optional[str] = None
    assigned_user_id: Optional[UUID] = None
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
    unit_id: UUID
    reported_by_customer_id: Optional[UUID] = None
    assigned_user_id: Optional[UUID] = None
    priority: Optional[str] = "NORMAL"
    category: Optional[str] = "GENERAL"
    description: str = Field(..., min_length=3)
    due_at: Optional[datetime] = None

class MaintenanceTicketUpdateIn(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_user_id: Optional[UUID] = None
    category: Optional[str] = None
    closed_at: Optional[datetime] = None

class VendorOut(BaseModel):
    vendor_id: UUID
    organization_id: UUID
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
    work_order_id: UUID
    ticket_id: UUID
    ticket_description: Optional[str] = None
    unit_number: Optional[str] = None
    vendor_id: Optional[UUID] = None
    vendor_name: Optional[str] = None
    assigned_user_id: Optional[UUID] = None
    assigned_user_name: Optional[str] = None
    quoted_amount: Optional[float] = None
    approved_amount: Optional[float] = None
    completed_at: Optional[datetime] = None
    status: str

class WorkOrderCreateIn(BaseModel):
    ticket_id: UUID
    vendor_id: Optional[UUID] = None
    assigned_user_id: Optional[UUID] = None
    quoted_amount: Optional[float] = None
    approved_amount: Optional[float] = None
    status: Optional[str] = "REQUESTED"

class WorkOrderUpdateIn(BaseModel):
    status: Optional[str] = None
    approved_amount: Optional[float] = None
    completed_at: Optional[datetime] = None

class ManagementContractOut(BaseModel):
    management_contract_id: UUID
    customer_id: UUID
    owner_name: Optional[str] = None
    contract_number: str
    start_date: date
    end_date: Optional[date] = None
    fee_type: str
    fee_rate: Optional[float] = None
    status: str
    managed_units_count: Optional[int] = 0

class ManagementContractCreateIn(BaseModel):
    customer_id: UUID
    contract_number: Optional[str] = None
    start_date: date
    end_date: Optional[date] = None
    fee_type: Optional[str] = "PERCENT"
    fee_rate: Optional[float] = 5.0
    unit_ids: Optional[List[UUID]] = []
    status: Optional[str] = "ACTIVE"
