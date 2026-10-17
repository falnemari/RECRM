from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, Header
import asyncpg
from app.database import get_db
from app.routers.auth import resolve_user_data_scope
from app.schemas.common import ResponseEnvelope, BaseMeta
from app.schemas.reports import (
    ExecutiveDashboard, ExecutiveKPIs, StatusBreakdown,
    MultiTierDashboardOut, FunnelKPIs, ScopeInfo,
    BranchFunnelItem, AgentFunnelItem, OpportunityFunnelItem,
    LivePulseEvent, DrilldownData
)

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
        elif user_scope == "BRANCH" and scope == "GLOBAL":
            scope = "BRANCH"
            if not branch_id:
                branch_id = await conn.fetchval("SELECT branch_id FROM users WHERE user_id = $1", x_user_id)
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
        qualified_leads = await conn.fetchval(f"SELECT count(*) FROM leads l WHERE l.status = 'QUALIFIED' AND {lead_condition}", *lead_params)


        # Opportunities
        open_opps = await conn.fetchval("""
            SELECT count(*) FROM opportunities 
            WHERE stage NOT IN ('CLOSED_WON', 'CLOSED_LOST') 
              AND assigned_user_id = ANY($1)
        """, target_user_ids)

        # Viewings (from viewings table and activities table)
        v_tbl_cnt = await conn.fetchval("""
            SELECT count(*) FROM viewings 
            WHERE agent_user_id = ANY($1)
        """, target_user_ids) or 0
        v_act_cnt = await conn.fetchval("""
            SELECT count(*) FROM activities a
            JOIN activity_types at ON a.activity_type_id = at.activity_type_id
            WHERE at.code = 'VIEWING' AND a.user_id = ANY($1)
        """, target_user_ids) or 0
        viewings_cnt = v_tbl_cnt + v_act_cnt

        # Offers
        offers_cnt = await conn.fetchval("""
            SELECT count(*) FROM offers ofr
            JOIN opportunities o ON ofr.opportunity_id = o.opportunity_id
            WHERE o.assigned_user_id = ANY($1)
        """, target_user_ids)

        # Reservations
        reservations_cnt = await conn.fetchval("""
            SELECT count(*) FROM reservations r
            JOIN opportunities o ON r.opportunity_id = o.opportunity_id
            WHERE r.status IN ('ACTIVE', 'CONFIRMED')
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
        qualified_leads = await conn.fetchval("SELECT count(*) FROM leads WHERE status = 'QUALIFIED'")
        open_opps = await conn.fetchval("SELECT count(*) FROM opportunities WHERE stage NOT IN ('CLOSED_WON', 'CLOSED_LOST')")
        v_tbl_cnt = await conn.fetchval("SELECT count(*) FROM viewings") or 0
        v_act_cnt = await conn.fetchval("""
            SELECT count(*) FROM activities a
            JOIN activity_types at ON a.activity_type_id = at.activity_type_id
            WHERE at.code = 'VIEWING'
        """) or 0
        viewings_cnt = v_tbl_cnt + v_act_cnt
        offers_cnt = await conn.fetchval("SELECT count(*) FROM offers")
        reservations_cnt = await conn.fetchval("SELECT count(*) FROM reservations WHERE status IN ('ACTIVE', 'CONFIRMED')")
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
        branch_rows = await conn.fetch("""
            SELECT 
                b.branch_id, b.branch_code, b.name,
                (SELECT count(*) FROM users u WHERE u.branch_id = b.branch_id) AS agents_count,
                (SELECT count(*) FROM leads l WHERE l.branch_id = b.branch_id) AS leads_count,
                (SELECT count(*) FROM opportunities o JOIN users u ON o.assigned_user_id = u.user_id WHERE u.branch_id = b.branch_id AND o.stage NOT IN ('CLOSED_WON', 'CLOSED_LOST')) AS open_opps,
                (
                    (SELECT count(*) FROM viewings v JOIN users u ON v.agent_user_id = u.user_id WHERE u.branch_id = b.branch_id) +
                    (SELECT count(*) FROM activities a JOIN activity_types at ON a.activity_type_id = at.activity_type_id JOIN users u ON a.user_id = u.user_id WHERE u.branch_id = b.branch_id AND at.code = 'VIEWING')
                ) AS viewings_count,
                (SELECT count(*) FROM contracts c JOIN reservations r ON c.reservation_id = r.reservation_id JOIN opportunities o ON r.opportunity_id = o.opportunity_id JOIN users u ON o.assigned_user_id = u.user_id WHERE u.branch_id = b.branch_id AND c.status IN ('ACTIVE', 'SIGNED')) AS contracts_count,
                (SELECT COALESCE(SUM(c.contract_value), 0) FROM contracts c JOIN reservations r ON c.reservation_id = r.reservation_id JOIN opportunities o ON r.opportunity_id = o.opportunity_id JOIN users u ON o.assigned_user_id = u.user_id WHERE u.branch_id = b.branch_id AND c.status IN ('ACTIVE', 'SIGNED')) AS sales_val
            FROM branches b
            ORDER BY sales_val DESC
        """)
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
            (
                (SELECT count(*) FROM viewings v WHERE v.agent_user_id = u.user_id) +
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

    # 5. Drill-down: Top / Active Opportunities (linked to customer & unit)
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
            o.opportunity_id, o.customer_id, o.expected_value, o.stage, o.created_at,
            COALESCE(NULLIF(TRIM(c.first_name || ' ' || COALESCE(c.last_name, '')), ''), c.company_name, 'Customer') AS customer_name,
            c.mobile AS customer_mobile,
            u.full_name AS agent_name,
            un.unit_id, un.unit_number, b.name AS building_name, p.name_en AS project_name
        FROM opportunities o
        LEFT JOIN customers c ON o.customer_id = c.customer_id
        LEFT JOIN users u ON o.assigned_user_id = u.user_id
        LEFT JOIN opportunity_units ou ON o.opportunity_id = ou.opportunity_id
        LEFT JOIN units un ON ou.unit_id = un.unit_id
        LEFT JOIN buildings b ON un.building_id = b.building_id
        LEFT JOIN projects p ON b.project_id = p.project_id
        WHERE {opp_where}
        ORDER BY o.created_at DESC
        LIMIT 25
    """, *opp_params)

    opps_data = [
        OpportunityFunnelItem(
            opportunity_id=r["opportunity_id"],
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
            created_at=r["created_at"].isoformat() if r["created_at"] else None
        )
        for r in opp_rows
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

