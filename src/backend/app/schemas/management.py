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
    total_managed_units: Optional[int] = 0
    occupancy_rate: Optional[float] = 0.0
    total_yield_distributed: Optional[float] = 0.0
    pending_owner_payouts: Optional[float] = 0.0

class TenancyOut(BaseModel):
    tenancy_id: str
    unit_id: str
    unit_number: Optional[str] = None
    tenant_customer_id: str
    tenant_name: Optional[str] = None
    tenant_mobile: Optional[str] = None
    contract_number: str
    ejar_contract_number: Optional[str] = None
    ejar_status: Optional[str] = "ACTIVE"
    contract_type: Optional[str] = "RESIDENTIAL"
    start_date: date
    end_date: Optional[date] = None
    rent_amount: float
    payment_frequency: Optional[str] = None
    deposit_amount: Optional[float] = None
    security_deposit_status: Optional[str] = "HELD"
    status: str

class TenancyCreateIn(BaseModel):
    unit_id: str
    tenant_customer_id: str
    contract_number: Optional[str] = None
    ejar_contract_number: Optional[str] = None
    ejar_status: Optional[str] = "ACTIVE"
    contract_type: Optional[str] = "RESIDENTIAL"
    start_date: date
    end_date: Optional[date] = None
    rent_amount: float = Field(..., gt=0)
    payment_frequency: Optional[str] = "ANNUAL"
    deposit_amount: Optional[float] = 0.0
    security_deposit_status: Optional[str] = "HELD"
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
    cost_bearer: Optional[str] = "OWNER"
    quoted_amount: Optional[float] = None
    approved_amount: Optional[float] = None
    vat_amount: Optional[float] = 0.0
    total_amount: Optional[float] = 0.0
    invoice_ref: Optional[str] = None
    notes: Optional[str] = None
    completed_at: Optional[datetime] = None
    status: str

class WorkOrderCreateIn(BaseModel):
    ticket_id: str
    vendor_id: Optional[str] = None
    assigned_user_id: Optional[str] = None
    cost_bearer: Optional[str] = "OWNER"
    quoted_amount: Optional[float] = None
    approved_amount: Optional[float] = None
    vat_amount: Optional[float] = None
    total_amount: Optional[float] = None
    invoice_ref: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = "REQUESTED"

class WorkOrderUpdateIn(BaseModel):
    status: Optional[str] = None
    cost_bearer: Optional[str] = None
    approved_amount: Optional[float] = None
    vat_amount: Optional[float] = None
    total_amount: Optional[float] = None
    invoice_ref: Optional[str] = None
    notes: Optional[str] = None
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

class OwnerYieldDistributionOut(BaseModel):
    distribution_id: str
    management_contract_id: str
    contract_number: Optional[str] = None
    owner_customer_id: str
    owner_name: Optional[str] = None
    owner_mobile: Optional[str] = None
    period_start: date
    period_end: date
    gross_rent_collected: float
    management_fee_rate: float
    management_fee_amount: float
    maintenance_expenses_deducted: float
    other_deductions: float
    net_yield_amount: float
    status: str
    payment_reference: Optional[str] = None
    bank_name: Optional[str] = None
    iban: Optional[str] = None
    paid_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: datetime

class OwnerYieldCalculationPreviewOut(BaseModel):
    management_contract_id: str
    owner_customer_id: str
    owner_name: str
    contract_number: str
    period_start: date
    period_end: date
    fee_type: str
    management_fee_rate: float
    managed_units_count: int
    gross_rent_collected: float
    rent_collections_count: int
    management_fee_amount: float
    maintenance_expenses_deducted: float
    work_orders_count: int
    other_deductions: float
    net_yield_amount: float
    units_breakdown: List[dict] = []

class OwnerYieldDistributionCalculateIn(BaseModel):
    management_contract_id: str
    period_start: date
    period_end: date
    other_deductions: Optional[float] = 0.0

class OwnerYieldDistributionCreateIn(BaseModel):
    management_contract_id: str
    period_start: date
    period_end: date
    other_deductions: Optional[float] = 0.0
    notes: Optional[str] = None

class OwnerYieldDistributionPayoutIn(BaseModel):
    payment_reference: str
    bank_name: Optional[str] = None
    iban: Optional[str] = None
    paid_at: Optional[datetime] = None
    notes: Optional[str] = None
