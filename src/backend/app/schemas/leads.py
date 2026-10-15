from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, model_validator

class LeadUnitItem(BaseModel):
    unit_id: str
    unit_number: str
    building_name: Optional[str] = None
    project_name: Optional[str] = None
    unit_price: Optional[float] = None
    bedrooms: Optional[int] = None
    is_primary: bool = False

class LeadOut(BaseModel):
    lead_id: str
    organization_id: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_mobile: Optional[str] = None
    customer_email: Optional[str] = None
    lead_source_id: Optional[str] = None
    lead_source_name: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None
    branch_id: Optional[str] = None
    status: str
    priority: str
    inquiry_type: str
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    preferred_city_id: Optional[str] = None
    preferred_city_name: Optional[str] = None
    preferred_property_type_id: Optional[str] = None
    preferred_property_type_name: Optional[str] = None
    bedrooms_min: Optional[int] = None
    area_min_sqm: Optional[float] = None
    unit_id: Optional[str] = None
    unit_number: Optional[str] = None
    building_name: Optional[str] = None
    project_name: Optional[str] = None
    unit_price: Optional[float] = None
    units: List[LeadUnitItem] = []
    first_contact_due_at: Optional[datetime] = None
    first_contact_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

class LeadCreate(BaseModel):
    customer_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    lead_source_id: Optional[str] = None
    assigned_user_id: Optional[str] = None
    unit_id: Optional[str] = None
    unit_ids: Optional[List[str]] = None
    priority: str = "MEDIUM"
    inquiry_type: str = "BUY"
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    bedrooms_min: Optional[int] = None
    area_min_sqm: Optional[float] = None
    preferred_city_id: Optional[str] = None
    preferred_property_type_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_budget_order(self):
        if self.budget_min is not None and self.budget_max is not None:
            if self.budget_min > self.budget_max:
                raise ValueError("budget_min must be less than or equal to budget_max")
        if self.bedrooms_min is not None and self.bedrooms_min < 0:
            raise ValueError("bedrooms_min cannot be negative")
        return self

class LeadUpdate(BaseModel):
    customer_id: Optional[str] = None
    lead_source_id: Optional[str] = None
    assigned_user_id: Optional[str] = None
    unit_id: Optional[str] = None
    unit_ids: Optional[List[str]] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    inquiry_type: Optional[str] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    bedrooms_min: Optional[int] = None
    area_min_sqm: Optional[float] = None
    preferred_city_id: Optional[str] = None
    preferred_property_type_id: Optional[str] = None
    first_contact_at: Optional[datetime] = None

class LeadNoteCreate(BaseModel):
    note: str

class LeadNoteOut(BaseModel):
    note_id: str
    lead_id: str
    created_by_user_id: Optional[str] = None
    created_by_user_name: Optional[str] = None
    note: str
    created_at: datetime

