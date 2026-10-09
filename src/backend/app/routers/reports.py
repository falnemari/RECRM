from typing import List, Dict, Any
from fastapi import APIRouter, Depends
import asyncpg
from app.database import get_db
from app.schemas.common import ResponseEnvelope, BaseMeta
from app.schemas.reports import ExecutiveDashboard, ExecutiveKPIs, StatusBreakdown

router = APIRouter(prefix="/reports", tags=["Reports & Dashboards"])

@router.get("/executive", response_model=ResponseEnvelope[ExecutiveDashboard])
async def get_executive_report(conn: asyncpg.Connection = Depends(get_db)):
    # 1. Total & active leads
    total_leads = await conn.fetchval("SELECT count(*) FROM leads")
    active_leads = await conn.fetchval("SELECT count(*) FROM leads WHERE status NOT IN ('CONVERTED', 'LOST', 'DISQUALIFIED')")

    # 2. Total customers
    total_customers = await conn.fetchval("SELECT count(*) FROM customers")

    # 3. Units
    total_units = await conn.fetchval("SELECT count(*) FROM units")
    available_units = await conn.fetchval("SELECT count(*) FROM units WHERE status = 'AVAILABLE'")
    rented_units = await conn.fetchval("SELECT count(*) FROM units WHERE status = 'RENTED'")

    # 4. Pipeline
    total_opps = await conn.fetchval("SELECT count(*) FROM opportunities")
    pipeline_val = await conn.fetchval("SELECT COALESCE(SUM(expected_value), 0) FROM opportunities WHERE stage NOT IN ('CLOSED_WON', 'CLOSED_LOST')")

    # 5. Tenancies
    total_tenancies = await conn.fetchval("SELECT count(*) FROM tenancies")
    active_tenancies = await conn.fetchval("SELECT count(*) FROM tenancies WHERE status = 'ACTIVE'")

    # 6. Maintenance
    open_tickets = await conn.fetchval("SELECT count(*) FROM maintenance_tickets WHERE status NOT IN ('RESOLVED', 'CLOSED')")

    # 7. Collections
    rent_due = await conn.fetchval("SELECT COALESCE(SUM(amount_due), 0) FROM rent_collections")
    rent_collected = await conn.fetchval("SELECT COALESCE(SUM(amount_paid), 0) FROM rent_collections")

    kpis = ExecutiveKPIs(
        total_leads=total_leads,
        active_leads=active_leads,
        total_customers=total_customers,
        total_units=total_units,
        available_units=available_units,
        rented_units=rented_units,
        total_opportunities=total_opps,
        active_pipeline_value=float(pipeline_val),
        total_tenancies=total_tenancies,
        active_tenancies=active_tenancies,
        open_tickets=open_tickets,
        total_rent_due=float(rent_due),
        total_rent_collected=float(rent_collected)
    )

    # Breakdowns
    lead_rows = await conn.fetch("SELECT status, count(*) AS count FROM leads GROUP BY status ORDER BY count DESC")
    leads_by_status = [StatusBreakdown(status=r["status"], count=r["count"]) for r in lead_rows]

    unit_rows = await conn.fetch("SELECT status, count(*) AS count FROM units GROUP BY status ORDER BY count DESC")
    units_by_status = [StatusBreakdown(status=r["status"], count=r["count"]) for r in unit_rows]

    opp_rows = await conn.fetch("SELECT stage AS status, count(*) AS count FROM opportunities GROUP BY stage ORDER BY count DESC")
    opps_by_stage = [StatusBreakdown(status=r["status"], count=r["count"]) for r in opp_rows]

    dashboard = ExecutiveDashboard(
        kpis=kpis,
        leads_by_status=leads_by_status,
        units_by_status=units_by_status,
        opportunities_by_stage=opps_by_stage
    )

    return ResponseEnvelope(data=dashboard, meta=BaseMeta())

