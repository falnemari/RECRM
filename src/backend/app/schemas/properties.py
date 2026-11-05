from datetime import datetime, date
from typing import Optional, List, Any
from uuid import UUID
from pydantic import BaseModel, Field, field_validator, model_validator

class ProjectOut(BaseModel):
    project_id: str
    organization_id: str
    name_ar: str
    name_en: str
    city_name: Optional[str] = None
    city_name_ar: Optional[str] = None
    developer_customer_id: Optional[str] = None
    developer_name: Optional[str] = None
    buildings_count: Optional[int] = 0
    units_count: Optional[int] = 0
    status: str
    start_date: Optional[date] = None
    completion_date: Optional[date] = None
    end_date: Optional[date] = None

class ProjectCreateIn(BaseModel):
    name_ar: str
    name_en: str
    city_id: Optional[str] = None
    status: Optional[str] = "ACTIVE"
    developer_customer_id: Optional[str] = None
    start_date: Optional[date] = None
    completion_date: Optional[date] = None
    end_date: Optional[date] = None

    @field_validator("start_date", "completion_date", "end_date", mode="before")
    @classmethod
    def parse_optional_date(cls, v: Any) -> Optional[date]:
        if v is None or v == "" or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            return date.fromisoformat(v.strip()[:10])
        return v

    @field_validator("developer_customer_id", "city_id", mode="before")
    @classmethod
    def clean_empty_strings(cls, v: Any) -> Optional[str]:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def unify_end_date(self) -> "ProjectCreateIn":
        if self.end_date and not self.completion_date:
            self.completion_date = self.end_date
        elif self.completion_date and not self.end_date:
            self.end_date = self.completion_date
        return self

class BuildingCreateIn(BaseModel):
    project_id: str
    building_code: str
    name: Optional[str] = None
    floors_count: Optional[int] = None

    @field_validator("floors_count", mode="before")
    @classmethod
    def parse_optional_int(cls, v: Any) -> Optional[int]:
        if v is None or v == "" or (isinstance(v, str) and not v.strip()):
            return None
        return int(v)

    @field_validator("name", "building_code", mode="before")
    @classmethod
    def clean_str(cls, v: Any) -> Optional[str]:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v.strip() if isinstance(v, str) else v

class ProjectUpdateIn(BaseModel):
    name_ar: Optional[str] = None
    name_en: Optional[str] = None
    city_id: Optional[str] = None
    status: Optional[str] = None
    developer_customer_id: Optional[str] = None
    start_date: Optional[date] = None
    completion_date: Optional[date] = None
    end_date: Optional[date] = None

    @field_validator("start_date", "completion_date", "end_date", mode="before")
    @classmethod
    def parse_optional_date(cls, v: Any) -> Optional[date]:
        if v is None or v == "" or (isinstance(v, str) and not v.strip()):
            return None
        if isinstance(v, str):
            return date.fromisoformat(v.strip()[:10])
        return v

    @field_validator("developer_customer_id", "city_id", mode="before")
    @classmethod
    def clean_empty_strings(cls, v: Any) -> Optional[str]:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def unify_end_date(self) -> "ProjectUpdateIn":
        if self.end_date is not None and self.completion_date is None:
            self.completion_date = self.end_date
        elif self.completion_date is not None and self.end_date is None:
            self.end_date = self.completion_date
        return self

class BuildingUpdateIn(BaseModel):
    project_id: Optional[str] = None
    building_code: Optional[str] = None
    name: Optional[str] = None
    floors_count: Optional[int] = None

    @field_validator("floors_count", mode="before")
    @classmethod
    def parse_optional_int(cls, v: Any) -> Optional[int]:
        if v is None or v == "" or (isinstance(v, str) and not v.strip()):
            return None
        return int(v)

    @field_validator("name", "building_code", mode="before")
    @classmethod
    def clean_str(cls, v: Any) -> Optional[str]:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v.strip() if isinstance(v, str) else v

class UnitOut(BaseModel):
    unit_id: str
    building_id: Optional[str] = None
    building_name: Optional[str] = None
    building_code: Optional[str] = None
    project_id: Optional[str] = None
    project_name_ar: Optional[str] = None
    project_name_en: Optional[str] = None
    city_id: Optional[str] = None
    city_name: Optional[str] = None
    city_name_ar: Optional[str] = None
    city_name_en: Optional[str] = None
    unit_number: str
    floor_no: Optional[int] = None
    total_floors: Optional[int] = None
    building_floors_count: Optional[int] = None
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
    annual_operating_expenses: Optional[float] = None
    annual_vacancy_rate: Optional[float] = None
    investment_notes: Optional[str] = None
    listing_purpose: Optional[str] = "ALL"
    status: str
    owner_customer_id: Optional[str] = None
    owner_name: Optional[str] = None
    owner_mobile: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class UnitCreateIn(BaseModel):
    project_id: Optional[str] = None
    building_id: Optional[str] = None
    unit_number: str
    property_type_id: Optional[str] = None
    floor_no: Optional[int] = None
    total_floors: Optional[int] = None
    area_sqm: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    parking_spaces: Optional[int] = None
    orientation: Optional[str] = None
    asking_price: Optional[float] = None
    rent_price: Optional[float] = None
    annual_operating_expenses: Optional[float] = None
    annual_vacancy_rate: Optional[float] = None
    investment_notes: Optional[str] = None
    listing_purpose: Optional[str] = "ALL"
    status: Optional[str] = "AVAILABLE"
    owner_customer_id: Optional[str] = None
    assigned_user_id: Optional[str] = None

class UnitUpdateIn(BaseModel):
    project_id: Optional[str] = None
    building_id: Optional[str] = None
    unit_number: Optional[str] = None
    property_type_id: Optional[str] = None
    floor_no: Optional[int] = None
    total_floors: Optional[int] = None
    area_sqm: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    parking_spaces: Optional[int] = None
    orientation: Optional[str] = None
    asking_price: Optional[float] = None
    rent_price: Optional[float] = None
    annual_operating_expenses: Optional[float] = None
    annual_vacancy_rate: Optional[float] = None
    investment_notes: Optional[str] = None
    listing_purpose: Optional[str] = None
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
    units_count: Optional[int] = 0

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

