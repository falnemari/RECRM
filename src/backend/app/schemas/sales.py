from datetime import datetime, date
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field

class OpportunityOut(BaseModel):
    opportunity_id: str
    lead_id: Optional[str] = None
    customer_id: str
    customer_name: Optional[str] = None
    customer_mobile: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None
    stage: str
    expected_value: Optional[float] = None
    expected_close_date: Optional[date] = None
    inquiry_type: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    bedrooms_min: Optional[int] = None
    area_min_sqm: Optional[float] = None
    preferred_property_type_id: Optional[str] = None
    preferred_property_type_name: Optional[str] = None
    preferred_city_id: Optional[str] = None
    preferred_city_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class OpportunityUpdate(BaseModel):
    stage: Optional[str] = None
    expected_value: Optional[float] = None
    expected_close_date: Optional[date] = None
    assigned_user_id: Optional[str] = None

class OpportunityCreateIn(BaseModel):
    customer_id: str
    lead_id: Optional[str] = None
    assigned_user_id: Optional[str] = None
    stage: Optional[str] = "QUALIFIED"
    expected_value: Optional[float] = 0.0
    expected_close_date: Optional[date] = None

class ViewingOut(BaseModel):
    viewing_id: str
    opportunity_id: str
    lead_id: Optional[str] = None
    unit_id: str
    unit_number: Optional[str] = None
    project_name: Optional[str] = None
    building_name: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    agent_user_id: Optional[str] = None
    agent_user_name: Optional[str] = None
    scheduled_start: datetime
    scheduled_end: Optional[datetime] = None
    status: str
    outcome: Optional[str] = None
    notes: Optional[str] = None
    feedback: Optional[str] = None
    owner_customer_id: Optional[str] = None
    unit_owner_name: Optional[str] = None
    unit_owner_mobile: Optional[str] = None

class ViewingCreateIn(BaseModel):
    unit_id: str
    scheduled_start: datetime
    scheduled_end: Optional[datetime] = None
    opportunity_id: Optional[str] = None
    lead_id: Optional[str] = None
    customer_id: Optional[str] = None
    agent_user_id: Optional[str] = None
    task_id: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = "SCHEDULED"

class ReservationOut(BaseModel):
    reservation_id: str
    opportunity_id: str
    unit_id: str
    unit_number: Optional[str] = None
    owner_customer_id: Optional[str] = None
    unit_owner_name: Optional[str] = None
    unit_owner_mobile: Optional[str] = None
    reservation_number: str
    reserved_at: datetime
    expires_at: Optional[datetime] = None
    deposit_amount: Optional[float] = None
    status: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_mobile: Optional[str] = None
    customer_email: Optional[str] = None
    national_id: Optional[str] = None
    project_name: Optional[str] = None
    building_name: Optional[str] = None
    property_type: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    area_sqm: Optional[float] = None
    floor_no: Optional[int] = None
    asking_price: Optional[float] = None
    agreed_price: Optional[float] = None
    accepted_offer_amount: Optional[float] = None
    offer_id: Optional[str] = None
    unit_status: Optional[str] = None
    assigned_agent_id: Optional[str] = None
    assigned_agent_name: Optional[str] = None
    contract_id: Optional[str] = None
    contract_number: Optional[str] = None
    contract_value: Optional[float] = None

class OfferOut(BaseModel):
    offer_id: str
    opportunity_id: str
    unit_id: str
    customer_id: Optional[str] = None
    unit_number: Optional[str] = None
    unit_status: Optional[str] = None
    owner_customer_id: Optional[str] = None
    unit_owner_name: Optional[str] = None
    unit_owner_mobile: Optional[str] = None
    customer_name: Optional[str] = None
    offer_amount: float
    submitted_at: datetime
    valid_until: Optional[datetime] = None
    status: str

class OfferCreateIn(BaseModel):
    opportunity_id: str
    unit_id: str
    offer_amount: float
    valid_until: Optional[datetime] = None
    status: str = "SUBMITTED"

class OfferUpdateIn(BaseModel):
    offer_amount: Optional[float] = None
    valid_until: Optional[datetime] = None
    status: Optional[str] = None

class OfferDecisionIn(BaseModel):
    decision: str # ACCEPTED, REJECTED, COUNTERED, APPROVED
    counter_amount: Optional[float] = None
    notes: Optional[str] = None

class ReservationCreateIn(BaseModel):
    opportunity_id: str
    unit_id: str
    customer_id: Optional[str] = None
    deposit_amount: Optional[float] = None
    expiry_hours: int = 48
    notes: Optional[str] = None

class ReservationDepositVerifyIn(BaseModel):
    amount_received: float
    payment_method: str = "BANK_TRANSFER"
    payment_reference: Optional[str] = None
    notes: Optional[str] = None

class OpportunityUnitOut(BaseModel):
    opportunity_id: str
    unit_id: str
    unit_number: Optional[str] = None
    owner_customer_id: Optional[str] = None
    unit_owner_name: Optional[str] = None
    unit_owner_mobile: Optional[str] = None
    is_primary: bool
    offered_price: Optional[float] = None

class OpportunityUnitCreateIn(BaseModel):
    unit_id: str
    is_primary: bool = False
    offered_price: Optional[float] = None



