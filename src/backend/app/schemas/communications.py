from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

class TasksSummaryOut(BaseModel):
    open_tasks: int
    overdue_tasks: int
    completed_tasks: int
    total_activities: int
    total_communications: int
    total_viewings: int = 0

class TaskOut(BaseModel):
    task_id: str
    template_id: Optional[str] = None
    title: str
    due_at: Optional[datetime] = None
    priority: str
    status: str
    escalation_level: Optional[int] = 0
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    lead_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    is_overdue: bool = False

class TaskCompleteIn(BaseModel):
    outcome: Optional[str] = "CONNECTED"
    notes: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    preferred_property_type_id: Optional[str] = None
    preferred_city_id: Optional[str] = None
    # Stage B Callback field
    callback_at: Optional[datetime] = None
    # Stage C Property Matching fields
    unit_ids: Optional[list[str]] = None
    # Stage 3 Property Viewing fields
    unit_id: Optional[str] = None
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    viewing_duration_minutes: Optional[int] = 45
    location_notes: Optional[str] = None
    feedback_rating: Optional[str] = None
    offer_amount: Optional[float] = None
    # Rental agreement / tenancy fields
    rent_amount: Optional[float] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    payment_frequency: Optional[str] = "ANNUAL"
    deposit_amount: Optional[float] = None
    installments_count: Optional[int] = 1
    contract_number: Optional[str] = None
    # Investment criteria, baseline & return fields
    target_yield_percent: Optional[float] = None
    investment_horizon_years: Optional[int] = None
    risk_tolerance: Optional[str] = None
    investment_strategy: Optional[str] = None
    purchase_price: Optional[float] = None
    cash_invested: Optional[float] = None
    annual_pre_tax_cash_flow: Optional[float] = None
    annual_operating_expenses: Optional[float] = None
    annual_vacancy_allowance: Optional[float] = None
    acquisition_costs: Optional[float] = None
    monthly_rent_forecast: Optional[float] = None
    actual_rental_income: Optional[float] = None
    actual_expenses: Optional[float] = None

class TaskReopenIn(BaseModel):
    reason: Optional[str] = None

class TaskCreateIn(BaseModel):
    template_id: Optional[str] = None
    title: str = Field(..., min_length=2)
    due_at: Optional[datetime] = None
    priority: Optional[str] = "NORMAL"
    status: Optional[str] = "OPEN"
    assigned_user_id: Optional[str] = None
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None
    opportunity_id: Optional[str] = None

class TaskUpdateIn(BaseModel):
    title: Optional[str] = None
    due_at: Optional[datetime] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assigned_user_id: Optional[str] = None

class ActivityOut(BaseModel):
    activity_id: str
    template_id: Optional[str] = None
    subject: str
    description: Optional[str] = None
    outcome: Optional[str] = None
    activity_type_id: Optional[str] = None
    activity_type_code: Optional[str] = None
    activity_type_name: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    lead_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str

class ActivityCreateIn(BaseModel):
    subject: str = Field(..., min_length=2)
    description: Optional[str] = None
    activity_type_code: Optional[str] = "CALL"
    activity_type_id: Optional[str] = None
    user_id: Optional[str] = None
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: Optional[str] = "COMPLETED"

class CommunicationOut(BaseModel):
    communication_id: str
    channel: str
    direction: str
    external_message_id: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    lead_id: Optional[str] = None
    sent_at: Optional[datetime] = None
    delivery_status: Optional[str] = None

class CommunicationCreateIn(BaseModel):
    channel: str = "WHATSAPP"
    direction: str = "OUTBOUND"
    subject: Optional[str] = None
    body: Optional[str] = None
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None
    sent_at: Optional[datetime] = None
    delivery_status: Optional[str] = "SENT"

