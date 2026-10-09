from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field

class TasksSummaryOut(BaseModel):
    open_tasks: int
    overdue_tasks: int
    completed_tasks: int
    total_activities: int
    total_communications: int

class TaskOut(BaseModel):
    task_id: UUID
    title: str
    due_at: Optional[datetime] = None
    priority: str
    status: str
    assigned_user_id: Optional[UUID] = None
    assigned_user_name: Optional[str] = None
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    lead_id: Optional[UUID] = None
    opportunity_id: Optional[UUID] = None
    is_overdue: bool = False

class TaskCreateIn(BaseModel):
    title: str = Field(..., min_length=2)
    due_at: Optional[datetime] = None
    priority: Optional[str] = "NORMAL"
    status: Optional[str] = "OPEN"
    assigned_user_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    opportunity_id: Optional[UUID] = None

class TaskUpdateIn(BaseModel):
    title: Optional[str] = None
    due_at: Optional[datetime] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    assigned_user_id: Optional[UUID] = None

class ActivityOut(BaseModel):
    activity_id: UUID
    subject: str
    description: Optional[str] = None
    activity_type_id: Optional[UUID] = None
    activity_type_code: Optional[str] = None
    activity_type_name: Optional[str] = None
    user_id: Optional[UUID] = None
    user_name: Optional[str] = None
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    lead_id: Optional[UUID] = None
    opportunity_id: Optional[UUID] = None
    scheduled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str

class ActivityCreateIn(BaseModel):
    subject: str = Field(..., min_length=2)
    description: Optional[str] = None
    activity_type_code: Optional[str] = "CALL"
    activity_type_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    customer_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    opportunity_id: Optional[UUID] = None
    scheduled_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: Optional[str] = "COMPLETED"

class CommunicationOut(BaseModel):
    communication_id: UUID
    channel: str
    direction: str
    external_message_id: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    lead_id: Optional[UUID] = None
    sent_at: Optional[datetime] = None
    delivery_status: Optional[str] = None

class CommunicationCreateIn(BaseModel):
    channel: str = "WHATSAPP"
    direction: str = "OUTBOUND"
    subject: Optional[str] = None
    body: Optional[str] = None
    customer_id: Optional[UUID] = None
    lead_id: Optional[UUID] = None
    sent_at: Optional[datetime] = None
    delivery_status: Optional[str] = "SENT"

