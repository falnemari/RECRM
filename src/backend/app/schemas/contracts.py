from datetime import datetime, date
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, model_validator

class PaymentOut(BaseModel):
    payment_id: str
    contract_id: str
    payment_reference: Optional[str] = None
    due_date: Optional[date] = None
    amount_due: float
    amount_paid: float
    remaining_balance: float
    paid_at: Optional[datetime] = None
    method: Optional[str] = None
    status: str
    contract_number: Optional[str] = None
    contract_status: Optional[str] = None
    customer_name: Optional[str] = None
    unit_number: Optional[str] = None

class PaymentCreate(BaseModel):
    due_date: Optional[date] = None
    amount_due: float = Field(..., gt=0)
    payment_reference: Optional[str] = None

class RecordPaymentIn(BaseModel):
    amount: float = Field(..., gt=0)
    method: str = "BANK_TRANSFER"
    payment_reference: Optional[str] = None

class CommissionOut(BaseModel):
    commission_id: str
    contract_id: str
    user_id: str
    user_name: Optional[str] = None
    commission_type: str
    rate: Optional[float] = None
    amount: float
    status: str
    approved_at: Optional[datetime] = None
    paid_at: Optional[datetime] = None
    contract_number: Optional[str] = None
    contract_status: Optional[str] = None
    customer_name: Optional[str] = None
    unit_number: Optional[str] = None

class CommissionCreate(BaseModel):
    user_id: str
    commission_type: str = "SALES"
    rate: Optional[float] = 2.5
    amount: float = Field(..., gt=0)

class ContractOut(BaseModel):
    contract_id: str
    reservation_id: Optional[str] = None
    reservation_number: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_mobile: Optional[str] = None
    unit_id: Optional[str] = None
    unit_number: Optional[str] = None
    owner_customer_id: Optional[str] = None
    unit_owner_name: Optional[str] = None
    unit_owner_mobile: Optional[str] = None
    contract_number: str
    contract_type: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    contract_value: float
    signed_at: Optional[datetime] = None
    status: str
    total_paid: float = 0.0
    outstanding_balance: float = 0.0

class ContractCreate(BaseModel):
    reservation_id: Optional[str] = None
    contract_number: str
    contract_type: str = "SALE"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    contract_value: float = Field(..., gt=0)
    status: str = "SIGNED"

class ConvertReservationIn(BaseModel):
    contract_number: Optional[str] = None
    contract_type: str = "SALE"
    contract_value: Optional[float] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None

class AdvanceContractIn(BaseModel):
    action: str # APPROVE_DRAFT, RECORD_SIGNATURE, COMPLETE_HANDOVER
    notes: Optional[str] = None

class ContractDetailOut(BaseModel):
    contract: ContractOut
    payments: List[PaymentOut] = []
    commissions: List[CommissionOut] = []

class FinanceSummary(BaseModel):
    total_contracts: int
    total_contract_value: float
    total_payments_collected: float
    total_payments_due: float
    outstanding_receivables: float
    total_commissions_amount: float
    paid_commissions_amount: float
    pending_commissions_amount: float

