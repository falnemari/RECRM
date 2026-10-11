from datetime import datetime
from typing import Optional, List, Any
from uuid import UUID
from pydantic import BaseModel, Field

class CustomerOut(BaseModel):
    customer_id: str
    organization_id: str
    customer_type: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    full_name: Optional[str] = None
    company_name: Optional[str] = None
    nationality_code: Optional[str] = None
    preferred_language: str
    mobile: Optional[str] = None
    email: Optional[str] = None
    national_id_hash: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime

class CustomerCreate(BaseModel):
    customer_type: str = "INDIVIDUAL"
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    nationality_code: Optional[str] = "SA"
    preferred_language: str = "ar"
    mobile: Optional[str] = None
    email: Optional[str] = None
    national_id: Optional[str] = None

class CustomerUpdate(BaseModel):
    customer_type: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    nationality_code: Optional[str] = None
    preferred_language: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    national_id: Optional[str] = None
    status: Optional[str] = None

class Customer360Out(BaseModel):
    profile: CustomerOut
    leads: List[Any] = []
    opportunities: List[Any] = []
    tenancies: List[Any] = []
    owned_units: List[Any] = []
    tickets: List[Any] = []
