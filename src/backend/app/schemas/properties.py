from datetime import datetime, date
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field

class ProjectOut(BaseModel):
    project_id: UUID
    organization_id: UUID
    name_ar: str
    name_en: str
    city_name: Optional[str] = None
    status: str
    start_date: Optional[date] = None
    completion_date: Optional[date] = None

class UnitOut(BaseModel):
    unit_id: UUID
    building_id: UUID
    project_id: Optional[UUID] = None
    project_name_ar: Optional[str] = None
    project_name_en: Optional[str] = None
    unit_number: str
    floor_no: Optional[int] = None
    area_sqm: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    parking_spaces: Optional[int] = None
    orientation: Optional[str] = None
    property_type_name: Optional[str] = None
    asking_price: Optional[float] = None
    rent_price: Optional[float] = None
    status: str
    owner_customer_id: Optional[UUID] = None
    owner_name: Optional[str] = None
    assigned_user_id: Optional[UUID] = None
    assigned_user_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class UnitStatusUpdate(BaseModel):
    status: str
    reason: Optional[str] = None

class UnitSearchCriteria(BaseModel):
    city_id: Optional[UUID] = None
    property_type_id: Optional[UUID] = None
    status: Optional[str] = None
    bedrooms: Optional[int] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_area: Optional[float] = None

