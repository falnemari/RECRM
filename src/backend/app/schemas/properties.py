from datetime import datetime, date
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field

class ProjectOut(BaseModel):
    project_id: str
    organization_id: str
    name_ar: str
    name_en: str
    city_name: Optional[str] = None
    status: str
    start_date: Optional[date] = None
    completion_date: Optional[date] = None

class ProjectCreateIn(BaseModel):
    name_ar: str
    name_en: str
    city_id: Optional[str] = None
    status: Optional[str] = "ACTIVE"
    developer_customer_id: Optional[str] = None
    start_date: Optional[date] = None
    completion_date: Optional[date] = None

class BuildingCreateIn(BaseModel):
    project_id: str
    building_code: str
    name: Optional[str] = None
    floors_count: Optional[int] = None

class UnitOut(BaseModel):
    unit_id: str
    building_id: str
    project_id: Optional[str] = None
    project_name_ar: Optional[str] = None
    project_name_en: Optional[str] = None
    unit_number: str
    floor_no: Optional[int] = None
    area_sqm: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    parking_spaces: Optional[int] = None
    orientation: Optional[str] = None
    property_type_id: Optional[str] = None
    property_type_name: Optional[str] = None
    property_type_name_en: Optional[str] = None
    property_type_name_ar: Optional[str] = None
    asking_price: Optional[float] = None
    rent_price: Optional[float] = None
    status: str
    owner_customer_id: Optional[str] = None
    owner_name: Optional[str] = None
    owner_mobile: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class UnitCreateIn(BaseModel):
    building_id: str
    unit_number: str
    property_type_id: Optional[str] = None
    floor_no: Optional[int] = None
    area_sqm: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    parking_spaces: Optional[int] = None
    orientation: Optional[str] = None
    asking_price: Optional[float] = None
    rent_price: Optional[float] = None
    status: Optional[str] = "AVAILABLE"
    owner_customer_id: Optional[str] = None
    assigned_user_id: Optional[str] = None

class UnitUpdateIn(BaseModel):
    building_id: Optional[str] = None
    unit_number: Optional[str] = None
    property_type_id: Optional[str] = None
    floor_no: Optional[int] = None
    area_sqm: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    parking_spaces: Optional[int] = None
    orientation: Optional[str] = None
    asking_price: Optional[float] = None
    rent_price: Optional[float] = None
    status: Optional[str] = None
    owner_customer_id: Optional[str] = None
    assigned_user_id: Optional[str] = None

class BuildingOut(BaseModel):
    building_id: str
    project_id: str
    project_name_ar: Optional[str] = None
    project_name_en: Optional[str] = None
    building_code: str
    building_name: Optional[str] = None
    floors_count: Optional[int] = None

class UnitStatusUpdate(BaseModel):
    status: str
    reason: Optional[str] = None

class UnitSearchCriteria(BaseModel):
    city_id: Optional[str] = None
    property_type_id: Optional[str] = None
    status: Optional[str] = None
    bedrooms: Optional[int] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_area: Optional[float] = None

