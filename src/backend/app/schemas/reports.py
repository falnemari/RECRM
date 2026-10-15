from typing import Dict, Any, List, Optional
from pydantic import BaseModel

class ExecutiveKPIs(BaseModel):
    total_leads: int
    active_leads: int
    total_customers: int
    total_units: int
    available_units: int
    rented_units: int
    total_opportunities: int
    active_pipeline_value: float
    total_tenancies: int
    active_tenancies: int
    open_tickets: int
    total_rent_due: float
    total_rent_collected: float

class StatusBreakdown(BaseModel):
    status: str
    count: int

class ExecutiveDashboard(BaseModel):
    kpis: ExecutiveKPIs
    leads_by_status: List[StatusBreakdown]
    units_by_status: List[StatusBreakdown]
    opportunities_by_stage: List[StatusBreakdown]


# ==========================================
# Multi-Tier Funnel & Drill-down Dashboard
# ==========================================
class FunnelKPIs(BaseModel):
    total_leads: int
    new_leads: int
    qualified_leads: int
    open_opportunities: int
    viewings: int
    offers: int
    reservations: int
    contracts: int
    sales_value: float
    pending_payments: float

class ScopeInfo(BaseModel):
    scope: str
    branch_id: Optional[str] = None
    branch_name: Optional[str] = None
    user_id: Optional[str] = None
    user_name: Optional[str] = None

class BranchFunnelItem(BaseModel):
    branch_id: str
    branch_code: str
    name: str
    agents_count: int
    leads_count: int
    open_opps: int
    viewings_count: int = 0
    contracts_count: int
    sales_value: float

class AgentFunnelItem(BaseModel):
    user_id: str
    full_name: str
    employee_no: Optional[str] = None
    branch_id: Optional[str] = None
    branch_name: Optional[str] = None
    leads_count: int
    open_opps: int
    viewings_count: int
    contracts_count: int
    sales_value: float

class OpportunityFunnelItem(BaseModel):
    opportunity_id: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_mobile: Optional[str] = None
    stage: str
    expected_value: float
    agent_name: Optional[str] = None
    unit_id: Optional[str] = None
    unit_number: Optional[str] = None
    building_name: Optional[str] = None
    project_name: Optional[str] = None
    created_at: Any = None

class LivePulseEvent(BaseModel):
    id: str
    event_type: str  # ACTIVITY, TASK, COMMUNICATION, LEAD_UPDATE
    title: str
    description: str
    occurred_at: Any
    actor_name: Optional[str] = None
    lead_id: Optional[str] = None
    customer_name: Optional[str] = None

class DrilldownData(BaseModel):
    branches: List[BranchFunnelItem] = []
    agents: List[AgentFunnelItem] = []
    opportunities: List[OpportunityFunnelItem] = []

class MultiTierDashboardOut(BaseModel):
    kpis: FunnelKPIs
    scope_info: ScopeInfo
    drilldown: DrilldownData
    live_pulse: List[LivePulseEvent]

