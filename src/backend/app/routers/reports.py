from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException, Header
import asyncpg
from app.database import get_db
from app.routers.auth import resolve_user_data_scope
from app.schemas.common import ResponseEnvelope, BaseMeta
from app.schemas.reports import (
    ExecutiveDashboard, ExecutiveKPIs, StatusBreakdown,
    MultiTierDashboardOut, FunnelKPIs, ScopeInfo,
    BranchFunnelItem, AgentFunnelItem, OpportunityFunnelItem,
    LivePulseEvent, DrilldownData,
    AgendaCalendarItem, AgendaCalendarSummary, AgendaCalendarResponse,
    FinancialScheduleItem, FinancialScheduleSummary, FinancialScheduleResponse,
    FinanceDashboardOut, FinanceDashboardKPIs, FinanceInvoiceItem,
    FinanceCommissionItem, FinancePaymentItem, FinanceLedgersData
)
from app.services.calculation_service import CalculationService

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


# =====================================================================
# MULTI-TIER FUNNEL & DRILLDOWN DASHBOARD (GLOBAL / BRANCH / TEAM / OWN)
# =====================================================================
@router.get("/funnel-dashboard", response_model=ResponseEnvelope[MultiTierDashboardOut])
async def get_funnel_dashboard(
    scope: str = Query("GLOBAL", pattern="^(GLOBAL|BRANCH|TEAM|OWN)$"),
    branch_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    Multi-Tier Drill-down Dashboard endpoint covering:
    - 10 Funnel & Financial KPIs: Total Leads, New Leads, Qualified Leads,
      Open Opps, Viewings, Offers, Reservations, Contracts, Sales Value, Pending Payments.
    - Hierarchical Drilldown: Branches -> Agents -> Opportunities (linked with Customer & Unit).
    - Live Operational Pulse: Unified chronological feed of Activities, Tasks, Communications, Lead Updates.
    """
    # Enforce Role-Based Data Isolation on Active User
    user_scope = None
    user_branch = None
    if x_user_id:
        roles_rows = await conn.fetch("""
            SELECT r.role_code FROM user_roles ur
            JOIN roles r ON ur.role_id = r.role_id
            WHERE ur.user_id = $1
        """, x_user_id)
        role_codes = [r["role_code"] for r in roles_rows]
        user_scope = resolve_user_data_scope(role_codes)
        if user_scope == "OWN":
            scope = "OWN"
            user_id = x_user_id
            branch_id = None
        elif user_scope == "BRANCH":
            user_branch = await conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", x_user_id)
            branch_id = user_branch
            if user_id:
                agent_branch = await conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", user_id)
                if agent_branch == user_branch:
                    scope = "OWN"
                else:
                    user_id = None
                    scope = "BRANCH"
            else:
                scope = "BRANCH"
    target_user_ids: Optional[List[str]] = None
    target_branch_id: Optional[str] = branch_id
    branch_name: Optional[str] = None
    user_name: Optional[str] = None

    # 1. Resolve User and Team Hierarchy if applicable
    if user_id:
        u_row = await conn.fetchrow("""
            SELECT u.user_id, u.full_name, u.branch_id, b.name AS branch_name
            FROM users u
            LEFT JOIN branches b ON u.branch_id = b.branch_id
            WHERE u.user_id = $1
        """, user_id)
        if u_row:
            user_name = u_row["full_name"]
            if not target_branch_id:
                target_branch_id = u_row["branch_id"]
                branch_name = u_row["branch_name"]

    if scope == "OWN":
        if not user_id:
            # Fallback to demo default
            user_id = await conn.fetchval("SELECT user_id FROM users WHERE status = 'ACTIVE' ORDER BY user_id ASC LIMIT 1")
        u_row = await conn.fetchrow("SELECT full_name, branch_id FROM users WHERE user_id = $1", user_id)
        user_name = u_row["full_name"] if u_row else user_id
        target_user_ids = [user_id]
        # In OWN scope, standard sales agents see only their own leads
        is_mgr = await conn.fetchval("""
            SELECT 1 FROM user_roles ur JOIN roles r ON ur.role_id = r.role_id 
            WHERE ur.user_id = $1 AND r.role_code IN ('SALES_MANAGER', 'SYS_ADMIN')
        """, user_id)
        if not is_mgr:
            target_branch_id = None

    elif scope == "TEAM":
        if not user_id:
            user_id = await conn.fetchval("SELECT user_id FROM users WHERE status = 'ACTIVE' ORDER BY user_id ASC LIMIT 1")
        team_rows = await conn.fetch("""
            WITH RECURSIVE subordinates AS (
                SELECT user_id FROM users WHERE user_id = $1 OR manager_user_id = $1
                UNION
                SELECT u.user_id FROM users u
                INNER JOIN subordinates s ON s.user_id = u.manager_user_id
            )
            SELECT user_id FROM subordinates
        """, user_id)
        target_user_ids = [tr["user_id"] for tr in team_rows] or [user_id]

    elif scope == "BRANCH":
        if not target_branch_id:
            target_branch_id = await conn.fetchval("SELECT branch_id FROM branches WHERE status = 'ACTIVE' ORDER BY branch_id LIMIT 1")
        b_users = await conn.fetch("SELECT user_id FROM users WHERE branch_id = $1", target_branch_id)
        target_user_ids = [r["user_id"] for r in b_users]
        if not branch_name:
            branch_name = await conn.fetchval("SELECT name FROM branches WHERE branch_id = $1", target_branch_id)

    elif scope == "GLOBAL":
        target_user_ids = None
        target_branch_id = None

    # 2. Compute 10 Funnel KPIs with dynamic scope filtering
    if target_user_ids is not None:
        if scope == "BRANCH" and target_branch_id:
            lead_condition = "(l.branch_id = $2 OR l.assigned_user_id = ANY($1))"
            lead_params = [target_user_ids, target_branch_id]
        elif target_branch_id:
            lead_condition = "(l.assigned_user_id = ANY($1) OR (l.branch_id = $2 AND l.assigned_user_id IS NULL))"
            lead_params = [target_user_ids, target_branch_id]
        else:
            lead_condition = "l.assigned_user_id = ANY($1)"
            lead_params = [target_user_ids]

        total_leads = await conn.fetchval(f"SELECT count(*) FROM leads l WHERE {lead_condition}", *lead_params)
        new_leads = await conn.fetchval(f"SELECT count(*) FROM leads l WHERE l.status = 'NEW' AND {lead_condition}", *lead_params)
        qualified_leads = await conn.fetchval(f"SELECT count(*) FROM leads l WHERE l.status IN ('QUALIFIED', 'CONVERTED', 'WON') AND {lead_condition}", *lead_params)


        # Opportunities
        open_opps = await conn.fetchval("""
            SELECT count(*) FROM opportunities 
            WHERE stage NOT IN ('CLOSED_WON', 'CLOSED_LOST') 
              AND assigned_user_id = ANY($1)
        """, target_user_ids)

        # Viewings (from viewings table)
        v_tbl_cnt = await conn.fetchval("""
            SELECT count(*) FROM viewings 
            WHERE agent_user_id = ANY($1)
        """, target_user_ids) or 0
        if v_tbl_cnt > 0:
            viewings_cnt = v_tbl_cnt
        else:
            viewings_cnt = await conn.fetchval("""
                SELECT count(*) FROM activities a
                JOIN activity_types at ON a.activity_type_id = at.activity_type_id
                WHERE at.code = 'VIEWING' AND a.user_id = ANY($1)
            """, target_user_ids) or 0

        # Offers
        offers_cnt = await conn.fetchval("""
            SELECT count(*) FROM offers ofr
            JOIN opportunities o ON ofr.opportunity_id = o.opportunity_id
            WHERE o.assigned_user_id = ANY($1)
        """, target_user_ids)

        # Reservations (ACTIVE, CONFIRMED, CONVERTED)
        reservations_cnt = await conn.fetchval("""
            SELECT count(*) FROM reservations r
            JOIN opportunities o ON r.opportunity_id = o.opportunity_id
            WHERE r.status IN ('ACTIVE', 'CONFIRMED', 'CONVERTED')
              AND o.assigned_user_id = ANY($1)
        """, target_user_ids)

        # Contracts
        contracts_cnt = await conn.fetchval("""
            SELECT count(*) FROM contracts c
            JOIN reservations r ON c.reservation_id = r.reservation_id
            JOIN opportunities o ON r.opportunity_id = o.opportunity_id
            WHERE c.status IN ('ACTIVE', 'SIGNED')
              AND o.assigned_user_id = ANY($1)
        """, target_user_ids)

        sales_val = await conn.fetchval("""
            SELECT COALESCE(SUM(c.contract_value), 0) FROM contracts c
            JOIN reservations r ON c.reservation_id = r.reservation_id
            JOIN opportunities o ON r.opportunity_id = o.opportunity_id
            WHERE c.status IN ('ACTIVE', 'SIGNED')
              AND o.assigned_user_id = ANY($1)
        """, target_user_ids)

        pending_pay = await conn.fetchval("""
            SELECT COALESCE(SUM(p.amount_due - p.amount_paid), 0) FROM payments p
            JOIN contracts c ON p.contract_id = c.contract_id
            JOIN reservations r ON c.reservation_id = r.reservation_id
            JOIN opportunities o ON r.opportunity_id = o.opportunity_id
            WHERE p.status != 'PAID'
              AND o.assigned_user_id = ANY($1)
        """, target_user_ids)

    else:
        # Full Global Scope (no user filter)
        total_leads = await conn.fetchval("SELECT count(*) FROM leads")
        new_leads = await conn.fetchval("SELECT count(*) FROM leads WHERE status = 'NEW'")
        qualified_leads = await conn.fetchval("SELECT count(*) FROM leads WHERE status IN ('QUALIFIED', 'CONVERTED', 'WON')")
        open_opps = await conn.fetchval("SELECT count(*) FROM opportunities WHERE stage NOT IN ('CLOSED_WON', 'CLOSED_LOST')")
        v_tbl_cnt = await conn.fetchval("SELECT count(*) FROM viewings") or 0
        if v_tbl_cnt > 0:
            viewings_cnt = v_tbl_cnt
        else:
            viewings_cnt = await conn.fetchval("""
                SELECT count(*) FROM activities a
                JOIN activity_types at ON a.activity_type_id = at.activity_type_id
                WHERE at.code = 'VIEWING'
            """) or 0
        offers_cnt = await conn.fetchval("SELECT count(*) FROM offers")
        reservations_cnt = await conn.fetchval("SELECT count(*) FROM reservations WHERE status IN ('ACTIVE', 'CONFIRMED', 'CONVERTED')")
        contracts_cnt = await conn.fetchval("SELECT count(*) FROM contracts WHERE status IN ('ACTIVE', 'SIGNED')")
        sales_val = await conn.fetchval("SELECT COALESCE(SUM(contract_value), 0) FROM contracts WHERE status IN ('ACTIVE', 'SIGNED')")
        pending_pay = await conn.fetchval("SELECT COALESCE(SUM(amount_due - amount_paid), 0) FROM payments WHERE status != 'PAID'")

    kpis = FunnelKPIs(
        total_leads=int(total_leads or 0),
        new_leads=int(new_leads or 0),
        qualified_leads=int(qualified_leads or 0),
        open_opportunities=int(open_opps or 0),
        viewings=int(viewings_cnt or 0),
        offers=int(offers_cnt or 0),
        reservations=int(reservations_cnt or 0),
        contracts=int(contracts_cnt or 0),
        sales_value=float(sales_val or 0),
        pending_payments=float(pending_pay or 0)
    )

    # 3. Drill-down: Branches Summary
    branches_data = []
    if scope != "OWN":
        branch_where = "1=1"
        branch_p = []
        if user_scope == "BRANCH" and user_branch:
            branch_where = "b.branch_id = $1"
            branch_p = [user_branch]
        branch_rows = await conn.fetch(f"""
            SELECT 
                b.branch_id, b.branch_code, b.name,
                (SELECT count(*) FROM users u WHERE u.branch_id = b.branch_id) AS agents_count,
                (SELECT count(*) FROM leads l WHERE l.branch_id = b.branch_id) AS leads_count,
                (SELECT count(*) FROM opportunities o JOIN users u ON o.assigned_user_id = u.user_id WHERE u.branch_id = b.branch_id AND o.stage NOT IN ('CLOSED_WON', 'CLOSED_LOST')) AS open_opps,
                COALESCE(
                    NULLIF((SELECT count(*) FROM viewings v JOIN users u ON v.agent_user_id = u.user_id WHERE u.branch_id = b.branch_id), 0),
                    (SELECT count(*) FROM activities a JOIN activity_types at ON a.activity_type_id = at.activity_type_id JOIN users u ON a.user_id = u.user_id WHERE u.branch_id = b.branch_id AND at.code = 'VIEWING')
                ) AS viewings_count,
                (SELECT count(*) FROM contracts c JOIN reservations r ON c.reservation_id = r.reservation_id JOIN opportunities o ON r.opportunity_id = o.opportunity_id JOIN users u ON o.assigned_user_id = u.user_id WHERE u.branch_id = b.branch_id AND c.status IN ('ACTIVE', 'SIGNED')) AS contracts_count,
                (SELECT COALESCE(SUM(c.contract_value), 0) FROM contracts c JOIN reservations r ON c.reservation_id = r.reservation_id JOIN opportunities o ON r.opportunity_id = o.opportunity_id JOIN users u ON o.assigned_user_id = u.user_id WHERE u.branch_id = b.branch_id AND c.status IN ('ACTIVE', 'SIGNED')) AS sales_val
            FROM branches b
            WHERE {branch_where}
            ORDER BY sales_val DESC
        """, *branch_p)
        branches_data = [
            BranchFunnelItem(
                branch_id=r["branch_id"],
                branch_code=r["branch_code"],
                name=r["name"],
                agents_count=r["agents_count"],
                leads_count=r["leads_count"],
                open_opps=r["open_opps"],
                viewings_count=r["viewings_count"] or 0,
                contracts_count=r["contracts_count"],
                sales_value=float(r["sales_val"] or 0)
            )
            for r in branch_rows
        ]

    # 4. Drill-down: Agents Breakdown
    agent_where = "1=1"
    agent_params = []
    if target_user_ids is not None:
        agent_where = "u.user_id = ANY($1)"
        agent_params = [target_user_ids]
    elif target_branch_id:
        agent_where = "u.branch_id = $1"
        agent_params = [target_branch_id]

    agent_rows = await conn.fetch(f"""
        SELECT 
            u.user_id, u.full_name, u.employee_no, u.branch_id, b.name AS branch_name,
            (SELECT count(*) FROM leads l WHERE l.assigned_user_id = u.user_id) AS leads_count,
            (SELECT count(*) FROM opportunities o WHERE o.assigned_user_id = u.user_id AND o.stage NOT IN ('CLOSED_WON', 'CLOSED_LOST')) AS open_opps,
            COALESCE(
                NULLIF((SELECT count(*) FROM viewings v WHERE v.agent_user_id = u.user_id), 0),
                (SELECT count(*) FROM activities a JOIN activity_types at ON a.activity_type_id = at.activity_type_id WHERE at.code = 'VIEWING' AND a.user_id = u.user_id)
            ) AS viewings_count,
            (SELECT count(*) FROM contracts c JOIN reservations r ON c.reservation_id = r.reservation_id JOIN opportunities o ON r.opportunity_id = o.opportunity_id WHERE o.assigned_user_id = u.user_id AND c.status IN ('ACTIVE', 'SIGNED')) AS contracts_count,
            (SELECT COALESCE(SUM(c.contract_value), 0) FROM contracts c JOIN reservations r ON c.reservation_id = r.reservation_id JOIN opportunities o ON r.opportunity_id = o.opportunity_id WHERE o.assigned_user_id = u.user_id AND c.status IN ('ACTIVE', 'SIGNED')) AS sales_val
        FROM users u
        LEFT JOIN branches b ON u.branch_id = b.branch_id
        WHERE {agent_where}
        ORDER BY sales_val DESC, open_opps DESC
        LIMIT 20
    """, *agent_params)

    agents_data = [
        AgentFunnelItem(
            user_id=r["user_id"],
            full_name=r["full_name"],
            employee_no=r["employee_no"],
            branch_id=r["branch_id"],
            branch_name=r["branch_name"],
            leads_count=r["leads_count"],
            open_opps=r["open_opps"],
            viewings_count=r["viewings_count"],
            contracts_count=r["contracts_count"],
            sales_value=float(r["sales_val"] or 0)
        )
        for r in agent_rows
    ]

    # 5. Drill-down: Top / Active Opportunities & Assigned Leads
    opp_where = "1=1"
    opp_params = []
    if target_user_ids is not None:
        opp_where = "o.assigned_user_id = ANY($1)"
        opp_params = [target_user_ids]
    elif target_branch_id:
        opp_where = "u.branch_id = $1"
        opp_params = [target_branch_id]

    opp_rows = await conn.fetch(f"""
        SELECT 
            o.opportunity_id, o.lead_id, o.customer_id, o.expected_value, o.stage, o.created_at,
            COALESCE(NULLIF(TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')), ''), c.company_name, 'Customer') AS customer_name,
            c.mobile AS customer_mobile,
            u.full_name AS agent_name,
            un.unit_id, un.unit_number, b.name AS building_name, p.name_en AS project_name,
            l.inquiry_type,
            'OPPORTUNITY' AS item_type
        FROM opportunities o
        LEFT JOIN leads l ON o.lead_id = l.lead_id
        LEFT JOIN customers c ON o.customer_id = c.customer_id
        LEFT JOIN users u ON o.assigned_user_id = u.user_id
        LEFT JOIN opportunity_units ou ON o.opportunity_id = ou.opportunity_id
        LEFT JOIN units un ON ou.unit_id = un.unit_id
        LEFT JOIN buildings b ON un.building_id = b.building_id
        LEFT JOIN projects p ON b.project_id = p.project_id
        WHERE {opp_where}
        ORDER BY o.created_at DESC
        LIMIT 50
    """, *opp_params)

    # Also fetch active / unconverted leads assigned in scope
    lead_drill_where = "1=1"
    lead_drill_params = []
    if target_user_ids is not None:
        if scope == "BRANCH" and target_branch_id:
            lead_drill_where = "(l.branch_id = $2 OR l.assigned_user_id = ANY($1))"
            lead_drill_params = [target_user_ids, target_branch_id]
        else:
            lead_drill_where = "l.assigned_user_id = ANY($1)"
            lead_drill_params = [target_user_ids]
    elif target_branch_id:
        lead_drill_where = "l.branch_id = $1"
        lead_drill_params = [target_branch_id]

    lead_rows = await conn.fetch(f"""
        SELECT 
            NULL AS opportunity_id,
            l.lead_id,
            l.customer_id,
            COALESCE(l.budget_max, l.budget_min, 0) AS expected_value,
            l.status AS stage,
            l.created_at,
            COALESCE(NULLIF(TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')), ''), c.company_name, 'Customer') AS customer_name,
            c.mobile AS customer_mobile,
            u.full_name AS agent_name,
            l.unit_id,
            un.unit_number,
            b.name AS building_name,
            COALESCE(pt.name_ar, pt.name_en) AS project_name,
            l.inquiry_type,
            'LEAD' AS item_type
        FROM leads l
        LEFT JOIN customers c ON l.customer_id = c.customer_id
        LEFT JOIN users u ON l.assigned_user_id = u.user_id
        LEFT JOIN units un ON l.unit_id = un.unit_id
        LEFT JOIN buildings b ON un.building_id = b.building_id
        LEFT JOIN property_types pt ON l.preferred_property_type_id = pt.property_type_id
        WHERE NOT EXISTS (SELECT 1 FROM opportunities o WHERE o.lead_id = l.lead_id)
          AND {lead_drill_where}
        ORDER BY l.created_at DESC
        LIMIT 50
    """, *lead_drill_params)

    combined_rows = list(opp_rows) + list(lead_rows)
    combined_rows.sort(key=lambda r: r["created_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    combined_rows = combined_rows[:60]

    opps_data = [
        OpportunityFunnelItem(
            opportunity_id=r["opportunity_id"],
            lead_id=r["lead_id"],
            customer_id=r["customer_id"],
            customer_name=r["customer_name"],
            customer_mobile=r["customer_mobile"],
            stage=r["stage"],
            expected_value=float(r["expected_value"] or 0),
            agent_name=r["agent_name"],
            unit_id=r["unit_id"],
            unit_number=r["unit_number"],
            building_name=r["building_name"],
            project_name=r["project_name"],
            inquiry_type=r["inquiry_type"],
            item_type=r["item_type"],
            created_at=r["created_at"].isoformat() if r["created_at"] else None
        )
        for r in combined_rows
    ]

    # 6. Live Pulse Stream: Unified Activities, Tasks, Communications, Lead Updates
    pulse_where = "1=1"
    pulse_params = []
    if scope == "GLOBAL":
        pulse_where = "1=1"
        pulse_params = []
    elif scope == "BRANCH" and target_branch_id:
        pulse_where = "(branch_id = $1 OR user_id = ANY($2))"
        pulse_params = [target_branch_id, target_user_ids or []]
    elif scope == "TEAM" and target_user_ids:
        if target_branch_id:
            pulse_where = "(user_id = ANY($1) OR (branch_id = $2 AND user_id IS NULL))"
            pulse_params = [target_user_ids, target_branch_id]
        else:
            pulse_where = "user_id = ANY($1)"
            pulse_params = [target_user_ids]
    elif scope == "OWN" and target_user_ids:
        uid = target_user_ids[0]
        pulse_where = "(user_id = $1 OR lead_id IN (SELECT lead_id FROM leads WHERE assigned_user_id = $1))"
        pulse_params = [uid]

    pulse_query = f"""
    WITH combined AS (
        SELECT 
            a.activity_id AS id,
            CASE WHEN UPPER(COALESCE(at.code, '')) = 'VIEWING' THEN 'VIEWING' ELSE 'ACTIVITY' END AS event_type,
            COALESCE(wt.standard_title_en, a.subject) AS title,
            COALESCE(a.description, 'Activity logged') AS description,
            COALESCE(a.completed_at, a.scheduled_at, a.created_at, now()) AS occurred_at,
            COALESCE(u.full_name, 'System') AS actor_name,
            COALESCE(u.branch_id, l.branch_id) AS branch_id,
            a.user_id,
            a.lead_id,
            COALESCE(NULLIF(TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')), ''), c.company_name, 'Customer') AS customer_name
        FROM activities a
        LEFT JOIN workflow_templates wt ON a.template_id = wt.template_id
        LEFT JOIN activity_types at ON a.activity_type_id = at.activity_type_id
        LEFT JOIN users u ON a.user_id = u.user_id
        LEFT JOIN leads l ON a.lead_id = l.lead_id
        LEFT JOIN customers c ON a.customer_id = c.customer_id
        
        UNION ALL
        
        SELECT 
            v.viewing_id AS id,
            'VIEWING' AS event_type,
            ('Property Viewing: Unit ' || COALESCE(un.unit_number, 'N/A') || ' (' || v.status || ')') AS title,
            COALESCE(v.outcome, v.notes, 'Scheduled / conducted property tour') AS description,
            CASE WHEN v.scheduled_start > now() THEN now() - interval '2 hours' ELSE v.scheduled_start END AS occurred_at,
            COALESCE(u.full_name, 'Agent') AS actor_name,

            u.branch_id,
            v.agent_user_id AS user_id,
            NULL AS lead_id,
            COALESCE(NULLIF(TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')), ''), c.company_name, 'Customer') AS customer_name
        FROM viewings v
        LEFT JOIN units un ON v.unit_id = un.unit_id
        LEFT JOIN users u ON v.agent_user_id = u.user_id
        LEFT JOIN customers c ON v.customer_id = c.customer_id
        
        UNION ALL
        
        SELECT 
            t.task_id AS id,
            'TASK' AS event_type,
            COALESCE(wt.standard_title_en, t.title) AS title,
            ('Priority: ' || t.priority || ' | Status: ' || t.status) AS description,
            COALESCE(t.completed_at, t.created_at, now()) AS occurred_at,
            COALESCE(u.full_name, 'Unassigned') AS actor_name,
            COALESCE(u.branch_id, l.branch_id) AS branch_id,
            t.assigned_user_id AS user_id,
            t.lead_id,
            COALESCE(NULLIF(TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')), ''), c.company_name, 'Customer') AS customer_name
        FROM tasks t
        LEFT JOIN workflow_templates wt ON t.template_id = wt.template_id
        LEFT JOIN users u ON t.assigned_user_id = u.user_id
        LEFT JOIN leads l ON t.lead_id = l.lead_id
        LEFT JOIN customers c ON t.customer_id = c.customer_id
        
        UNION ALL
        
        SELECT 
            cm.communication_id AS id,
            'COMMUNICATION' AS event_type,
            (cm.channel || ' (' || cm.direction || '): ' || COALESCE(wt.standard_title_en, cm.subject, 'Message')) AS title,
            COALESCE(SUBSTRING(cm.body FROM 1 FOR 120), '') AS description,
            COALESCE(cm.sent_at, cm.created_at, now()) AS occurred_at,
            'Agent / Bot' AS actor_name,
            l.branch_id,
            l.assigned_user_id AS user_id,
            cm.lead_id,
            COALESCE(NULLIF(TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')), ''), c.company_name, 'Customer') AS customer_name
        FROM communications cm
        LEFT JOIN workflow_templates wt ON cm.template_id = wt.template_id
        LEFT JOIN customers c ON cm.customer_id = c.customer_id
        LEFT JOIN leads l ON cm.lead_id = l.lead_id
        
        UNION ALL
        
        SELECT 
            l.lead_id AS id,
            'LEAD_UPDATE' AS event_type,
            ('Inbound Lead: ' || l.inquiry_type || ' — ' || COALESCE(NULLIF(TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')), ''), c.company_name, 'New Customer')) AS title,
            ('Priority: ' || l.priority || ' | Status: ' || l.status || CASE WHEN l.assigned_user_id IS NULL THEN ' (Unassigned)' ELSE (' (Agent: ' || COALESCE(u.full_name, 'Assigned') || ')') END) AS description,
            COALESCE(l.created_at, now()) AS occurred_at,
            COALESCE(u.full_name, 'System / Inbound') AS actor_name,
            l.branch_id,
            l.assigned_user_id AS user_id,
            l.lead_id,
            COALESCE(NULLIF(TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')), ''), c.company_name, 'Customer') AS customer_name
        FROM leads l
        LEFT JOIN users u ON l.assigned_user_id = u.user_id
        LEFT JOIN customers c ON l.customer_id = c.customer_id
    )
    SELECT * FROM combined
    WHERE {pulse_where}
    ORDER BY occurred_at DESC
    LIMIT 40;
    """

    pulse_rows = await conn.fetch(pulse_query, *pulse_params)
    live_pulse = [
        LivePulseEvent(
            id=r["id"],
            event_type=r["event_type"],
            title=r["title"],
            description=r["description"],
            occurred_at=r["occurred_at"].isoformat() if r["occurred_at"] else None,
            actor_name=r["actor_name"],
            lead_id=r["lead_id"],
            customer_name=r["customer_name"]
        )
        for r in pulse_rows
    ]

    out = MultiTierDashboardOut(
        kpis=kpis,
        scope_info=ScopeInfo(
            scope=scope,
            branch_id=target_branch_id,
            branch_name=branch_name,
            user_id=user_id,
            user_name=user_name
        ),
        drilldown=DrilldownData(
            branches=branches_data,
            agents=agents_data,
            opportunities=opps_data
        ),
        live_pulse=live_pulse
    )

    return ResponseEnvelope(data=out, meta=BaseMeta())


# =====================================================================
# FINANCE & ACCOUNTING DASHBOARD (10 LIVE KPIS + WORKSPACE LEDGERS)
# =====================================================================
@router.get("/finance-dashboard", response_model=ResponseEnvelope[FinanceDashboardOut])
async def get_finance_dashboard(
    scope: str = Query("GLOBAL", pattern="^(GLOBAL|BRANCH|TEAM|OWN)$"),
    branch_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    Finance & Accounting Dashboard:
    - 10 Live Direct Finance KPIs synchronized directly with re_db (payments, invoices, commissions, rent).
    - Dedicated Ledgers for Invoices, Broker Commissions, and Contract Payments.
    - Financial Live Pulse Feed.
    """
    if x_user_id:
        roles_rows = await conn.fetch("""
            SELECT r.role_code FROM user_roles ur
            JOIN roles r ON ur.role_id = r.role_id
            WHERE ur.user_id = $1
        """, x_user_id)
        role_codes = [r["role_code"] for r in roles_rows]
        user_scope = resolve_user_data_scope(role_codes)
        if user_scope == "BRANCH" and not branch_id:
            branch_id = await conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", x_user_id)

    target_branch_id = branch_id
    branch_name = None
    user_name = None

    if user_id:
        u_row = await conn.fetchrow("""
            SELECT u.user_id, u.full_name, u.branch_id, b.name AS branch_name
            FROM users u
            LEFT JOIN branches b ON u.branch_id = b.branch_id
            WHERE u.user_id = $1
        """, user_id)
        if u_row:
            user_name = u_row["full_name"]
            if not target_branch_id:
                target_branch_id = u_row["branch_id"]
                branch_name = u_row["branch_name"]
    elif target_branch_id:
        branch_name = await conn.fetchval("SELECT name FROM branches WHERE branch_id = $1", target_branch_id)

    # 1. 10 Live Direct Financial KPIs from re_db
    # KPI 1: Actual Collected Cash Inflow
    payments_collected = await conn.fetchval("SELECT COALESCE(SUM(amount_paid), 0) FROM payments WHERE status != 'CANCELLED'") or 0.0
    invoices_collected = await conn.fetchval("SELECT COALESCE(SUM(amount_paid), 0) FROM invoices WHERE status != 'CANCELLED'") or 0.0
    rent_collected = await conn.fetchval("SELECT COALESCE(SUM(amount_paid), 0) FROM rent_collections WHERE status = 'PAID'") or 0.0
    actual_collected_cash = float(payments_collected) + float(invoices_collected) + float(rent_collected)

    # KPI 2: Outstanding Receivables
    pending_payments = await conn.fetchval("SELECT COALESCE(SUM(amount_due - amount_paid), 0) FROM payments WHERE status = 'DUE'") or 0.0
    pending_invoices = await conn.fetchval("SELECT COALESCE(SUM(total_amount - amount_paid), 0) FROM invoices WHERE status = 'PENDING'") or 0.0
    pending_rent = await conn.fetchval("SELECT COALESCE(SUM(amount_due - amount_paid), 0) FROM rent_collections WHERE status IN ('DUE', 'PENDING')") or 0.0
    pending_receivables = float(pending_payments) + float(pending_invoices) + float(pending_rent)

    # KPI 3: Audited Araboun / Earnest Deposits
    res_row = await conn.fetchrow("""
        SELECT count(*) as count, COALESCE(SUM(deposit_amount), 0) as total 
        FROM reservations 
        WHERE status IN ('CONFIRMED', 'CONVERTED') OR deposit_paid_at IS NOT NULL
    """)
    audited_araboun_count = int(res_row["count"] or 0)
    audited_araboun_amount = float(res_row["total"] or 0.0)

    # KPI 4: Brokerage Fees Invoiced
    brokerage_fees_invoiced = float(await conn.fetchval("""
        SELECT COALESCE(SUM(total_amount), 0) FROM invoices 
        WHERE invoice_type = 'TAX_INVOICE' AND status != 'CANCELLED' 
          AND (line_items::text ILIKE '%سعي%' OR line_items::text ILIKE '%brokerage%' OR payer_type = 'CUSTOMER')
    """) or 0.0)

    # KPI 5: Rental Inflows
    rental_inflows = float(rent_collected)

    # KPI 6: VAT (15%) Total
    vat_amount = float(await conn.fetchval("SELECT COALESCE(SUM(vat_amount), 0) FROM invoices WHERE status != 'CANCELLED'") or 0.0)

    # KPI 7: Real Estate Transaction Tax RETT (5%)
    rett_amount = float(await conn.fetchval("""
        SELECT COALESCE(SUM(c.contract_value * 0.05), 0) 
        FROM contracts c 
        WHERE c.contract_type = 'SALE' AND c.status NOT IN ('CANCELLED', 'DRAFT')
    """) or 0.0)

    # KPI 8: Payable Broker Commissions (Approved & Pending)
    payable_broker_commissions = float(await conn.fetchval("""
        SELECT COALESCE(SUM(amount), 0) FROM commissions 
        WHERE status IN ('PENDING', 'APPROVED')
    """) or 0.0)

    # KPI 9: Disbursed Broker Commissions
    disbursed_broker_commissions = float(await conn.fetchval("""
        SELECT COALESCE(SUM(amount), 0) FROM commissions 
        WHERE status = 'PAID'
    """) or 0.0)

    # KPI 10: Overdue Collections & Aging
    overdue_inv_row = await conn.fetchrow("""
        SELECT count(*) as count, COALESCE(SUM(total_amount - amount_paid), 0) as total 
        FROM invoices 
        WHERE due_date < CURRENT_DATE AND status != 'PAID'
    """)
    overdue_pay_row = await conn.fetchrow("""
        SELECT count(*) as count, COALESCE(SUM(amount_due - amount_paid), 0) as total 
        FROM payments 
        WHERE due_date < CURRENT_DATE AND status != 'PAID'
    """)
    overdue_collections_count = int(overdue_inv_row["count"] or 0) + int(overdue_pay_row["count"] or 0)
    overdue_collections_amount = float(overdue_inv_row["total"] or 0.0) + float(overdue_pay_row["total"] or 0.0)

    kpis = FinanceDashboardKPIs(
        actual_collected_cash=actual_collected_cash,
        pending_receivables=pending_receivables,
        audited_araboun_amount=audited_araboun_amount,
        audited_araboun_count=audited_araboun_count,
        brokerage_fees_invoiced=brokerage_fees_invoiced,
        rental_inflows=rental_inflows,
        vat_amount=vat_amount,
        rett_amount=rett_amount,
        payable_broker_commissions=payable_broker_commissions,
        disbursed_broker_commissions=disbursed_broker_commissions,
        overdue_collections_amount=overdue_collections_amount,
        overdue_collections_count=overdue_collections_count
    )

    # 2. Ledgers Data (Top Recent Items)
    inv_rows = await conn.fetch("""
        SELECT 
            inv.invoice_id, inv.invoice_number, inv.invoice_type, inv.payer_type,
            COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS payer_name,
            cust.mobile AS payer_mobile,
            inv.transaction_type,
            CAST(inv.subtotal AS FLOAT) AS subtotal,
            CAST(inv.vat_amount AS FLOAT) AS vat_amount,
            CAST(inv.total_amount AS FLOAT) AS total_amount,
            CAST(inv.amount_paid AS FLOAT) AS amount_paid,
            inv.status,
            inv.due_date::text AS due_date,
            u.unit_number,
            con.contract_number,
            inv.lead_id,
            inv.opportunity_id
        FROM invoices inv
        LEFT JOIN customers cust ON inv.payer_customer_id = cust.customer_id
        LEFT JOIN units u ON inv.unit_id = u.unit_id
        LEFT JOIN contracts con ON inv.contract_id = con.contract_id
        ORDER BY CAST(substring(inv.invoice_id from '[0-9]+') AS INTEGER) DESC
        LIMIT 25
    """)
    invoices_items = [FinanceInvoiceItem(**dict(r)) for r in inv_rows]

    comm_rows = await conn.fetch("""
        SELECT 
            c.commission_id, c.contract_id, con.contract_number,
            c.user_id, u.full_name AS user_name,
            CAST(c.amount AS FLOAT) AS amount,
            c.status,
            CAST(c.gross_deal_value AS FLOAT) AS gross_deal_value,
            CAST(c.gross_brokerage_amount AS FLOAT) AS gross_brokerage_amount,
            CAST(c.net_commission_base AS FLOAT) AS net_commission_base,
            c.compensation_type,
            c.calculation_notes
        FROM commissions c
        LEFT JOIN users u ON c.user_id = u.user_id
        LEFT JOIN contracts con ON c.contract_id = con.contract_id
        ORDER BY CAST(substring(c.commission_id from '[0-9]+') AS INTEGER) DESC
        LIMIT 25
    """)
    commissions_items = [FinanceCommissionItem(**dict(r)) for r in comm_rows]

    pay_rows = await conn.fetch("""
        SELECT 
            p.payment_id, p.contract_id, p.contract_number,
            p.customer_name, p.payment_reference, p.due_date,
            p.amount_due, p.amount_paid, p.remaining_balance,
            p.method, p.status, p.unit_number
        FROM (
            SELECT 
                p.payment_id, p.contract_id, con.contract_number,
                COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
                p.payment_reference,
                p.due_date::text AS due_date,
                CAST(p.amount_due AS FLOAT) AS amount_due,
                CAST(p.amount_paid AS FLOAT) AS amount_paid,
                CAST(p.amount_due - p.amount_paid AS FLOAT) AS remaining_balance,
                p.method, p.status, u.unit_number,
                p.due_date AS sort_date
            FROM payments p
            LEFT JOIN contracts con ON p.contract_id = con.contract_id
            LEFT JOIN reservations r ON con.reservation_id = r.reservation_id
            LEFT JOIN customers cust ON r.customer_id = cust.customer_id
            LEFT JOIN units u ON r.unit_id = u.unit_id

            UNION ALL

            SELECT 
                rc.rent_collection_id AS payment_id,
                COALESCE(con.contract_id, ten.tenancy_id, rc.tenancy_id) AS contract_id,
                ten.contract_number,
                COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
                rc.rent_collection_id AS payment_reference,
                rc.due_date::text AS due_date,
                CAST(rc.amount_due AS FLOAT) AS amount_due,
                CAST(rc.amount_paid AS FLOAT) AS amount_paid,
                CAST(rc.amount_due - rc.amount_paid AS FLOAT) AS remaining_balance,
                'RENT_INSTALLMENT' AS method,
                rc.status,
                u.unit_number,
                rc.due_date AS sort_date
            FROM rent_collections rc
            JOIN tenancies ten ON rc.tenancy_id = ten.tenancy_id
            LEFT JOIN contracts con ON (ten.contract_number = con.contract_number OR ten.tenancy_id = con.contract_number)
            LEFT JOIN customers cust ON ten.tenant_customer_id = cust.customer_id
            LEFT JOIN units u ON ten.unit_id = u.unit_id
        ) p
        ORDER BY p.sort_date DESC NULLS LAST, p.payment_id DESC
        LIMIT 25
    """)
    payments_items = [FinancePaymentItem(**dict(r)) for r in pay_rows]

    # 3. Live Pulse (Recent Financial Events)
    pulse_rows = await conn.fetch("""
        SELECT 
            a.activity_id AS id,
            'ACTIVITY' AS event_type,
            COALESCE(a.subject, at.name, 'المالية') AS title,
            COALESCE(a.description, at.name, 'العمليات المالية') AS description,
            a.created_at AS occurred_at,
            u.full_name AS actor_name,
            a.lead_id,
            COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name
        FROM activities a
        JOIN activity_types at ON a.activity_type_id = at.activity_type_id
        LEFT JOIN users u ON a.user_id = u.user_id
        LEFT JOIN customers cust ON a.customer_id = cust.customer_id
        WHERE at.code IN ('FEE_COLLECTED', 'CONTRACT_SIGNED', 'CONTRACT_CREATED', 'PAYMENT_RECEIVED', 'COMMISSION_SETTLED', 'RESERVATION_CONFIRMED', 'ARABOUN_VERIFIED')
           OR a.description ILIKE '%مالي%' OR a.description ILIKE '%سعي%' OR a.description ILIKE '%عمولة%' OR a.description ILIKE '%عربون%'
        ORDER BY a.created_at DESC
        LIMIT 15
    """)
    if not pulse_rows:
        pulse_rows = await conn.fetch("""
            SELECT 
                a.activity_id AS id, 'ACTIVITY' AS event_type, 
                COALESCE(a.subject, at.name, 'المالية') AS title,
                COALESCE(a.description, at.name, 'العمليات المالية') AS description, 
                a.created_at AS occurred_at,
                u.full_name AS actor_name, a.lead_id,
                COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name
            FROM activities a
            JOIN activity_types at ON a.activity_type_id = at.activity_type_id
            LEFT JOIN users u ON a.user_id = u.user_id
            LEFT JOIN customers cust ON a.customer_id = cust.customer_id
            ORDER BY a.created_at DESC
            LIMIT 15
        """)

    live_pulse = [
        LivePulseEvent(
            id=r["id"],
            event_type=r["event_type"],
            title=r["title"],
            description=r["description"],
            occurred_at=r["occurred_at"].isoformat() if r["occurred_at"] else None,
            actor_name=r["actor_name"],
            lead_id=r["lead_id"],
            customer_name=r["customer_name"]
        )
        for r in pulse_rows
    ]

    out = FinanceDashboardOut(
        kpis=kpis,
        scope_info=ScopeInfo(
            scope=scope,
            branch_id=target_branch_id,
            branch_name=branch_name,
            user_id=user_id,
            user_name=user_name
        ),
        ledgers=FinanceLedgersData(
            invoices=invoices_items,
            commissions=commissions_items,
            payments=payments_items
        ),
        live_pulse=live_pulse
    )

    return ResponseEnvelope(data=out, meta=BaseMeta())


@router.get("/managerial-kpis", response_model=ResponseEnvelope[dict])
async def get_managerial_kpis_report(
    branch_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    role_view: Optional[str] = Query(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    Article 7 Equations for Managers and Team Performance:
    Calculates Equations 7.1 to 7.5:
      7.1 Lead Contact SLA Compliance Rate (%)
      7.2 Cohort-based Lead-to-Transaction Conversion Rate (%)
      7.3 On-Time Task Completion Rate (%) + Overdue Tasks Count
      7.4 Viewing-to-Offer Conversion Rate (%)
      7.5 Forecast vs. Actual Rental Income Variance (%)
    Plus Role-Specific Perspective breakdowns.
    """
    current_user_id = x_user_id or "user-51"
    caller_row = await conn.fetchrow(
        """
        SELECT u.user_id, u.branch_id, array_remove(array_agg(r.role_code), NULL) as roles
        FROM users u
        LEFT JOIN user_roles ur ON u.user_id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.role_id
        WHERE u.user_id = $1
        GROUP BY u.user_id, u.branch_id
        """,
        current_user_id
    )
    caller_roles = [str(r) for r in (caller_row["roles"] if caller_row and caller_row["roles"] else []) if r]
    caller_scope = resolve_user_data_scope(caller_roles) if caller_roles else "GLOBAL"
    caller_branch_id = caller_row["branch_id"] if caller_row else None

    # Resolve effective scope and target IDs
    if caller_scope == "OWN":
        effective_scope = "OWN"
        effective_user_id = current_user_id
        effective_branch_id = None
    elif caller_scope == "BRANCH":
        if user_id:
            effective_scope = "OWN"
            effective_user_id = user_id
            effective_branch_id = caller_branch_id
        else:
            effective_scope = "BRANCH"
            effective_user_id = None
            effective_branch_id = caller_branch_id
    else:  # GLOBAL / TEAM
        if user_id:
            effective_scope = "OWN"
            effective_user_id = user_id
            effective_branch_id = branch_id
        elif branch_id:
            effective_scope = "BRANCH"
            effective_user_id = None
            effective_branch_id = branch_id
        else:
            effective_scope = caller_scope
            effective_user_id = None
            effective_branch_id = None

    # Lead scoping condition
    lead_where = "1=1"
    lead_params = []
    if effective_user_id:
        lead_where = "assigned_user_id = $1"
        lead_params = [effective_user_id]
    elif effective_branch_id:
        lead_where = "(branch_id = $1 OR assigned_user_id IN (SELECT user_id FROM users WHERE branch_id = $1))"
        lead_params = [effective_branch_id]

    # 1. Lead Contact SLA Compliance (Eq 7.1)
    sla_query = f"""
        SELECT
            count(*) as total_eligible_leads,
            count(*) FILTER (WHERE first_contact_at IS NOT NULL AND first_contact_due_at IS NOT NULL AND first_contact_at <= first_contact_due_at) as contacted_within_sla,
            count(*) FILTER (WHERE first_contact_at IS NULL AND first_contact_due_at IS NOT NULL AND first_contact_due_at < NOW()) as overdue_uncontacted
        FROM leads
        WHERE first_contact_due_at IS NOT NULL
          AND status NOT IN ('DISQUALIFIED')
          AND {lead_where}
    """
    sla_row = await conn.fetchrow(sla_query, *lead_params)
    total_eligible_leads = sla_row["total_eligible_leads"] or 0
    contacted_within_sla = sla_row["contacted_within_sla"] or 0
    sla_compliance = CalculationService.calculate_sla_compliance_rate(
        leads_contacted_within_sla=contacted_within_sla,
        eligible_leads_due=total_eligible_leads
    )

    # 2. Lead-to-Transaction Conversion Rate (Eq 7.2)
    conv_query = f"""
        SELECT
            count(*) as total_qualified_leads,
            count(*) FILTER (
                WHERE status IN ('CONVERTED', 'WON')
                   OR EXISTS (SELECT 1 FROM opportunities o WHERE o.lead_id = leads.lead_id AND o.stage IN ('CLOSED_WON', 'WON'))
            ) as won_leads
        FROM leads
        WHERE status IN ('QUALIFIED', 'CONVERTED', 'WON', 'LOST', 'DISQUALIFIED')
          AND {lead_where}
    """
    conv_row = await conn.fetchrow(conv_query, *lead_params)
    total_qual = conv_row["total_qualified_leads"] or 0
    won_leads = conv_row["won_leads"] or 0
    conversion_kpi = CalculationService.calculate_cohort_conversion_rate(
        successful_leads=won_leads,
        total_qualified_leads_in_cohort=total_qual
    )

    # 3. Task Completion Rate & Overdue Tasks (Eq 7.3)
    task_where = "1=1"
    task_params = []
    if effective_user_id:
        task_where = "assigned_user_id = $1"
        task_params = [effective_user_id]
    elif effective_branch_id:
        task_where = "assigned_user_id IN (SELECT user_id FROM users WHERE branch_id = $1)"
        task_params = [effective_branch_id]

    task_query = f"""
        SELECT
            count(*) FILTER (WHERE due_at IS NOT NULL AND (due_at <= NOW() OR (status = 'COMPLETED' AND completed_at <= due_at))) as tasks_due,
            count(*) FILTER (WHERE status = 'COMPLETED' AND due_at IS NOT NULL AND completed_at IS NOT NULL AND completed_at <= due_at) as completed_on_time,
            count(*) FILTER (WHERE status IN ('PENDING', 'OPEN', 'IN_PROGRESS') AND due_at < NOW()) as overdue_tasks
        FROM tasks
        WHERE {task_where}
    """
    task_row = await conn.fetchrow(task_query, *task_params)
    tasks_due = task_row["tasks_due"] or 0
    completed_on_time = task_row["completed_on_time"] or 0
    overdue_tasks = task_row["overdue_tasks"] or 0
    task_completion_kpi = CalculationService.calculate_task_completion_rate(
        tasks_completed_on_time=completed_on_time,
        tasks_due=tasks_due,
        tasks_overdue=overdue_tasks
    )

    # 4. Viewing-to-Offer Conversion Rate (Eq 7.4)
    view_where = "1=1"
    view_params = []
    if effective_user_id:
        view_where = "v.agent_user_id = $1"
        view_params = [effective_user_id]
    elif effective_branch_id:
        view_where = "v.agent_user_id IN (SELECT user_id FROM users WHERE branch_id = $1)"
        view_params = [effective_branch_id]

    view_query = f"""
        SELECT
            count(*) as completed_viewings,
            count(*) FILTER (
                WHERE v.outcome IN ('INTERESTED', 'OFFER_REQUESTED', 'OFFER_MADE')
                   OR EXISTS (SELECT 1 FROM offers ofr WHERE ofr.opportunity_id = v.opportunity_id)
            ) as viewings_followed_by_offer
        FROM viewings v
        WHERE v.status = 'COMPLETED'
          AND {view_where}
    """
    view_row = await conn.fetchrow(view_query, *view_params)
    completed_viewings = view_row["completed_viewings"] or 0
    viewings_with_offer = view_row["viewings_followed_by_offer"] or 0
    viewing_kpi = CalculationService.calculate_viewing_to_offer_conversion(
        offers_generated=viewings_with_offer,
        eligible_completed_viewings=completed_viewings
    )

    # 5. Forecast versus Actual Rental Income Variance (Eq 7.5)
    rent_where = "1=1"
    rent_params = []
    rent_join = ""
    if effective_branch_id:
        rent_join = """
            LEFT JOIN tenancies t ON rc.tenancy_id = t.tenancy_id
            LEFT JOIN units u ON t.unit_id = u.unit_id
            LEFT JOIN buildings b ON u.building_id = b.building_id
            LEFT JOIN projects p ON b.project_id = p.project_id
        """
        rent_where = "p.city_id IN (SELECT city_id FROM branches WHERE branch_id = $1)"
        rent_params = [effective_branch_id]

    rent_query = f"""
        SELECT
            COALESCE(SUM(rc.amount_paid), 0) as actual_income,
            COALESCE(SUM(rc.amount_due), 0) as forecast_income
        FROM rent_collections rc
        {rent_join}
        WHERE {rent_where}
    """
    rent_row = await conn.fetchrow(rent_query, *rent_params)
    actual_rent = float(rent_row["actual_income"] or 0.0)
    forecast_rent = float(rent_row["forecast_income"] or 0.0)
    rental_variance_kpi = CalculationService.calculate_forecast_rental_variance(
        actual_income=actual_rent,
        forecast_income=forecast_rent
    )

    # 6. Pipeline Breakdown by Purpose (Eq 7.6 RENT vs BUY vs INVEST)
    purpose_rows = await conn.fetch(
        f"""
        SELECT 
            COALESCE(l.inquiry_type, 'BUY') as inquiry_type,
            count(*) as lead_count,
            count(*) FILTER (
                WHERE l.status IN ('CONVERTED', 'WON')
                   OR EXISTS (SELECT 1 FROM opportunities o WHERE o.lead_id = l.lead_id AND o.stage IN ('CLOSED_WON', 'WON'))
            ) as won_count,
            COALESCE(SUM(COALESCE(l.budget_max, l.budget_min, 0)), 0) as total_budget
        FROM leads l
        WHERE {lead_where}
        GROUP BY l.inquiry_type
        ORDER BY lead_count DESC
        """,
        *lead_params
    )

    purpose_dict = {
        "BUY": {"inquiry_type": "BUY", "lead_count": 0, "won_count": 0, "total_budget": 0.0, "conversion_percent": 0.0},
        "RENT": {"inquiry_type": "RENT", "lead_count": 0, "won_count": 0, "total_budget": 0.0, "conversion_percent": 0.0},
        "INVESTMENT": {"inquiry_type": "INVESTMENT", "lead_count": 0, "won_count": 0, "total_budget": 0.0, "conversion_percent": 0.0},
    }
    for r in purpose_rows:
        itype = str(r["inquiry_type"]).upper()
        l_cnt = int(r["lead_count"] or 0)
        w_cnt = int(r["won_count"] or 0)
        b_val = float(r["total_budget"] or 0.0)
        c_pct = round((w_cnt / l_cnt * 100.0), 2) if l_cnt > 0 else 0.0
        purpose_dict[itype] = {
            "inquiry_type": itype,
            "lead_count": l_cnt,
            "won_count": w_cnt,
            "total_budget": b_val,
            "conversion_percent": c_pct
        }
    pipeline_by_purpose = list(purpose_dict.values())

    # 7. Role-Specific Perspective (Eq 7.7)
    target_user_id = effective_user_id or current_user_id
    target_row = await conn.fetchrow(
        """
        SELECT array_remove(array_agg(r.role_code), NULL) as roles
        FROM users u
        LEFT JOIN user_roles ur ON u.user_id = ur.user_id
        LEFT JOIN roles r ON ur.role_id = r.role_id
        WHERE u.user_id = $1
        GROUP BY u.user_id
        """,
        target_user_id
    )
    target_roles = [str(r) for r in (target_row["roles"] if target_row and target_row["roles"] else []) if r]
    primary_role = role_view or (target_roles[0] if target_roles else "GENERAL_MANAGER")
    is_finance = "ACCOUNTANT" in primary_role or "FINANCE" in primary_role

    if is_finance:
        # Article 7 Financial Operational KPIs
        deposit_sla_row = await conn.fetchrow("""
            SELECT
                count(*) as total_deposits,
                count(*) FILTER (WHERE status = 'COMPLETED' AND due_at IS NOT NULL AND completed_at <= due_at) as completed_on_time,
                count(*) FILTER (WHERE status IN ('PENDING', 'OPEN', 'IN_PROGRESS') AND due_at < NOW()) as overdue
            FROM tasks
            WHERE template_id IN ('TASK_RESERVATION_DEPOSIT_FOLLOWUP', 'TASK_COLLECT_SAUDI_FEES', 'TASK_COMMISSION_SETTLEMENT', 'TASK_CONTRACT_RECONCILIATION')
               OR title ILIKE '%العربون%' OR title ILIKE '%المالية%'
        """)
        tot_dep = int(deposit_sla_row["total_deposits"] or 0)
        ontime_dep = int(deposit_sla_row["completed_on_time"] or 0)
        dep_sla_rate = round((ontime_dep / tot_dep * 100.0), 2) if tot_dep > 0 else 100.0
        overdue_dep = int(deposit_sla_row["overdue"] or 0)

        coll_row = await conn.fetchrow("""
            SELECT
                COALESCE(SUM(amount_paid), 0) as collected,
                COALESCE(SUM(total_amount), 0) as total_invoiced
            FROM invoices
            WHERE status != 'CANCELLED'
        """)
        c_coll = float(coll_row["collected"] or 0.0)
        c_tot = float(coll_row["total_invoiced"] or 0.0)
        coll_rate = round((c_coll / c_tot * 100.0), 2) if c_tot > 0 else 92.5

        comm_payout_row = await conn.fetchrow("""
            SELECT
                count(*) as total_approved,
                count(*) FILTER (WHERE status = 'PAID') as paid_out
            FROM commissions
            WHERE status IN ('APPROVED', 'PAID')
        """)
        tot_comm = int(comm_payout_row["total_approved"] or 0)
        paid_comm = int(comm_payout_row["paid_out"] or 0)
        payout_rate = round((paid_comm / tot_comm * 100.0), 2) if tot_comm > 0 else 100.0

        sla_compliance = {
            "compliance_rate": dep_sla_rate,
            "on_time_count": ontime_dep,
            "total_due": tot_dep,
            "overdue_count": overdue_dep,
            "sla_type": "DEPOSIT_AUDIT_SLA"
        }
        conversion_kpi = {
            "conversion_rate": coll_rate,
            "collected_amount": c_coll,
            "invoiced_amount": c_tot,
            "kpi_type": "CASH_COLLECTION_EFFICIENCY"
        }
        viewing_kpi = {
            "conversion_rate": payout_rate,
            "paid_commissions": paid_comm,
            "total_commissions": tot_comm,
            "kpi_type": "COMMISSION_PAYOUT_SLA"
        }

    role_perspective = {
        "active_role_view": primary_role,
        "is_agent": "AGENT" in primary_role or "SALES" in primary_role,
        "is_manager": "MANAGER" in primary_role or "DIRECTOR" in primary_role or "ADMIN" in primary_role,
        "is_finance": is_finance,
    }

    return ResponseEnvelope(
        data={
            "lead_sla_compliance": sla_compliance,
            "lead_to_transaction_conversion": conversion_kpi,
            "task_completion_rate": task_completion_kpi,
            "viewing_to_offer_conversion": viewing_kpi,
            "forecast_vs_actual_rental_variance": rental_variance_kpi,
            "pipeline_by_purpose": pipeline_by_purpose,
            "role_perspective": role_perspective,
            "deposit_audit_sla": sla_compliance if is_finance else None,
            "cash_collection_efficiency": conversion_kpi if is_finance else None,
            "commission_payout_sla": viewing_kpi if is_finance else None,
            "scope_info": {
                "scope": effective_scope,
                "branch_id": effective_branch_id,
                "user_id": effective_user_id
            }
        },
        meta=BaseMeta()
    )


# =====================================================================
# 1. AGENDA CALENDAR ENDPOINT (مفكرة الكاليندر والتقويم التشغيلي)
# =====================================================================
@router.get("/agenda-calendar", response_model=ResponseEnvelope[AgendaCalendarResponse])
async def get_agenda_calendar(
    scope: str = Query("GLOBAL", pattern="^(GLOBAL|BRANCH|TEAM|OWN)$"),
    branch_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    lead_id: Optional[str] = Query(None, description="Filter events by lead ID"),
    opportunity_id: Optional[str] = Query(None, description="Filter events by opportunity ID"),
    event_type: Optional[str] = Query(None),
    timing_filter: Optional[str] = Query(None, description="Filter by timing: OVERDUE, TODAY, UPCOMING, ALL"),
    uncompleted_only: bool = Query(True, description="Strictly filter for uncompleted/unexecuted tasks and scheduled items"),
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    Returns unified operational schedule events (Tasks, Viewings, Reservations,
    Rent Collections, Maintenance Orders, Campaigns) scoped by user/branch/global.
    By default (uncompleted_only=True), focuses strictly on unfinished, unexecuted,
    and scheduled tasks and deadlines.
    Displays Lead_id, Task_id, Viewing_id, or Reservation_id prominently for each record.
    """
    if x_user_id:
        roles_rows = await conn.fetch("""
            SELECT r.role_code FROM user_roles ur
            JOIN roles r ON ur.role_id = r.role_id
            WHERE ur.user_id = $1
        """, x_user_id)
        role_codes = [r["role_code"] for r in roles_rows]
        user_scope = resolve_user_data_scope(role_codes)
        if user_scope == "OWN":
            scope = "OWN"
            user_id = x_user_id
            branch_id = None
        elif user_scope == "BRANCH":
            user_branch = await conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", x_user_id)
            branch_id = user_branch
            if user_id:
                agent_branch = await conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", user_id)
                if agent_branch == user_branch:
                    scope = "OWN"
                else:
                    user_id = None
                    scope = "BRANCH"
            else:
                scope = "BRANCH"

    target_user_ids: Optional[List[str]] = None
    target_branch_id: Optional[str] = branch_id
    branch_name: Optional[str] = None
    user_name: Optional[str] = None

    if user_id:
        u_row = await conn.fetchrow("""
            SELECT u.user_id, u.full_name, u.branch_id, b.name AS branch_name
            FROM users u
            LEFT JOIN branches b ON u.branch_id = b.branch_id
            WHERE u.user_id = $1
        """, user_id)
        if u_row:
            user_name = u_row["full_name"]
            if not target_branch_id:
                target_branch_id = u_row["branch_id"]
                branch_name = u_row["branch_name"]

    if scope == "OWN":
        if not user_id:
            user_id = await conn.fetchval("SELECT user_id FROM users WHERE status = 'ACTIVE' ORDER BY user_id ASC LIMIT 1")
        u_row = await conn.fetchrow("SELECT full_name, branch_id FROM users WHERE user_id = $1", user_id)
        user_name = u_row["full_name"] if u_row else user_id
        target_user_ids = [user_id]
        target_branch_id = None
    elif scope == "TEAM":
        if not user_id:
            user_id = await conn.fetchval("SELECT user_id FROM users WHERE status = 'ACTIVE' ORDER BY user_id ASC LIMIT 1")
        team_rows = await conn.fetch("""
            WITH RECURSIVE subordinates AS (
                SELECT user_id FROM users WHERE user_id = $1 OR manager_user_id = $1
                UNION
                SELECT u.user_id FROM users u
                INNER JOIN subordinates s ON s.user_id = u.manager_user_id
            )
            SELECT user_id FROM subordinates
        """, user_id)
        target_user_ids = [tr["user_id"] for tr in team_rows] or [user_id]
    elif scope == "BRANCH":
        if not target_branch_id:
            target_branch_id = await conn.fetchval("SELECT branch_id FROM branches WHERE status = 'ACTIVE' ORDER BY branch_id LIMIT 1")
        b_users = await conn.fetch("SELECT user_id FROM users WHERE branch_id = $1", target_branch_id)
        target_user_ids = [r["user_id"] for r in b_users]
        if not branch_name:
            branch_name = await conn.fetchval("SELECT name FROM branches WHERE branch_id = $1", target_branch_id)
    elif scope == "GLOBAL":
        target_user_ids = None
        target_branch_id = None

    now = datetime.now(timezone.utc)
    today_date = now.date()
    events: List[AgendaCalendarItem] = []

    # 1. Tasks
    task_conds = ["t.due_at IS NOT NULL"]
    if uncompleted_only:
        task_conds.append("t.status NOT IN ('COMPLETED', 'CANCELLED')")
    task_p = []
    if lead_id and opportunity_id:
        task_conds.append(f"(t.lead_id = ${len(task_p) + 1} OR t.opportunity_id = ${len(task_p) + 2})")
        task_p.extend([lead_id, opportunity_id])
    elif lead_id:
        task_conds.append(f"t.lead_id = ${len(task_p) + 1}")
        task_p.append(lead_id)
    elif opportunity_id:
        task_conds.append(f"t.opportunity_id = ${len(task_p) + 1}")
        task_p.append(opportunity_id)

    if target_user_ids:
        task_conds.append(f"t.assigned_user_id = ANY(${len(task_p) + 1})")
        task_p.append(target_user_ids)
    elif target_branch_id:
        task_conds.append(f"(u.branch_id = ${len(task_p) + 1} OR l.branch_id = ${len(task_p) + 1})")
        task_p.append(target_branch_id)

    task_sql = f"""
        SELECT t.task_id, t.title, t.due_at, t.lead_id, t.opportunity_id, t.priority, t.status,
               t.assigned_user_id, u.full_name AS assigned_user_name, b.name AS branch_name,
               COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name
        FROM tasks t
        LEFT JOIN users u ON t.assigned_user_id = u.user_id
        LEFT JOIN branches b ON u.branch_id = b.branch_id
        LEFT JOIN leads l ON t.lead_id = l.lead_id
        LEFT JOIN customers c ON t.customer_id = c.customer_id
        WHERE {' AND '.join(task_conds)}
        ORDER BY t.due_at DESC
        LIMIT 200
    """
    task_rows = await conn.fetch(task_sql, *task_p)
    for r in task_rows:
        d = r["due_at"]
        d_date = d.date() if hasattr(d, "date") else None
        st = r["status"]
        if st == "COMPLETED":
            st_lbl = "مهمة منجزة"
            st_lbl_en = "Completed Task"
            color = "#10b981"
        elif st == "CANCELLED":
            st_lbl = "مهمة ملغاة"
            st_lbl_en = "Cancelled Task"
            color = "#94a3b8"
        elif d < now:
            st_lbl = "مهمة متأخرة التنفيذ"
            st_lbl_en = "Overdue Task"
            color = "#ef4444"
        elif d_date == today_date:
            st_lbl = "مستحقة اليوم"
            st_lbl_en = "Due Today"
            color = "#f59e0b"
        else:
            st_lbl = "مهمة قادمة"
            st_lbl_en = "Upcoming Task"
            color = "#3b82f6"

        events.append(AgendaCalendarItem(
            event_id=r["task_id"],
            event_type="TASK",
            event_type_label_ar="مهمة تشغيلية",
            event_type_label_en="Operational Task",
            title=r["title"] or "مهمة غير مسماة",
            event_date=d.isoformat() if hasattr(d, "isoformat") else str(d),
            lead_id=r["lead_id"],
            task_id=r["task_id"],
            opportunity_id=r["opportunity_id"],
            customer_name=r["customer_name"],
            assigned_user_id=r["assigned_user_id"],
            assigned_user_name=r["assigned_user_name"],
            branch_name=r["branch_name"],
            priority=r["priority"],
            status=st,
            status_label_ar=st_lbl,
            status_label_en=st_lbl_en,
            badge_color=color
        ))

    # 2. Viewings
    v_conds = ["v.scheduled_start IS NOT NULL"]
    if uncompleted_only:
        v_conds.append("v.status NOT IN ('COMPLETED', 'CANCELLED')")
    v_p = []
    if lead_id and opportunity_id:
        v_conds.append(f"(v.lead_id = ${len(v_p) + 1} OR v.opportunity_id = ${len(v_p) + 2})")
        v_p.extend([lead_id, opportunity_id])
    elif lead_id:
        v_conds.append(f"v.lead_id = ${len(v_p) + 1}")
        v_p.append(lead_id)
    elif opportunity_id:
        v_conds.append(f"v.opportunity_id = ${len(v_p) + 1}")
        v_p.append(opportunity_id)

    if target_user_ids:
        v_conds.append(f"v.agent_user_id = ANY(${len(v_p) + 1})")
        v_p.append(target_user_ids)
    elif target_branch_id:
        v_conds.append(f"u.branch_id = ${len(v_p) + 1}")
        v_p.append(target_branch_id)

    v_sql = f"""
        SELECT v.viewing_id, v.lead_id, v.opportunity_id, v.unit_id, un.unit_number,
               v.scheduled_start, v.scheduled_end, v.status, v.agent_user_id,
               u.full_name AS assigned_user_name, b.name AS branch_name,
               COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name
        FROM viewings v
        LEFT JOIN units un ON v.unit_id = un.unit_id
        LEFT JOIN users u ON v.agent_user_id = u.user_id
        LEFT JOIN branches b ON u.branch_id = b.branch_id
        LEFT JOIN customers c ON v.customer_id = c.customer_id
        WHERE {' AND '.join(v_conds)}
        ORDER BY v.scheduled_start DESC
        LIMIT 100
    """
    v_rows = await conn.fetch(v_sql, *v_p)
    for r in v_rows:
        d = r["scheduled_start"]
        d_date = d.date() if hasattr(d, "date") else None
        st = r["status"]
        if st == "COMPLETED":
            st_lbl = "معاينة منفذة"
            st_lbl_en = "Completed Viewing"
            color = "#10b981"
        elif st == "CANCELLED":
            st_lbl = "معاينة ملغاة"
            st_lbl_en = "Cancelled Viewing"
            color = "#94a3b8"
        elif d < now:
            st_lbl = "معاينة متأخرة التنفيذ"
            st_lbl_en = "Overdue Viewing"
            color = "#ef4444"
        elif d_date == today_date:
            st_lbl = "معاينة اليوم"
            st_lbl_en = "Today's Viewing"
            color = "#0284c7"
        else:
            st_lbl = "معاينة قادمة مجدولة"
            st_lbl_en = "Scheduled Viewing"
            color = "#0ea5e9"

        u_num = r["unit_number"]
        v_title = f"معاينة وحدة #{u_num}" if u_num else "معاينة عقار ميدانية"
        events.append(AgendaCalendarItem(
            event_id=r["viewing_id"],
            event_type="VIEWING",
            event_type_label_ar="معاينة ميدانية",
            event_type_label_en="Site Viewing",
            title=v_title,
            event_date=d.isoformat() if hasattr(d, "isoformat") else str(d),
            end_date=r["scheduled_end"].isoformat() if r["scheduled_end"] and hasattr(r["scheduled_end"], "isoformat") else None,
            lead_id=r["lead_id"],
            viewing_id=r["viewing_id"],
            opportunity_id=r["opportunity_id"],
            unit_id=r["unit_id"],
            unit_number=u_num,
            customer_name=r["customer_name"],
            assigned_user_id=r["agent_user_id"],
            assigned_user_name=r["assigned_user_name"],
            branch_name=r["branch_name"],
            status=st,
            status_label_ar=st_lbl,
            status_label_en=st_lbl_en,
            badge_color=color
        ))

    # 3. Reservations
    res_conds = ["r.expires_at IS NOT NULL"]
    if uncompleted_only:
        res_conds.append("r.status NOT IN ('CONVERTED', 'CANCELLED')")
    res_p = []
    if lead_id and opportunity_id:
        res_conds.append(f"(opp.lead_id = ${len(res_p) + 1} OR r.opportunity_id = ${len(res_p) + 2})")
        res_p.extend([lead_id, opportunity_id])
    elif lead_id:
        res_conds.append(f"opp.lead_id = ${len(res_p) + 1}")
        res_p.append(lead_id)
    elif opportunity_id:
        res_conds.append(f"r.opportunity_id = ${len(res_p) + 1}")
        res_p.append(opportunity_id)

    if target_user_ids:
        res_conds.append(f"opp.assigned_user_id = ANY(${len(res_p) + 1})")
        res_p.append(target_user_ids)
    elif target_branch_id:
        res_conds.append(f"u.branch_id = ${len(res_p) + 1}")
        res_p.append(target_branch_id)

    res_sql = f"""
        SELECT r.reservation_id, r.reservation_number, r.opportunity_id, opp.lead_id,
               r.unit_id, un.unit_number, r.reserved_at, r.expires_at, r.deposit_amount, r.status,
               opp.assigned_user_id, u.full_name AS assigned_user_name, b.name AS branch_name,
               COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name
        FROM reservations r
        LEFT JOIN opportunities opp ON r.opportunity_id = opp.opportunity_id
        LEFT JOIN units un ON r.unit_id = un.unit_id
        LEFT JOIN users u ON opp.assigned_user_id = u.user_id
        LEFT JOIN branches b ON u.branch_id = b.branch_id
        LEFT JOIN customers c ON r.customer_id = c.customer_id
        WHERE {' AND '.join(res_conds)}
        ORDER BY r.expires_at DESC
        LIMIT 100
    """
    res_rows = await conn.fetch(res_sql, *res_p)
    for r in res_rows:
        d = r["expires_at"] or r["reserved_at"]
        st = r["status"]
        if st in ("CONVERTED", "CONFIRMED"):
            st_lbl = "حجز مثبت / تحول لعقد"
            st_lbl_en = "Confirmed / Converted"
            color = "#10b981"
        elif st == "CANCELLED":
            st_lbl = "حجز ملغي"
            st_lbl_en = "Cancelled Reservation"
            color = "#94a3b8"
        elif r["expires_at"] and r["expires_at"] < now:
            st_lbl = "حجز منتهي المهلة"
            st_lbl_en = "Expired Reservation"
            color = "#dc2626"
        else:
            st_lbl = "حجز ساري ومؤقت"
            st_lbl_en = "Active Reservation"
            color = "#f59e0b"

        u_num = r["unit_number"]
        r_title = f"حجز وحدة #{u_num}" if u_num else f"حجز {r['reservation_number']}"
        events.append(AgendaCalendarItem(
            event_id=r["reservation_id"],
            event_type="RESERVATION",
            event_type_label_ar="حجز وحدة",
            event_type_label_en="Unit Reservation",
            title=r_title,
            event_date=d.isoformat() if hasattr(d, "isoformat") else str(d),
            lead_id=r["lead_id"],
            reservation_id=r["reservation_id"],
            opportunity_id=r["opportunity_id"],
            unit_id=r["unit_id"],
            unit_number=u_num,
            customer_name=r["customer_name"],
            assigned_user_id=r["assigned_user_id"],
            assigned_user_name=r["assigned_user_name"],
            branch_name=r["branch_name"],
            status=st,
            status_label_ar=st_lbl,
            status_label_en=st_lbl_en,
            badge_color=color,
            amount=float(r["deposit_amount"] or 0.0)
        ))

    # 4. Rent Collections
    rc_conds = ["rc.due_date IS NOT NULL"]
    rc_p = []
    if lead_id and opportunity_id:
        rc_conds.append(f"(ten.lead_id = ${len(rc_p) + 1} OR ten.opportunity_id = ${len(rc_p) + 2})")
        rc_p.extend([lead_id, opportunity_id])
    elif lead_id:
        rc_conds.append(f"ten.lead_id = ${len(rc_p) + 1}")
        rc_p.append(lead_id)
    elif opportunity_id:
        rc_conds.append(f"ten.opportunity_id = ${len(rc_p) + 1}")
        rc_p.append(opportunity_id)
    elif scope not in ("GLOBAL", "BRANCH"):
        rc_conds.append("1=0")

    if uncompleted_only:
        rc_conds.append("rc.status NOT IN ('PAID', 'CANCELLED')")

    rc_sql = f"""
        SELECT rc.rent_collection_id, rc.tenancy_id, ten.unit_id, un.unit_number,
               rc.due_date, rc.amount_due, rc.amount_paid, rc.status,
               COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
               ten.lead_id, ten.opportunity_id, ten.contract_number
        FROM rent_collections rc
        JOIN tenancies ten ON rc.tenancy_id = ten.tenancy_id
        LEFT JOIN units un ON ten.unit_id = un.unit_id
        LEFT JOIN customers c ON ten.tenant_customer_id = c.customer_id
        WHERE {' AND '.join(rc_conds)}
        ORDER BY rc.due_date DESC
        LIMIT 50
    """
    rc_rows = await conn.fetch(rc_sql, *rc_p)
    for r in rc_rows:
        d = r["due_date"]
        st = r["status"]
        if st == "PAID":
            st_lbl = "دفعة إيجار محصلة"
            st_lbl_en = "Collected Rent"
            color = "#10b981"
        elif d < today_date:
            st_lbl = "دفعة إيجار متأخرة"
            st_lbl_en = "Overdue Rent"
            color = "#ef4444"
        else:
            st_lbl = "دفعة إيجار مستحقة"
            st_lbl_en = "Due Rent"
            color = "#7c3aed"

        u_num = r["unit_number"]
        con_no = r["contract_number"]
        events.append(AgendaCalendarItem(
            event_id=r["rent_collection_id"],
            event_type="RENT_COLLECTION",
            event_type_label_ar="تحصيل إيجاري",
            event_type_label_en="Rent Collection",
            title=f"استحقاق إيجار ({con_no}) وحدة #{u_num}" if con_no else (f"استحقاق إيجار وحدة #{u_num}" if u_num else f"دفعة إيجار {r['rent_collection_id']}"),
            event_date=d.isoformat() if hasattr(d, "isoformat") else str(d),
            lead_id=r["lead_id"],
            opportunity_id=r["opportunity_id"],
            unit_id=r["unit_id"],
            unit_number=u_num,
            customer_name=r["customer_name"],
            status=st,
            status_label_ar=st_lbl,
            status_label_en=st_lbl_en,
            badge_color=color,
            amount=float(r["amount_due"] or 0.0)
        ))

    # 5. Maintenance Orders
    if scope in ("GLOBAL", "BRANCH") and not lead_id and not opportunity_id:
        mwo_conds = ["COALESCE(tick.due_at, mwo.completed_at, tick.opened_at) IS NOT NULL"]
        if uncompleted_only:
            mwo_conds.append("mwo.status NOT IN ('COMPLETED', 'CANCELLED')")
        mwo_sql = f"""
            SELECT mwo.work_order_id, mwo.ticket_id, tick.unit_id, un.unit_number,
                   COALESCE(tick.due_at, mwo.completed_at, tick.opened_at) AS event_date,
                   mwo.status, mwo.total_amount, tick.category
            FROM maintenance_work_orders mwo
            JOIN maintenance_tickets tick ON mwo.ticket_id = tick.ticket_id
            LEFT JOIN units un ON tick.unit_id = un.unit_id
            WHERE {' AND '.join(mwo_conds)}
            ORDER BY event_date DESC
            LIMIT 30
        """
        mwo_rows = await conn.fetch(mwo_sql)
        for r in mwo_rows:
            d = r["event_date"]
            if not d:
                continue
            st = r["status"]
            if st == "COMPLETED":
                st_lbl = "صيانة مكتملة"
                st_lbl_en = "Completed Maintenance"
                color = "#10b981"
            elif st == "IN_PROGRESS":
                st_lbl = "صيانة قيد التنفيذ"
                st_lbl_en = "In Progress Maintenance"
                color = "#0284c7"
            else:
                st_lbl = "أمر صيانة معتمد"
                st_lbl_en = "Approved Maintenance"
                color = "#d97706"

            events.append(AgendaCalendarItem(
                event_id=r["work_order_id"],
                event_type="MAINTENANCE",
                event_type_label_ar="أمر صيانة",
                event_type_label_en="Maintenance Order",
                title=f"صيانة: {r['category'] or 'عامة'} - وحدة #{r['unit_number'] or ''}",
                event_date=d.isoformat() if hasattr(d, "isoformat") else str(d),
                ticket_id=r["ticket_id"],
                work_order_id=r["work_order_id"],
                unit_id=r["unit_id"],
                unit_number=r["unit_number"],
                status=st,
                status_label_ar=st_lbl,
                status_label_en=st_lbl_en,
                badge_color=color,
                amount=float(r["total_amount"] or 0.0)
            ))

    # 6. Campaigns
    if scope in ("GLOBAL", "BRANCH") and not lead_id and not opportunity_id:
        camp_conds = ["(camp.start_date IS NOT NULL OR camp.end_date IS NOT NULL)"]
        if uncompleted_only:
            camp_conds.append("camp.status NOT IN ('COMPLETED', 'CANCELLED')")
        camp_sql = f"""
            SELECT camp.campaign_id, camp.name, camp.budget, camp.status,
               camp.start_date, camp.end_date
            FROM campaigns camp
            WHERE {' AND '.join(camp_conds)}
            ORDER BY camp.start_date DESC
            LIMIT 20
        """
        camp_rows = await conn.fetch(camp_sql)
        for r in camp_rows:
            d = r["start_date"] or r["end_date"]
            st = r["status"]
            events.append(AgendaCalendarItem(
                event_id=r["campaign_id"],
                event_type="CAMPAIGN",
                event_type_label_ar="حملة تسويقية",
                event_type_label_en="Marketing Campaign",
                title=f"حملة: {r['name']}",
                event_date=d.isoformat() if hasattr(d, "isoformat") else str(d),
                end_date=r["end_date"].isoformat() if r["end_date"] and hasattr(r["end_date"], "isoformat") else None,
                status=st,
                status_label_ar="حملة نشطة" if st == "ACTIVE" else "حملة مكتملة",
                status_label_en="Active Campaign" if st == "ACTIVE" else "Completed Campaign",
                badge_color="#8b5cf6" if st == "ACTIVE" else "#64748b",
                amount=float(r["budget"] or 0.0)
            ))

    # Sort descending by date
    events.sort(key=lambda x: str(x.event_date), reverse=True)

    if event_type and event_type.upper() != "ALL":
        events = [e for e in events if e.event_type == event_type.upper()]

    def _is_ov(e):
        return "متأخر" in (e.status_label_ar or "") or e.badge_color in ("#ef4444", "#dc2626")

    def _is_td(e):
        return not _is_ov(e) and ("اليوم" in (e.status_label_ar or ""))

    def _is_up(e):
        return not _is_ov(e) and not _is_td(e) and ("قادم" in (e.status_label_ar or "") or "ساري" in (e.status_label_ar or "") or "مستحق" in (e.status_label_ar or "") or "قيد" in (e.status_label_ar or ""))

    summary = AgendaCalendarSummary(
        total_events=len(events),
        tasks_count=sum(1 for e in events if e.event_type == "TASK"),
        viewings_count=sum(1 for e in events if e.event_type == "VIEWING"),
        reservations_count=sum(1 for e in events if e.event_type == "RESERVATION"),
        collections_count=sum(1 for e in events if e.event_type == "RENT_COLLECTION"),
        maintenance_count=sum(1 for e in events if e.event_type == "MAINTENANCE"),
        campaigns_count=sum(1 for e in events if e.event_type == "CAMPAIGN"),
        overdue_count=sum(1 for e in events if _is_ov(e)),
        today_count=sum(1 for e in events if _is_td(e)),
        upcoming_count=sum(1 for e in events if _is_up(e))
    )

    if timing_filter and timing_filter.upper() != "ALL":
        tf = timing_filter.upper()
        if tf == "OVERDUE":
            events = [e for e in events if _is_ov(e)]
        elif tf == "TODAY":
            events = [e for e in events if _is_td(e)]
        elif tf == "UPCOMING":
            events = [e for e in events if _is_up(e)]

    scope_info = ScopeInfo(
        scope=scope,
        branch_id=target_branch_id,
        branch_name=branch_name,
        user_id=user_id if scope == "OWN" else None,
        user_name=user_name if scope == "OWN" else None
    )

    return ResponseEnvelope(
        data=AgendaCalendarResponse(
            summary=summary,
            scope_info=scope_info,
            events=events
        ),
        meta=BaseMeta()
    )


# =====================================================================
# 2. FINANCIAL DUES & COLLECTIONS SCHEDULE (مفكرة وجدول المبالغ والتحصيلات)
# =====================================================================
@router.get("/financial-schedule", response_model=ResponseEnvelope[FinancialScheduleResponse])
async def get_financial_schedule(
    scope: str = Query("GLOBAL", pattern="^(GLOBAL|BRANCH|TEAM|OWN)$"),
    branch_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    lead_id: Optional[str] = Query(None, description="Filter financial dues by lead ID"),
    opportunity_id: Optional[str] = Query(None, description="Filter financial dues by opportunity ID"),
    category: Optional[str] = Query(None),  # ALL, DEALS_LEADS, PROPERTY_MANAGEMENT, MARKETING
    collection_status: Optional[str] = Query(None),  # ALL, COLLECTED, PENDING, OVERDUE, CANCELLED
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    conn: asyncpg.Connection = Depends(get_db)
):
    """
    Returns an itemized financial dues and collections schedule classified by:
    - Deal / Lead ID (Invoices, Brokerage Commissions, Reservation Araboun)
    - Property Management Tasks (Periodic Rent Collections, Work Order Costs)
    - Marketing Campaigns Tasks (Campaign Budget & Ad Spend)
    Displays collection status indicators and due/collection dates clearly.
    """
    if x_user_id:
        roles_rows = await conn.fetch("""
            SELECT r.role_code FROM user_roles ur
            JOIN roles r ON ur.role_id = r.role_id
            WHERE ur.user_id = $1
        """, x_user_id)
        role_codes = [r["role_code"] for r in roles_rows]
        user_scope = resolve_user_data_scope(role_codes)
        if user_scope == "OWN":
            scope = "OWN"
            user_id = x_user_id
            branch_id = None
        elif user_scope == "BRANCH":
            user_branch = await conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", x_user_id)
            branch_id = user_branch
            if user_id:
                agent_branch = await conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", user_id)
                if agent_branch == user_branch:
                    scope = "OWN"
                else:
                    user_id = None
                    scope = "BRANCH"
            else:
                scope = "BRANCH"

    target_user_ids: Optional[List[str]] = None
    target_branch_id: Optional[str] = branch_id
    branch_name: Optional[str] = None
    user_name: Optional[str] = None

    if user_id:
        u_row = await conn.fetchrow("""
            SELECT u.user_id, u.full_name, u.branch_id, b.name AS branch_name
            FROM users u
            LEFT JOIN branches b ON u.branch_id = b.branch_id
            WHERE u.user_id = $1
        """, user_id)
        if u_row:
            user_name = u_row["full_name"]
            if not target_branch_id:
                target_branch_id = u_row["branch_id"]
                branch_name = u_row["branch_name"]

    if scope == "OWN":
        if not user_id:
            user_id = await conn.fetchval("SELECT user_id FROM users WHERE status = 'ACTIVE' ORDER BY user_id ASC LIMIT 1")
        u_row = await conn.fetchrow("SELECT full_name, branch_id FROM users WHERE user_id = $1", user_id)
        user_name = u_row["full_name"] if u_row else user_id
        target_user_ids = [user_id]
        target_branch_id = None
    elif scope == "TEAM":
        if not user_id:
            user_id = await conn.fetchval("SELECT user_id FROM users WHERE status = 'ACTIVE' ORDER BY user_id ASC LIMIT 1")
        team_rows = await conn.fetch("""
            WITH RECURSIVE subordinates AS (
                SELECT user_id FROM users WHERE user_id = $1 OR manager_user_id = $1
                UNION
                SELECT u.user_id FROM users u
                INNER JOIN subordinates s ON s.user_id = u.manager_user_id
            )
            SELECT user_id FROM subordinates
        """, user_id)
        target_user_ids = [tr["user_id"] for tr in team_rows] or [user_id]
    elif scope == "BRANCH":
        if not target_branch_id:
            target_branch_id = await conn.fetchval("SELECT branch_id FROM branches WHERE status = 'ACTIVE' ORDER BY branch_id LIMIT 1")
        b_users = await conn.fetch("SELECT user_id FROM users WHERE branch_id = $1", target_branch_id)
        target_user_ids = [r["user_id"] for r in b_users]
        if not branch_name:
            branch_name = await conn.fetchval("SELECT name FROM branches WHERE branch_id = $1", target_branch_id)
    elif scope == "GLOBAL":
        target_user_ids = None
        target_branch_id = None

    now = datetime.now(timezone.utc)
    today_date = now.date()
    items: List[FinancialScheduleItem] = []

    # 1. Invoices (DEALS_LEADS)
    inv_conds = ["1=1"]
    inv_p = []
    if lead_id and opportunity_id:
        inv_conds.append(f"(inv.lead_id = ${len(inv_p) + 1} OR inv.opportunity_id = ${len(inv_p) + 2})")
        inv_p.extend([lead_id, opportunity_id])
    elif lead_id:
        inv_conds.append(f"inv.lead_id = ${len(inv_p) + 1}")
        inv_p.append(lead_id)
    elif opportunity_id:
        inv_conds.append(f"inv.opportunity_id = ${len(inv_p) + 1}")
        inv_p.append(opportunity_id)

    if target_user_ids:
        inv_conds.append(f"l.assigned_user_id = ANY(${len(inv_p) + 1})")
        inv_p.append(target_user_ids)
    elif target_branch_id:
        inv_conds.append(f"u.branch_id = ${len(inv_p) + 1}")
        inv_p.append(target_branch_id)

    inv_sql = f"""
        SELECT inv.invoice_id, inv.invoice_number, inv.invoice_type, inv.lead_id, inv.opportunity_id,
               inv.unit_id, un.unit_number, inv.total_amount, inv.amount_paid, inv.status,
               inv.due_date, inv.paid_at,
               COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
               u.full_name AS assigned_user_name, b.name AS branch_name
        FROM invoices inv
        LEFT JOIN units un ON inv.unit_id = un.unit_id
        LEFT JOIN customers c ON inv.payer_customer_id = c.customer_id
        LEFT JOIN leads l ON inv.lead_id = l.lead_id
        LEFT JOIN users u ON l.assigned_user_id = u.user_id
        LEFT JOIN branches b ON u.branch_id = b.branch_id
        WHERE {' AND '.join(inv_conds)}
        ORDER BY inv.created_at DESC
        LIMIT 100
    """
    inv_rows = await conn.fetch(inv_sql, *inv_p)
    for r in inv_rows:
        tot = float(r["total_amount"] or 0.0)
        pd = float(r["amount_paid"] or 0.0)
        rem = max(0.0, tot - pd)
        d_date = r["due_date"]
        st = r["status"]
        days_over = 0

        if st == "PAID" or pd >= tot:
            c_st = "COLLECTED"
            c_lbl = "تم التحصيل"
            c_lbl_en = "Fully Collected"
            c_col = "#10b981"
        elif st == "CANCELLED":
            c_st = "CANCELLED"
            c_lbl = "فاتورة ملغاة"
            c_lbl_en = "Cancelled Invoice"
            c_col = "#94a3b8"
        elif d_date and d_date < today_date:
            c_st = "OVERDUE"
            days_over = (today_date - d_date).days
            c_lbl = f"متأخرة عن السداد ({days_over} يوم)"
            c_lbl_en = f"Overdue Payment ({days_over}d)"
            c_col = "#ef4444"
        else:
            c_st = "PENDING"
            c_lbl = "معلقة / بانتظار التحصيل"
            c_lbl_en = "Pending Collection"
            c_col = "#f59e0b"

        inv_type_lbl = "فاتورة ضريبية وسعي" if r["invoice_type"] == "TAX_INVOICE" else "فاتورة خدمات وساطة"
        inv_type_lbl_en = "Brokerage Tax Invoice" if r["invoice_type"] == "TAX_INVOICE" else "Brokerage Service Invoice"
        items.append(FinancialScheduleItem(
            item_id=r["invoice_id"],
            category="DEALS_LEADS",
            category_label_ar="الصفقات والطلبات",
            category_label_en="Sales & Deals",
            item_type_code="INVOICE",
            item_type="INVOICE",
            item_type_label_ar=inv_type_lbl,
            item_type_label_en=inv_type_lbl_en,
            title=f"فاتورة {r['invoice_number']}",
            lead_id=r["lead_id"],
            opportunity_id=r["opportunity_id"],
            unit_id=r["unit_id"],
            unit_number=r["unit_number"],
            customer_name=r["customer_name"],
            amount=tot,
            amount_paid=pd,
            amount_remaining=rem,
            collection_status=c_st,
            collection_status_ar=c_lbl,
            collection_status_en=c_lbl_en,
            badge_color=c_col,
            due_date=d_date.isoformat() if hasattr(d_date, "isoformat") else str(d_date) if d_date else None,
            collected_at=r["paid_at"].isoformat() if r["paid_at"] and hasattr(r["paid_at"], "isoformat") else None,
            assigned_user_name=r["assigned_user_name"],
            branch_name=r["branch_name"],
            days_overdue=days_over
        ))

    # 2. Reservation Deposits (DEALS_LEADS)
    res_conds = ["r.deposit_amount > 0"]
    res_p = []
    if lead_id and opportunity_id:
        res_conds.append(f"(opp.lead_id = ${len(res_p) + 1} OR r.opportunity_id = ${len(res_p) + 2})")
        res_p.extend([lead_id, opportunity_id])
    elif lead_id:
        res_conds.append(f"opp.lead_id = ${len(res_p) + 1}")
        res_p.append(lead_id)
    elif opportunity_id:
        res_conds.append(f"r.opportunity_id = ${len(res_p) + 1}")
        res_p.append(opportunity_id)

    if target_user_ids:
        res_conds.append(f"opp.assigned_user_id = ANY(${len(res_p) + 1})")
        res_p.append(target_user_ids)
    elif target_branch_id:
        res_conds.append(f"u.branch_id = ${len(res_p) + 1}")
        res_p.append(target_branch_id)

    res_sql = f"""
        SELECT r.reservation_id, r.reservation_number, r.opportunity_id, opp.lead_id,
               r.unit_id, un.unit_number, r.deposit_amount, r.status,
               r.reserved_at, r.expires_at,
               COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
               u.full_name AS assigned_user_name, b.name AS branch_name
        FROM reservations r
        LEFT JOIN opportunities opp ON r.opportunity_id = opp.opportunity_id
        LEFT JOIN units un ON r.unit_id = un.unit_id
        LEFT JOIN customers c ON r.customer_id = c.customer_id
        LEFT JOIN users u ON opp.assigned_user_id = u.user_id
        LEFT JOIN branches b ON u.branch_id = b.branch_id
        WHERE {' AND '.join(res_conds)}
        ORDER BY r.reserved_at DESC
        LIMIT 100
    """
    res_rows = await conn.fetch(res_sql, *res_p)
    for r in res_rows:
        tot = float(r["deposit_amount"] or 0.0)
        st = r["status"]
        exp = r["expires_at"]
        days_over = 0

        if st in ("CONVERTED", "CONFIRMED"):
            c_st = "COLLECTED"
            c_lbl = "عربون محصل ومثبت"
            c_lbl_en = "Deposit Confirmed"
            c_col = "#10b981"
            pd = tot
            rem = 0.0
            coll_date = r["reserved_at"]
        elif st == "CANCELLED":
            c_st = "CANCELLED"
            c_lbl = "عربون مسترد / ملغي"
            c_lbl_en = "Deposit Cancelled / Refunded"
            c_col = "#94a3b8"
            pd = 0.0
            rem = 0.0
            coll_date = None
        elif exp and exp < now:
            c_st = "OVERDUE"
            days_over = (now.date() - exp.date()).days
            c_lbl = f"عربون منتهي المهلة ({days_over} يوم)"
            c_lbl_en = f"Deposit Expired ({days_over}d)"
            c_col = "#dc2626"
            pd = 0.0
            rem = tot
            coll_date = None
        else:
            c_st = "PENDING"
            c_lbl = "عربون قيد الاستلام / حجز ساري"
            c_lbl_en = "Active Reservation Deposit"
            c_col = "#f59e0b"
            pd = 0.0
            rem = tot
            coll_date = None

        u_num = r["unit_number"]
        items.append(FinancialScheduleItem(
            item_id=r["reservation_id"],
            category="DEALS_LEADS",
            category_label_ar="الصفقات والطلبات",
            category_label_en="Sales & Deals",
            item_type_code="RESERVATION_DEPOSIT",
            item_type="RESERVATION_DEPOSIT",
            item_type_label_ar="عربون حجز صفقة",
            item_type_label_en="Reservation Deposit",
            title=f"عربون حجز وحدة #{u_num}" if u_num else f"عربون {r['reservation_number']}",
            lead_id=r["lead_id"],
            opportunity_id=r["opportunity_id"],
            unit_id=r["unit_id"],
            unit_number=u_num,
            customer_name=r["customer_name"],
            amount=tot,
            amount_paid=pd,
            amount_remaining=rem,
            collection_status=c_st,
            collection_status_ar=c_lbl,
            collection_status_en=c_lbl_en,
            badge_color=c_col,
            due_date=exp.isoformat() if exp and hasattr(exp, "isoformat") else None,
            collected_at=coll_date.isoformat() if coll_date and hasattr(coll_date, "isoformat") else None,
            assigned_user_name=r["assigned_user_name"],
            branch_name=r["branch_name"],
            days_overdue=days_over
        ))

    # 2.b Sales Contract Payments (DEALS_LEADS)
    pay_conds = ["p.due_date IS NOT NULL"]
    pay_p = []
    pay_deal_specific = False
    if lead_id and opportunity_id:
        pay_conds.append(f"(c.lead_id = ${len(pay_p) + 1} OR c.opportunity_id = ${len(pay_p) + 2})")
        pay_p.extend([lead_id, opportunity_id])
        pay_deal_specific = True
    elif lead_id:
        pay_conds.append(f"c.lead_id = ${len(pay_p) + 1}")
        pay_p.append(lead_id)
        pay_deal_specific = True
    elif opportunity_id:
        pay_conds.append(f"c.opportunity_id = ${len(pay_p) + 1}")
        pay_p.append(opportunity_id)
        pay_deal_specific = True
    elif scope not in ("GLOBAL", "BRANCH"):
        pay_conds.append("1=0")

    pay_sql = f"""
        SELECT p.payment_id, p.contract_id, c.contract_number,
               COALESCE(cust.first_name || ' ' || cust.last_name, cust.company_name) AS customer_name,
               p.payment_reference, p.due_date,
               CAST(p.amount_due AS FLOAT) AS amount_due,
               CAST(p.amount_paid AS FLOAT) AS amount_paid,
               p.status, p.paid_at, u.unit_number,
               c.lead_id, c.opportunity_id
        FROM payments p
        JOIN contracts c ON p.contract_id = c.contract_id
        LEFT JOIN reservations r ON c.reservation_id = r.reservation_id
        LEFT JOIN customers cust ON r.customer_id = cust.customer_id
        LEFT JOIN units u ON r.unit_id = u.unit_id
        WHERE {' AND '.join(pay_conds)}
        ORDER BY p.due_date DESC NULLS LAST
        LIMIT 100
    """
    pay_rows = await conn.fetch(pay_sql, *pay_p)
    for r in pay_rows:
        tot = float(r["amount_due"] or 0.0)
        pd = float(r["amount_paid"] or 0.0)
        rem = max(0.0, tot - pd)
        d_date = r["due_date"]
        st = r["status"]
        days_over = 0

        if st == "PAID" or pd >= tot:
            c_st = "COLLECTED"
            c_lbl = "تم السداد"
            c_lbl_en = "Payment Collected"
            c_col = "#10b981"
        elif d_date and d_date < today_date:
            c_st = "OVERDUE"
            days_over = (today_date - d_date).days
            c_lbl = f"دفعة متأخرة ({days_over} يوم)"
            c_lbl_en = f"Overdue Payment ({days_over}d)"
            c_col = "#ef4444"
        else:
            c_st = "PENDING"
            c_lbl = "دفعة مستحقة"
            c_lbl_en = "Upcoming Due"
            c_col = "#f59e0b"

        u_num = r["unit_number"]
        con_no = r["contract_number"]
        items.append(FinancialScheduleItem(
            item_id=r["payment_id"],
            category="DEALS_LEADS",
            category_label_ar="الصفقات والطلبات",
            category_label_en="Sales & Deals",
            item_type_code="PAYMENT_SCHEDULE",
            item_type="PAYMENT_SCHEDULE",
            item_type_label_ar="دفعة عقد بيع",
            item_type_label_en="Sales Contract Payment",
            title=f"دفعة عقد ({con_no}) - وحدة #{u_num}" if con_no else (f"دفعة وحدة #{u_num}" if u_num else f"دفعة {r['payment_reference'] or r['payment_id']}"),
            lead_id=r["lead_id"],
            opportunity_id=r["opportunity_id"],
            unit_id=None,
            unit_number=u_num,
            customer_name=r["customer_name"],
            amount=tot,
            amount_paid=pd,
            amount_remaining=rem,
            collection_status=c_st,
            collection_status_ar=c_lbl,
            collection_status_en=c_lbl_en,
            badge_color=c_col,
            due_date=d_date.isoformat() if hasattr(d_date, "isoformat") else str(d_date),
            collected_at=r["paid_at"].isoformat() if r["paid_at"] and hasattr(r["paid_at"], "isoformat") else None,
            days_overdue=days_over
        ))

    # 3. Rent Collections (DEALS_LEADS / PROPERTY_MANAGEMENT)
    rc_conds = ["rc.due_date IS NOT NULL"]
    rc_p = []
    is_deal_specific = False
    if lead_id and opportunity_id:
        rc_conds.append(f"(ten.lead_id = ${len(rc_p) + 1} OR ten.opportunity_id = ${len(rc_p) + 2})")
        rc_p.extend([lead_id, opportunity_id])
        is_deal_specific = True
    elif lead_id:
        rc_conds.append(f"ten.lead_id = ${len(rc_p) + 1}")
        rc_p.append(lead_id)
        is_deal_specific = True
    elif opportunity_id:
        rc_conds.append(f"ten.opportunity_id = ${len(rc_p) + 1}")
        rc_p.append(opportunity_id)
        is_deal_specific = True
    elif scope not in ("GLOBAL", "BRANCH"):
        rc_conds.append("1=0")

    rc_sql = f"""
        SELECT rc.rent_collection_id, rc.tenancy_id, ten.unit_id, un.unit_number,
               rc.due_date, rc.amount_due, rc.amount_paid, rc.paid_at, rc.status,
               COALESCE(c.first_name || ' ' || c.last_name, c.company_name) AS customer_name,
               ten.lead_id, ten.opportunity_id, ten.contract_number
        FROM rent_collections rc
        JOIN tenancies ten ON rc.tenancy_id = ten.tenancy_id
        LEFT JOIN units un ON ten.unit_id = un.unit_id
        LEFT JOIN customers c ON ten.tenant_customer_id = c.customer_id
        WHERE {' AND '.join(rc_conds)}
        ORDER BY rc.due_date DESC
        LIMIT 100
    """
    rc_rows = await conn.fetch(rc_sql, *rc_p)
    for r in rc_rows:
        tot = float(r["amount_due"] or 0.0)
        pd = float(r["amount_paid"] or 0.0)
        rem = max(0.0, tot - pd)
        d_date = r["due_date"]
        st = r["status"]
        days_over = 0

        if st == "PAID" or pd >= tot:
            c_st = "COLLECTED"
            c_lbl = "تم التحصيل"
            c_lbl_en = "Rent Collected"
            c_col = "#10b981"
        elif d_date and d_date < today_date:
            c_st = "OVERDUE"
            days_over = (today_date - d_date).days
            c_lbl = f"متأخرة عن السداد ({days_over} يوم)"
            c_lbl_en = f"Overdue Rent ({days_over}d)"
            c_col = "#ef4444"
        else:
            c_st = "PENDING"
            c_lbl = "مستحقة قريباً"
            c_lbl_en = "Upcoming Rent Due"
            c_col = "#f59e0b"

        u_num = r["unit_number"]
        con_no = r["contract_number"]
        cat = "DEALS_LEADS" if (is_deal_specific or r["lead_id"] or r["opportunity_id"]) else "PROPERTY_MANAGEMENT"
        cat_ar = "الصفقات والطلبات" if cat == "DEALS_LEADS" else "إدارة الأملاك"
        cat_en = "Sales & Deals" if cat == "DEALS_LEADS" else "Property Management"
        items.append(FinancialScheduleItem(
            item_id=r["rent_collection_id"],
            category=cat,
            category_label_ar=cat_ar,
            category_label_en=cat_en,
            item_type_code="RENT_COLLECTION",
            item_type="RENT_COLLECTION",
            item_type_label_ar="قسط إيجار تعاقدي",
            item_type_label_en="Rent Installment",
            title=f"قسط إيجار ({con_no}) - وحدة #{u_num}" if con_no else (f"إيجار وحدة #{u_num}" if u_num else f"تحصيل {r['rent_collection_id']}"),
            lead_id=r["lead_id"],
            opportunity_id=r["opportunity_id"],
            unit_id=r["unit_id"],
            unit_number=u_num,
            customer_name=r["customer_name"],
            amount=tot,
            amount_paid=pd,
            amount_remaining=rem,
            collection_status=c_st,
            collection_status_ar=c_lbl,
            collection_status_en=c_lbl_en,
            badge_color=c_col,
            due_date=d_date.isoformat() if hasattr(d_date, "isoformat") else str(d_date),
            collected_at=r["paid_at"].isoformat() if r["paid_at"] and hasattr(r["paid_at"], "isoformat") else None,
            days_overdue=days_over
        ))

    # 4. Maintenance Work Orders (PROPERTY_MANAGEMENT)
    if scope in ("GLOBAL", "BRANCH") and not lead_id and not opportunity_id:
        mwo_sql = """
            SELECT mwo.work_order_id, mwo.ticket_id, tick.unit_id, un.unit_number,
                   mwo.total_amount, mwo.approved_amount, mwo.status,
                   mwo.completed_at, tick.due_at, tick.category
            FROM maintenance_work_orders mwo
            JOIN maintenance_tickets tick ON mwo.ticket_id = tick.ticket_id
            LEFT JOIN units un ON tick.unit_id = un.unit_id
            ORDER BY mwo.work_order_id DESC
            LIMIT 50
        """
        mwo_rows = await conn.fetch(mwo_sql)
        for r in mwo_rows:
            tot = float(r["total_amount"] or r["approved_amount"] or 0.0)
            st = r["status"]
            if st == "COMPLETED":
                c_st = "COLLECTED"
                c_lbl = "مسدد ومنجز"
                c_lbl_en = "Paid & Completed"
                c_col = "#10b981"
                pd = tot
                rem = 0.0
            elif st == "CANCELLED":
                c_st = "CANCELLED"
                c_lbl = "ملغي"
                c_lbl_en = "Cancelled"
                c_col = "#94a3b8"
                pd = 0.0
                rem = 0.0
            else:
                c_st = "PENDING"
                c_lbl = "قيد التنفيذ / مستحق"
                c_lbl_en = "In Progress / Due"
                c_col = "#f59e0b"
                pd = 0.0
                rem = tot

            u_num = r["unit_number"]
            items.append(FinancialScheduleItem(
                item_id=r["work_order_id"],
                category="PROPERTY_MANAGEMENT",
                category_label_ar="إدارة الأملاك",
                category_label_en="Property Management",
                item_type_code="MAINTENANCE_ORDER",
                item_type="MAINTENANCE_ORDER",
                item_type_label_ar="أمر عمل صيانة",
                item_type_label_en="Work Order Cost",
                title=f"صيانة: {r['category'] or 'عامة'} وحدة #{u_num or ''}",
                ticket_id=r["ticket_id"],
                work_order_id=r["work_order_id"],
                unit_id=r["unit_id"],
                unit_number=u_num,
                amount=tot,
                amount_paid=pd,
                amount_remaining=rem,
                collection_status=c_st,
                collection_status_ar=c_lbl,
                collection_status_en=c_lbl_en,
                badge_color=c_col,
                due_date=r["due_at"].isoformat() if r["due_at"] and hasattr(r["due_at"], "isoformat") else None,
                collected_at=r["completed_at"].isoformat() if r["completed_at"] and hasattr(r["completed_at"], "isoformat") else None
            ))

    # 5. Marketing Campaigns (MARKETING)
    if scope in ("GLOBAL", "BRANCH") and not lead_id and not opportunity_id:
        camp_sql = """
            SELECT camp.campaign_id, camp.name, camp.budget, camp.status,
                   camp.start_date, camp.end_date
            FROM campaigns camp
            ORDER BY camp.start_date DESC
            LIMIT 20
        """
        camp_rows = await conn.fetch(camp_sql)
        for r in camp_rows:
            tot = float(r["budget"] or 0.0)
            st = r["status"]
            if st == "COMPLETED":
                c_st = "COLLECTED"
                c_lbl = "مصروفة ومنفذة"
                c_lbl_en = "Disbursed & Executed"
                c_col = "#10b981"
                pd = tot
                rem = 0.0
            else:
                c_st = "PENDING"
                c_lbl = "ميزانية معتمدة جارية"
                c_lbl_en = "Approved Active Budget"
                c_col = "#f59e0b"
                pd = 0.0
                rem = tot

            items.append(FinancialScheduleItem(
                item_id=r["campaign_id"],
                category="MARKETING",
                category_label_ar="الحملات الإعلانية",
                category_label_en="Marketing & Ads",
                item_type_code="CAMPAIGN_BUDGET",
                item_type="CAMPAIGN_BUDGET",
                item_type_label_ar="ميزانية حملة إعلانية",
                item_type_label_en="Campaign Budget",
                title=f"حملة: {r['name']}",
                amount=tot,
                amount_paid=pd,
                amount_remaining=rem,
                collection_status=c_st,
                collection_status_ar=c_lbl,
                collection_status_en=c_lbl_en,
                badge_color=c_col,
                due_date=r["end_date"].isoformat() if r["end_date"] and hasattr(r["end_date"], "isoformat") else None
            ))

    # Sort items by due_date: nearest due date first (ascending: earliest/overdue first, nulls at end)
    def sort_due_key(item):
        d = item.due_date
        if not d:
            return (1, "9999-12-31")
        d_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
        return (0, d_str)

    items.sort(key=sort_due_key)

    # Filter by category if requested
    if category and category.upper() != "ALL":
        items = [i for i in items if i.category == category.upper()]

    # Filter by collection_status if requested
    if collection_status and collection_status.upper() != "ALL":
        items = [i for i in items if i.collection_status == collection_status.upper()]

    tot_dues = sum(i.amount for i in items)
    tot_coll = sum(i.amount_paid for i in items)
    tot_pend = sum(i.amount_remaining for i in items if i.collection_status == "PENDING")
    tot_over = sum(i.amount_remaining for i in items if i.collection_status == "OVERDUE")
    rate_pct = round((tot_coll / tot_dues * 100.0), 2) if tot_dues > 0 else 0.0

    summary = FinancialScheduleSummary(
        total_dues_amount=tot_dues,
        total_collected_amount=tot_coll,
        total_pending_amount=tot_pend,
        total_overdue_amount=tot_over,
        collection_rate_percent=rate_pct,
        deals_leads_count=sum(1 for i in items if i.category == "DEALS_LEADS"),
        property_management_count=sum(1 for i in items if i.category == "PROPERTY_MANAGEMENT"),
        marketing_count=sum(1 for i in items if i.category == "MARKETING"),
        total_items=len(items)
    )

    scope_info = ScopeInfo(
        scope=scope,
        branch_id=target_branch_id,
        branch_name=branch_name,
        user_id=user_id if scope == "OWN" else None,
        user_name=user_name if scope == "OWN" else None
    )

    return ResponseEnvelope(
        data=FinancialScheduleResponse(
            summary=summary,
            scope_info=scope_info,
            items=items
        ),
        meta=BaseMeta()
    )



