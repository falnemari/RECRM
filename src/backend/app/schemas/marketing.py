from datetime import datetime, date
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field

class ChannelMetric(BaseModel):
    channel: str
    campaigns_count: int
    total_budget: float
    total_leads: int
    qualified_leads: int

class MarketingSummaryOut(BaseModel):
    total_campaigns: int
    active_campaigns: int
    total_budget: float
    total_leads_captured: int
    qualified_leads_count: int
    overall_conversion_rate: float
    channel_breakdown: List[ChannelMetric]

class CampaignOut(BaseModel):
    campaign_id: UUID
    organization_id: UUID
    name: str
    channel: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = 0.0
    status: str
    leads_count: int = 0
    qualified_leads_count: int = 0
    lost_leads_count: int = 0
    conversion_rate: float = 0.0
    cost_per_lead: Optional[float] = None

class CampaignCreateIn(BaseModel):
    name: str = Field(..., min_length=2, description="Campaign name")
    channel: Optional[str] = Field("SOCIAL", description="Marketing channel (SOCIAL, SEARCH, PORTAL, EMAIL)")
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = Field(0.0, ge=0)
    status: Optional[str] = Field("ACTIVE", description="Campaign status (ACTIVE, PAUSED, COMPLETED)")

class CampaignUpdateIn(BaseModel):
    name: Optional[str] = None
    channel: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    budget: Optional[float] = Field(None, ge=0)
    status: Optional[str] = None

class CampaignLeadOut(BaseModel):
    campaign_id: UUID
    campaign_name: Optional[str] = None
    campaign_channel: Optional[str] = None
    lead_id: UUID
    captured_at: datetime
    customer_id: Optional[UUID] = None
    customer_name: Optional[str] = None
    customer_mobile: Optional[str] = None
    customer_email: Optional[str] = None
    lead_status: Optional[str] = None
    lead_priority: Optional[str] = None
    inquiry_type: Optional[str] = None
    assigned_agent_name: Optional[str] = None

class CampaignLeadAttachIn(BaseModel):
    lead_id: UUID
    captured_at: Optional[datetime] = None

class LeadEventOut(BaseModel):
    lead_event_id: UUID
    lead_id: UUID
    event_type: str
    event_at: datetime
    metadata_json: Optional[Dict[str, Any]] = None
    customer_name: Optional[str] = None
    customer_mobile: Optional[str] = None
    lead_status: Optional[str] = None
    campaign_name: Optional[str] = None

class LeadEventCreateIn(BaseModel):
    lead_id: Optional[UUID] = None
    event_type: str = Field(..., min_length=2, description="Type of event (CONTACTED, STATUS_CHANGED, VIEWED_LISTING, CREATED, NOTE_ADDED)")
    event_at: Optional[datetime] = None
    metadata_json: Optional[Dict[str, Any]] = None

