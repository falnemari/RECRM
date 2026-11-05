from datetime import datetime, date
from typing import Optional, Any, Dict, Union, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

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
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    priority: str
    status: str
    escalation_level: Optional[int] = 0
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    lead_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    inquiry_type: Optional[str] = None
    preferred_property_type_id: Optional[str] = None
    preferred_property_type_name: Optional[str] = None
    preferred_property_type_name_ar: Optional[str] = None
    is_overdue: bool = False
    parent_task_id: Optional[str] = None
    lead_budget_max: Optional[float] = None
    opp_expected_value: Optional[float] = None
    opp_stage: Optional[str] = None

class TaskCompleteIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    outcome: Optional[str] = "CONNECTED"
    notes: Optional[str] = None
    assigned_user_id: Optional[str] = None
    branch_id: Optional[str] = None
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
    # Stage E Offer & Negotiation fields
    counter_amount: Optional[float] = None
    negotiated_price: Optional[float] = None
    payment_terms: Optional[str] = None
    # Rental agreement / tenancy fields
    rent_amount: Optional[float] = None
    start_date: Optional[Union[date, datetime, str]] = None
    end_date: Optional[Union[date, datetime, str]] = None
    first_due_date: Optional[Union[date, datetime, str]] = None
    payment_frequency: Optional[str] = "ANNUAL"
    deposit_amount: Optional[float] = None
    installments_count: Optional[int] = 1
    contract_number: Optional[str] = None
    ejar_contract_number: Optional[str] = None
    bank_name: Optional[str] = None
    bank_iban: Optional[str] = None
    bank_beneficiary: Optional[str] = None
    maintenance_terms: Optional[str] = None
    viewing_data: Optional[Dict[str, Any]] = None
    # Investment criteria, baseline & return fields
    target_yield_percent: Optional[float] = None
    investment_horizon_years: Optional[int] = None
    risk_tolerance: Optional[str] = None
    investment_strategy: Optional[str] = None
    purchase_price: Optional[float] = None
    gross_annual_rent: Optional[float] = None
    cash_invested: Optional[float] = None
    annual_pre_tax_cash_flow: Optional[float] = None
    annual_operating_expenses: Optional[float] = None
    annual_vacancy_allowance: Optional[float] = None
    acquisition_costs: Optional[float] = None
    monthly_rent_forecast: Optional[float] = None
    actual_rental_income: Optional[float] = None
    actual_expenses: Optional[float] = None
    # Investment Due Diligence Inspection fields (Technical & Commercial)
    structural_condition: Optional[str] = None
    building_age_years: Optional[int] = None
    saudi_building_code_compliant: Optional[bool] = None
    hvac_status: Optional[str] = None
    elevators_status: Optional[str] = None
    plumbing_network_status: Optional[str] = None
    electrical_network_status: Optional[str] = None
    roofing_and_insulation_status: Optional[str] = None
    fire_safety_compliance: Optional[str] = None
    estimated_capex_sar: Optional[float] = None
    technical_notes: Optional[str] = None
    location_traffic_flow: Optional[str] = None
    access_and_egress_quality: Optional[str] = None
    parking_availability: Optional[str] = None
    actual_occupancy_rate: Optional[float] = None
    occupied_units_count: Optional[int] = None
    vacant_units_count: Optional[int] = None
    rent_roll_verified: Optional[bool] = None
    property_manager_interview_notes: Optional[str] = None
    commercial_viability_score: Optional[int] = None
    commercial_notes: Optional[str] = None
    recommendation: Optional[str] = None
    suggested_price_adjustment_sar: Optional[float] = None
    final_verdict_summary: Optional[str] = None

class TaskReopenIn(BaseModel):
    reason: Optional[str] = None

class TaskCancelIn(BaseModel):
    reason: str = Field("OTHER", description="Cancellation reason: PROPERTY_UNAVAILABLE, CLIENT_WITHDREW, NO_RESPONSE, FINANCE, PRICE, OTHER")
    notes: Optional[str] = None
    cancel_opportunity: Optional[bool] = False
    cascade_cancel_opportunity: Optional[bool] = False

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
    parent_task_id: Optional[str] = None

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
    inquiry_type: Optional[str] = None
    preferred_property_type_id: Optional[str] = None
    preferred_property_type_name: Optional[str] = None
    preferred_property_type_name_ar: Optional[str] = None
    priority: Optional[str] = "NORMAL"
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
    opportunity_id: Optional[str] = None
    inquiry_type: Optional[str] = None
    template_id: Optional[str] = None
    business_cause: Optional[str] = None
    sent_at: Optional[datetime] = None
    delivery_status: Optional[str] = None

class CommunicationCreateIn(BaseModel):
    channel: str = "WHATSAPP"
    direction: str = "OUTBOUND"
    subject: Optional[str] = None
    body: Optional[str] = None
    customer_id: Optional[str] = None
    lead_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    template_id: Optional[str] = None
    sent_at: Optional[datetime] = None
    delivery_status: Optional[str] = "SENT"

# ================= INTERNAL TASK REMINDER MESSAGES (CHATS & PINGS) =================
class InternalPingCreateIn(BaseModel):
    recipient_role: str = Field(..., description="Target role: DIRECT_MANAGER, ACCOUNTANT, PROPERTY_MANAGER, ASSIGNED_AGENT, GENERAL_MANAGER, etc.")
    recipient_user_id: Optional[str] = Field(None, description="Explicit recipient user ID if known")
    context_type: str = Field(..., description="Operational category: TASK, VIEWING, RESERVATION, RENT_COLLECTION, WORK_ORDER, INVOICE, CAMPAIGN, GENERAL")
    context_id: str = Field(..., description="ID of the related record (e.g. TSK-102, CL-504)")
    context_snapshot: dict = Field(default_factory=dict, description="Metadata snapshot of the row")
    message_text: str = Field(..., min_length=2, max_length=2000, description="Ping message text")
    urgency_level: str = Field("NORMAL", description="NORMAL, URGENT, CRITICAL")
    is_archived: bool = Field(False, description="Archive at send time as proof")

class InternalPingOut(BaseModel):
    ping_id: str
    sender_user_id: str
    sender_name: Optional[str] = None
    recipient_role: str
    recipient_user_id: Optional[str] = None
    recipient_name: Optional[str] = None
    context_type: str
    context_id: str
    context_snapshot: dict
    message_text: str
    urgency_level: str
    is_read: bool
    read_at: Optional[datetime] = None
    is_archived: bool
    archived_at: Optional[datetime] = None
    created_at: datetime

class InternalPingsSummary(BaseModel):
    total_count: int
    unread_count: int
    archived_count: int

class InternalPingsInboxOut(BaseModel):
    pings: list[InternalPingOut]
    summary: InternalPingsSummary

class CleanupExpiredPingsOut(BaseModel):
    purged_count: int
    retained_proofs_count: int
    message: str


