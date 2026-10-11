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
    unit_id: str
    unit_number: Optional[str] = None
    customer_name: Optional[str] = None
    scheduled_start: datetime
    scheduled_end: Optional[datetime] = None
    status: str
    feedback: Optional[str] = None

class ReservationOut(BaseModel):
    reservation_id: str
    opportunity_id: str
    unit_id: str
    unit_number: Optional[str] = None
    reservation_number: str
    reserved_at: datetime
    expires_at: Optional[datetime] = None
    deposit_amount: Optional[float] = None
    status: str

class OfferOut(BaseModel):
    offer_id: str
    opportunity_id: str
    unit_id: str
    unit_number: Optional[str] = None
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

class OpportunityUnitOut(BaseModel):
    opportunity_id: str
    unit_id: str
    unit_number: Optional[str] = None
    is_primary: bool
    offered_price: Optional[float] = None

class OpportunityUnitCreateIn(BaseModel):
    unit_id: str
    is_primary: bool = False
    offered_price: Optional[float] = None


