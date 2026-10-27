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

