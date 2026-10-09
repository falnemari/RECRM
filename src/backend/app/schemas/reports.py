from typing import Dict, Any, List
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

