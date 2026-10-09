from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field, model_validator

class LeadOut(BaseModel):
    lead_id: UUID
    organization_id: UUID
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    customer_mobile: Optional[str] = None
    customer_email: Optional[str] = None
    lead_source_id: Optional[UUID] = None
    lead_source_name: Optional[str] = None
    assigned_user_id: Optional[UUID] = None
    assigned_user_name: Optional[str] = None
    branch_id: Optional[UUID] = None
    status: str
    priority: str
    inquiry_type: str
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    preferred_city_id: Optional[UUID] = None
    preferred_city_name: Optional[str] = None
    preferred_property_type_id: Optional[UUID] = None
    preferred_property_type_name: Optional[str] = None
    bedrooms_min: Optional[int] = None
    area_min_sqm: Optional[float] = None
    first_contact_due_at: Optional[datetime] = None
    first_contact_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

class LeadCreate(BaseModel):
    customer_id: Optional[UUID] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    lead_source_id: Optional[UUID] = None
    assigned_user_id: Optional[UUID] = None
    priority: str = "MEDIUM"
    inquiry_type: str = "BUY"
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    bedrooms_min: Optional[int] = None
    area_min_sqm: Optional[float] = None
    preferred_city_id: Optional[UUID] = None
    preferred_property_type_id: Optional[UUID] = None

    @model_validator(mode="after")
    def validate_budget_order(self):
        if self.budget_min is not None and self.budget_max is not None:
            if self.budget_min > self.budget_max:
                raise ValueError("budget_min must be less than or equal to budget_max")
        if self.bedrooms_min is not None and self.bedrooms_min < 0:
            raise ValueError("bedrooms_min cannot be negative")
        return self

class LeadUpdate(BaseModel):
    customer_id: Optional[UUID] = None
    lead_source_id: Optional[UUID] = None
    assigned_user_id: Optional[UUID] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    inquiry_type: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    bedrooms_min: Optional[int] = None
    area_min_sqm: Optional[float] = None
    preferred_city_id: Optional[UUID] = None
    preferred_property_type_id: Optional[UUID] = None
    first_contact_at: Optional[datetime] = None

class LeadNoteCreate(BaseModel):
    note: str

class LeadNoteOut(BaseModel):
    note_id: UUID
    lead_id: UUID
    created_by_user_id: Optional[UUID] = None
    created_by_user_name: Optional[str] = None
    note: str
    created_at: datetime

