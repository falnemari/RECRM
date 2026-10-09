from datetime import datetime, date
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field

class OpportunityOut(BaseModel):
    opportunity_id: UUID
    lead_id: Optional[UUID] = None
    customer_id: UUID
    customer_name: Optional[str] = None
    customer_mobile: Optional[str] = None
    assigned_user_id: Optional[UUID] = None
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
    assigned_user_id: Optional[UUID] = None

class ViewingOut(BaseModel):
    viewing_id: UUID
    opportunity_id: UUID
    unit_id: UUID
    unit_number: Optional[str] = None
    customer_name: Optional[str] = None
    scheduled_start: datetime
    scheduled_end: Optional[datetime] = None
    status: str
    feedback: Optional[str] = None

class ReservationOut(BaseModel):
    reservation_id: UUID
    opportunity_id: UUID
    unit_id: UUID
    unit_number: Optional[str] = None
    reservation_number: str
    reserved_at: datetime
    expires_at: Optional[datetime] = None
    deposit_amount: Optional[float] = None
    status: str

