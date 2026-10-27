from datetime import datetime, date
from typing import Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field

class DocumentsSummaryOut(BaseModel):
    total_documents: int
    active_documents: int
    expiring_soon_count: int
    expired_count: int
    total_access_events: int

class DocumentTypeOut(BaseModel):
    document_type_id: str
    code: str
    name: str
    expiry_required: bool

class DocumentOut(BaseModel):
    document_id: str
    organization_id: str
    document_type_id: Optional[str] = None
    document_type_code: Optional[str] = None
    document_type_name: Optional[str] = None
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    unit_id: Optional[str] = None
    unit_number: Optional[str] = None
    contract_id: Optional[str] = None
    contract_number: Optional[str] = None
    lead_id: Optional[str] = None
    lead_number: Optional[str] = None
    opportunity_id: Optional[str] = None
    task_id: Optional[str] = None
    task_title: Optional[str] = None
    notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    file_name: str
    storage_uri: str
    file_hash: Optional[str] = None
    version_no: int
    issued_at: Optional[date] = None
    expires_at: Optional[date] = None
    status: str
    uploaded_by_user_id: Optional[str] = None
    uploaded_by_name: Optional[str] = None
    created_at: datetime
    is_expired: bool = False
    is_expiring_soon: bool = False

class DocumentCreateIn(BaseModel):
    file_name: str = Field(..., min_length=3)
    document_type_code: Optional[str] = "TITLE_DEED"
    document_type_id: Optional[str] = None
    customer_id: Optional[str] = None
    unit_id: Optional[str] = None
    contract_id: Optional[str] = None
    lead_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    task_id: Optional[str] = None
    notes: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    storage_uri: Optional[str] = None
    issued_at: Optional[date] = None
    expires_at: Optional[date] = None
    uploaded_by_user_id: Optional[str] = None
    status: Optional[str] = "ACTIVE"

class DocumentGenerateIn(BaseModel):
    document_type_code: str
    lead_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    task_id: Optional[str] = None
    unit_id: Optional[str] = None
    customer_id: Optional[str] = None
    contract_id: Optional[str] = None
    custom_title: Optional[str] = None
    custom_payload: Optional[Dict[str, Any]] = None

class DocumentAccessLogOut(BaseModel):
    document_access_id: str
    document_id: str
    user_id: str
    user_name: Optional[str] = None
    action: str
    accessed_at: datetime
    ip_address: Optional[str] = None

