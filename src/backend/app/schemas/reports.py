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
    opportunity_id: Optional[str] = None
    lead_id: Optional[str] = None
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
    inquiry_type: Optional[str] = None
    item_type: Optional[str] = "OPPORTUNITY"
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

# =====================================================================
# AGENDA CALENDAR SCHEMAS (مفكرة الكاليندر والتقويم التشغيلي)
# =====================================================================
class AgendaCalendarItem(BaseModel):
    event_id: str
    event_type: str  # 'TASK', 'VIEWING', 'RESERVATION', 'RENT_COLLECTION', 'MAINTENANCE', 'CAMPAIGN'
    event_type_label_ar: str
    event_type_label_en: str
    title: str
    event_date: Any
    end_date: Optional[Any] = None
    lead_id: Optional[str] = None
    task_id: Optional[str] = None
    viewing_id: Optional[str] = None
    reservation_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    ticket_id: Optional[str] = None
    work_order_id: Optional[str] = None
    unit_id: Optional[str] = None
    unit_number: Optional[str] = None
    customer_name: Optional[str] = None
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None
    branch_name: Optional[str] = None
    priority: Optional[str] = None
    status: str
    status_label_ar: str
    badge_color: str
    amount: Optional[float] = None

class AgendaCalendarSummary(BaseModel):
    total_events: int = 0
    tasks_count: int = 0
    viewings_count: int = 0
    reservations_count: int = 0
    collections_count: int = 0
    maintenance_count: int = 0
    campaigns_count: int = 0
    overdue_count: int = 0
    today_count: int = 0
    upcoming_count: int = 0

class AgendaCalendarResponse(BaseModel):
    summary: AgendaCalendarSummary
    scope_info: ScopeInfo
    events: List[AgendaCalendarItem]

# =====================================================================
# FINANCIAL SCHEDULE SCHEMAS (مفكرة وجدول المبالغ والتحصيلات)
# =====================================================================
class FinancialScheduleItem(BaseModel):
    item_id: str
    category: str  # 'DEALS_LEADS', 'PROPERTY_MANAGEMENT', 'MARKETING'
    category_label_ar: str
    item_type_code: str  # 'RESERVATION_DEPOSIT', 'INVOICE', 'RENT_COLLECTION', 'MAINTENANCE_ORDER', 'CAMPAIGN_BUDGET'
    item_type: Optional[str] = None  # Alias for item_type_code for frontend compatibility
    item_type_label_ar: str
    item_type_label_en: str
    title: str
    lead_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    ticket_id: Optional[str] = None
    work_order_id: Optional[str] = None
    unit_id: Optional[str] = None
    unit_number: Optional[str] = None
    customer_name: Optional[str] = None
    amount: float
    amount_paid: float
    amount_remaining: float
    collection_status: str  # 'COLLECTED', 'PENDING', 'OVERDUE', 'CANCELLED'
    collection_status_ar: str
    badge_color: str
    due_date: Optional[Any] = None
    collected_at: Optional[Any] = None
    assigned_user_id: Optional[str] = None
    assigned_user_name: Optional[str] = None
    branch_name: Optional[str] = None
    days_overdue: Optional[int] = 0

class FinancialScheduleSummary(BaseModel):
    total_dues_amount: float = 0.0
    total_collected_amount: float = 0.0
    total_pending_amount: float = 0.0
    total_overdue_amount: float = 0.0
    collection_rate_percent: float = 0.0
    deals_leads_count: int = 0
    property_management_count: int = 0
    marketing_count: int = 0
    total_items: int = 0

class FinancialScheduleResponse(BaseModel):
    summary: FinancialScheduleSummary
    scope_info: ScopeInfo
    items: List[FinancialScheduleItem]


