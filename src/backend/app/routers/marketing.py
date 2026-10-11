from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, timezone
import json
from fastapi import APIRouter, Depends, Query, HTTPException, status, Request
import asyncpg
from app.database import get_db, get_next_id
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope
from app.schemas.marketing import (
    MarketingSummaryOut, ChannelMetric,
    CampaignOut, CampaignCreateIn, CampaignUpdateIn,
    CampaignLeadOut, CampaignLeadAttachIn,
    LeadEventOut, LeadEventCreateIn
)

router = APIRouter(tags=["Marketing & Campaigns"])

# ---------------------------------------------------------
# Marketing Summary & Attribution KPIs
# ---------------------------------------------------------
@router.get("/marketing/summary", response_model=ResponseEnvelope[MarketingSummaryOut])
async def get_marketing_summary(conn: asyncpg.Connection = Depends(get_db)):
    total_campaigns = await conn.fetchval("SELECT count(*) FROM campaigns") or 0
    active_campaigns = await conn.fetchval("SELECT count(*) FROM campaigns WHERE status = 'ACTIVE'") or 0
    total_budget = await conn.fetchval("SELECT coalesce(sum(budget), 0) FROM campaigns") or 0.0
    total_leads_captured = await conn.fetchval("SELECT count(DISTINCT lead_id) FROM campaign_leads") or 0
    
    qualified_leads = await conn.fetchval("""
        SELECT count(DISTINCT cl.lead_id) 
        FROM campaign_leads cl
        JOIN leads l ON cl.lead_id = l.lead_id
        WHERE l.status = 'QUALIFIED'
    """) or 0

    conversion_rate = round((float(qualified_leads) / float(total_leads_captured) * 100.0), 2) if total_leads_captured > 0 else 0.0

    # Channel metrics breakdown using CTE to prevent budget multiplication
    channel_rows = await conn.fetch("""
        WITH camp_agg AS (
            SELECT 
                c.campaign_id,
                coalesce(c.channel, 'OTHER') AS channel,
                coalesce(c.budget, 0) AS budget,
                count(DISTINCT cl.lead_id) AS leads_cnt,
                count(DISTINCT CASE WHEN l.status = 'QUALIFIED' THEN cl.lead_id END) AS qual_cnt
            FROM campaigns c
            LEFT JOIN campaign_leads cl ON c.campaign_id = cl.campaign_id
            LEFT JOIN leads l ON cl.lead_id = l.lead_id
            GROUP BY c.campaign_id, c.channel, c.budget
        )
        SELECT 
            channel,
            count(*) AS campaigns_count,
            coalesce(sum(budget), 0) AS total_budget,
            coalesce(sum(leads_cnt), 0) AS total_leads,
            coalesce(sum(qual_cnt), 0) AS qualified_leads
        FROM camp_agg
        GROUP BY channel
        ORDER BY total_leads DESC, total_budget DESC
    """)

    breakdown = [
        ChannelMetric(
            channel=r["channel"],
            campaigns_count=r["campaigns_count"],
            total_budget=float(r["total_budget"]),
            total_leads=r["total_leads"],
            qualified_leads=r["qualified_leads"]
        )
        for r in channel_rows
    ]

    return ResponseEnvelope(data=MarketingSummaryOut(
        total_campaigns=total_campaigns,
        active_campaigns=active_campaigns,
        total_budget=float(total_budget),
        total_leads_captured=total_leads_captured,
        qualified_leads_count=qualified_leads,
        overall_conversion_rate=conversion_rate,
        channel_breakdown=breakdown
    ))


# ---------------------------------------------------------
# Campaigns CRUD
# ---------------------------------------------------------
@router.get("/campaigns", response_model=CollectionEnvelope[CampaignOut])
async def list_campaigns(
    channel: Optional[str] = Query(None, description="Filter by marketing channel (SOCIAL, SEARCH, PORTAL, EMAIL)"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (ACTIVE, COMPLETED, PAUSED)"),
    search: Optional[str] = Query(None, description="Search campaign name"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = []
    params = []

    if channel:
        params.append(channel.upper())
        conditions.append(f"UPPER(c.channel) = ${len(params)}")

    if status_filter:
        params.append(status_filter.upper())
        conditions.append(f"UPPER(c.status) = ${len(params)}")

    if search:
        params.append(f"%{search}%")
        conditions.append(f"c.name ILIKE ${len(params)}")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count_query = f"SELECT count(*) FROM campaigns c {where_clause}"
    total = await conn.fetchval(count_query, *params) or 0

    query = f"""
        SELECT 
            c.campaign_id,
            c.organization_id,
            c.name,
            c.channel,
            c.start_date,
            c.end_date,
            c.budget,
            c.status,
            COUNT(DISTINCT cl.lead_id) AS leads_count,
            COUNT(DISTINCT CASE WHEN l.status = 'QUALIFIED' THEN cl.lead_id END) AS qualified_leads_count,
            COUNT(DISTINCT CASE WHEN l.status = 'LOST' THEN cl.lead_id END) AS lost_leads_count
        FROM campaigns c
        LEFT JOIN campaign_leads cl ON c.campaign_id = cl.campaign_id
        LEFT JOIN leads l ON cl.lead_id = l.lead_id
        {where_clause}
        GROUP BY c.campaign_id
        ORDER BY c.status = 'ACTIVE' DESC, c.start_date DESC NULLS LAST, c.name ASC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
    """
    rows = await conn.fetch(query, *params, page_size, offset)

    items = []
    for r in rows:
        budget = float(r["budget"]) if r["budget"] is not None else 0.0
        leads_cnt = r["leads_count"]
        qual_cnt = r["qualified_leads_count"]
        lost_cnt = r["lost_leads_count"]
        conv_rate = round((qual_cnt / leads_cnt * 100.0), 2) if leads_cnt > 0 else 0.0
        cpl = round((budget / leads_cnt), 2) if leads_cnt > 0 else None

        items.append(CampaignOut(
            campaign_id=r["campaign_id"],
            organization_id=r["organization_id"],
            name=r["name"],
            channel=r["channel"],
            start_date=r["start_date"],
            end_date=r["end_date"],
            budget=budget,
            status=r["status"],
            leads_count=leads_cnt,
            qualified_leads_count=qual_cnt,
            lost_leads_count=lost_cnt,
            conversion_rate=conv_rate,
            cost_per_lead=cpl
        ))

    return CollectionEnvelope(
        data=items,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )


@router.post("/campaigns", response_model=ResponseEnvelope[CampaignOut], status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    org_id = await conn.fetchval("SELECT organization_id FROM organizations ORDER BY created_at ASC LIMIT 1")
    if not org_id:
        raise HTTPException(status_code=500, detail="No active organization found in system.")

    campaign_id = await get_next_id(conn, "campaigns", "campaign")
    channel = payload.channel.upper() if payload.channel else "SOCIAL"
    campaign_status = payload.status.upper() if payload.status else "ACTIVE"

    await conn.execute("""
        INSERT INTO campaigns (
            campaign_id, organization_id, name, channel, start_date, end_date, budget, status
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
    """, campaign_id, org_id, payload.name, channel, payload.start_date, payload.end_date, payload.budget, campaign_status)

    out = CampaignOut(
        campaign_id=campaign_id,
        organization_id=org_id,
        name=payload.name,
        channel=channel,
        start_date=payload.start_date,
        end_date=payload.end_date,
        budget=payload.budget or 0.0,
        status=campaign_status,
        leads_count=0,
        qualified_leads_count=0,
        lost_leads_count=0,
        conversion_rate=0.0,
        cost_per_lead=None
    )
    return ResponseEnvelope(data=out)


@router.get("/campaigns/{campaign_id}", response_model=ResponseEnvelope[CampaignOut])
async def get_campaign(campaign_id: str, conn: asyncpg.Connection = Depends(get_db)):
    row = await conn.fetchrow("""
        SELECT 
            c.campaign_id,
            c.organization_id,
            c.name,
            c.channel,
            c.start_date,
            c.end_date,
            c.budget,
            c.status,
            COUNT(DISTINCT cl.lead_id) AS leads_count,
            COUNT(DISTINCT CASE WHEN l.status = 'QUALIFIED' THEN cl.lead_id END) AS qualified_leads_count,
            COUNT(DISTINCT CASE WHEN l.status = 'LOST' THEN cl.lead_id END) AS lost_leads_count
        FROM campaigns c
        LEFT JOIN campaign_leads cl ON c.campaign_id = cl.campaign_id
        LEFT JOIN leads l ON cl.lead_id = l.lead_id
        WHERE c.campaign_id = $1
        GROUP BY c.campaign_id
    """, campaign_id)

    if not row:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found.")

    budget = float(row["budget"]) if row["budget"] is not None else 0.0
    leads_cnt = row["leads_count"]
    qual_cnt = row["qualified_leads_count"]
    lost_cnt = row["lost_leads_count"]
    conv_rate = round((qual_cnt / leads_cnt * 100.0), 2) if leads_cnt > 0 else 0.0
    cpl = round((budget / leads_cnt), 2) if leads_cnt > 0 else None

    out = CampaignOut(
        campaign_id=row["campaign_id"],
        organization_id=row["organization_id"],
        name=row["name"],
        channel=row["channel"],
        start_date=row["start_date"],
        end_date=row["end_date"],
        budget=budget,
        status=row["status"],
        leads_count=leads_cnt,
        qualified_leads_count=qual_cnt,
        lost_leads_count=lost_cnt,
        conversion_rate=conv_rate,
        cost_per_lead=cpl
    )
    return ResponseEnvelope(data=out)


@router.patch("/campaigns/{campaign_id}", response_model=ResponseEnvelope[CampaignOut])
async def update_campaign(
    campaign_id: str,
    payload: CampaignUpdateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    existing = await conn.fetchrow("SELECT * FROM campaigns WHERE campaign_id = $1", campaign_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found.")

    update_fields = []
    params = [campaign_id]

    if payload.name is not None:
        params.append(payload.name)
        update_fields.append(f"name = ${len(params)}")

    if payload.channel is not None:
        params.append(payload.channel.upper())
        update_fields.append(f"channel = ${len(params)}")

    if payload.start_date is not None:
        params.append(payload.start_date)
        update_fields.append(f"start_date = ${len(params)}")

    if payload.end_date is not None:
        params.append(payload.end_date)
        update_fields.append(f"end_date = ${len(params)}")

    if payload.budget is not None:
        params.append(payload.budget)
        update_fields.append(f"budget = ${len(params)}")

    if payload.status is not None:
        params.append(payload.status.upper())
        update_fields.append(f"status = ${len(params)}")

    if update_fields:
        query = f"UPDATE campaigns SET {', '.join(update_fields)} WHERE campaign_id = $1"
        await conn.execute(query, *params)

    return await get_campaign(campaign_id, conn)


# ---------------------------------------------------------
# Campaign Leads Attribution
# ---------------------------------------------------------
@router.get("/campaigns/{campaign_id}/leads", response_model=CollectionEnvelope[CampaignLeadOut])
async def get_campaign_leads(
    campaign_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    conn: asyncpg.Connection = Depends(get_db)
):
    # Verify campaign exists
    camp = await conn.fetchrow("SELECT name, channel FROM campaigns WHERE campaign_id = $1", campaign_id)
    if not camp:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found.")

    offset = (page - 1) * page_size
    total = await conn.fetchval("SELECT count(*) FROM campaign_leads WHERE campaign_id = $1", campaign_id) or 0

    rows = await conn.fetch("""
        SELECT 
            cl.campaign_id,
            c.name AS campaign_name,
            c.channel AS campaign_channel,
            cl.lead_id,
            cl.captured_at,
            l.customer_id,
            COALESCE(NULLIF(TRIM(CONCAT(cust.first_name, ' ', cust.last_name)), ''), cust.company_name, 'Unknown Customer') AS customer_name,
            cust.mobile AS customer_mobile,
            cust.email AS customer_email,
            l.status AS lead_status,
            l.priority AS lead_priority,
            l.inquiry_type,
            u.full_name AS assigned_agent_name
        FROM campaign_leads cl
        JOIN campaigns c ON cl.campaign_id = c.campaign_id
        JOIN leads l ON cl.lead_id = l.lead_id
        LEFT JOIN customers cust ON l.customer_id = cust.customer_id
        LEFT JOIN users u ON l.assigned_user_id = u.user_id
        WHERE cl.campaign_id = $1
        ORDER BY cl.captured_at DESC
        LIMIT $2 OFFSET $3
    """, campaign_id, page_size, offset)

    items = [CampaignLeadOut(**dict(r)) for r in rows]
    return CollectionEnvelope(
        data=items,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )


@router.post("/campaigns/{campaign_id}/leads/{lead_id}", response_model=ResponseEnvelope[CampaignLeadOut], status_code=status.HTTP_201_CREATED)
async def attach_lead_to_campaign_path(
    campaign_id: str,
    lead_id: str,
    conn: asyncpg.Connection = Depends(get_db)
):
    # Check campaign and lead exist
    c = await conn.fetchrow("SELECT name, channel FROM campaigns WHERE campaign_id = $1", campaign_id)
    if not c:
        raise HTTPException(status_code=404, detail=f"Campaign {campaign_id} not found.")
    l = await conn.fetchrow("SELECT * FROM leads WHERE lead_id = $1", lead_id)
    if not l:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found.")

    captured_at = datetime.now(timezone.utc)
    # Insert or ignore if already attached
    await conn.execute("""
        INSERT INTO campaign_leads (campaign_id, lead_id, captured_at)
        VALUES ($1, $2, $3)
        ON CONFLICT (campaign_id, lead_id) DO UPDATE SET captured_at = EXCLUDED.captured_at
    """, campaign_id, lead_id, captured_at)

    # Automatically add a lead event to lead_events
    lead_event_id = await get_next_id(conn, "lead_events", "lead_event")
    meta_json = json.dumps({"campaign_id": str(campaign_id), "campaign_name": c["name"], "channel": c["channel"]})
    await conn.execute("""
        INSERT INTO lead_events (lead_event_id, lead_id, event_type, event_at, metadata_json)
        VALUES ($1, $2, 'CAMPAIGN_ATTRIBUTED', $3, $4::jsonb)
    """, lead_event_id, lead_id, captured_at, meta_json)

    # Fetch and return complete lead info
    row = await conn.fetchrow("""
        SELECT 
            cl.campaign_id,
            c.name AS campaign_name,
            c.channel AS campaign_channel,
            cl.lead_id,
            cl.captured_at,
            l.customer_id,
            COALESCE(NULLIF(TRIM(CONCAT(cust.first_name, ' ', cust.last_name)), ''), cust.company_name, 'Unknown Customer') AS customer_name,
            cust.mobile AS customer_mobile,
            cust.email AS customer_email,
            l.status AS lead_status,
            l.priority AS lead_priority,
            l.inquiry_type,
            u.full_name AS assigned_agent_name
        FROM campaign_leads cl
        JOIN campaigns c ON cl.campaign_id = c.campaign_id
        JOIN leads l ON cl.lead_id = l.lead_id
        LEFT JOIN customers cust ON l.customer_id = cust.customer_id
        LEFT JOIN users u ON l.assigned_user_id = u.user_id
        WHERE cl.campaign_id = $1 AND cl.lead_id = $2
    """, campaign_id, lead_id)

    return ResponseEnvelope(data=CampaignLeadOut(**dict(row)))


@router.post("/campaigns/{campaign_id}/leads", response_model=ResponseEnvelope[CampaignLeadOut], status_code=status.HTTP_201_CREATED)
async def attach_lead_to_campaign_body(
    campaign_id: str,
    payload: CampaignLeadAttachIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    return await attach_lead_to_campaign_path(campaign_id, payload.lead_id, conn)


# ---------------------------------------------------------
# Lead Events Stream & Timeline
# ---------------------------------------------------------
@router.get("/lead-events", response_model=CollectionEnvelope[LeadEventOut])
async def list_lead_events(
    lead_id: Optional[str] = Query(None, description="Filter by specific lead ID"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = []
    params = []

    if lead_id:
        params.append(lead_id)
        conditions.append(f"le.lead_id = ${len(params)}")

    if event_type:
        params.append(event_type.upper())
        conditions.append(f"UPPER(le.event_type) = ${len(params)}")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count_query = f"SELECT count(*) FROM lead_events le {where_clause}"
    total = await conn.fetchval(count_query, *params) or 0

    query = f"""
        SELECT 
            le.lead_event_id,
            le.lead_id,
            le.event_type,
            le.event_at,
            le.metadata_json,
            COALESCE(NULLIF(TRIM(CONCAT(cust.first_name, ' ', cust.last_name)), ''), cust.company_name, 'Unknown') AS customer_name,
            cust.mobile AS customer_mobile,
            l.status AS lead_status,
            c.name AS campaign_name
        FROM lead_events le
        JOIN leads l ON le.lead_id = l.lead_id
        LEFT JOIN customers cust ON l.customer_id = cust.customer_id
        LEFT JOIN campaign_leads cl ON l.lead_id = cl.lead_id
        LEFT JOIN campaigns c ON cl.campaign_id = c.campaign_id
        {where_clause}
        ORDER BY le.event_at DESC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
    """
    rows = await conn.fetch(query, *params, page_size, offset)

    items = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("metadata_json"), str):
            try:
                d["metadata_json"] = json.loads(d["metadata_json"])
            except Exception:
                pass
        items.append(LeadEventOut(**d))

    return CollectionEnvelope(
        data=items,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )


@router.post("/lead-events", response_model=ResponseEnvelope[LeadEventOut], status_code=status.HTTP_201_CREATED)
async def record_lead_event(
    payload: LeadEventCreateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    if not payload.lead_id:
        raise HTTPException(status_code=400, detail="lead_id is required.")

    # Check lead exists
    l = await conn.fetchrow("SELECT lead_id FROM leads WHERE lead_id = $1", payload.lead_id)
    if not l:
        raise HTTPException(status_code=404, detail=f"Lead {payload.lead_id} not found.")

    event_id = await get_next_id(conn, "lead_events", "lead_event")
    event_at = payload.event_at or datetime.now(timezone.utc)
    meta_json = json.dumps(payload.metadata_json or {})

    await conn.execute("""
        INSERT INTO lead_events (lead_event_id, lead_id, event_type, event_at, metadata_json)
        VALUES ($1, $2, $3, $4, $5::jsonb)
    """, event_id, payload.lead_id, payload.event_type.upper(), event_at, meta_json)

    row = await conn.fetchrow("""
        SELECT 
            le.lead_event_id,
            le.lead_id,
            le.event_type,
            le.event_at,
            le.metadata_json,
            COALESCE(NULLIF(TRIM(CONCAT(cust.first_name, ' ', cust.last_name)), ''), cust.company_name, 'Unknown') AS customer_name,
            cust.mobile AS customer_mobile,
            l.status AS lead_status,
            c.name AS campaign_name
        FROM lead_events le
        JOIN leads l ON le.lead_id = l.lead_id
        LEFT JOIN customers cust ON l.customer_id = cust.customer_id
        LEFT JOIN campaign_leads cl ON l.lead_id = cl.lead_id
        LEFT JOIN campaigns c ON cl.campaign_id = c.campaign_id
        WHERE le.lead_event_id = $1
    """, event_id)

    d = dict(row)
    if isinstance(d.get("metadata_json"), str):
        try:
            d["metadata_json"] = json.loads(d["metadata_json"])
        except Exception:
            pass

    return ResponseEnvelope(data=LeadEventOut(**d))


@router.get("/leads/{lead_id}/events", response_model=CollectionEnvelope[LeadEventOut])
async def get_lead_events_timeline(
    lead_id: str,
    conn: asyncpg.Connection = Depends(get_db)
):
    l = await conn.fetchrow("SELECT lead_id FROM leads WHERE lead_id = $1", lead_id)
    if not l:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found.")

    rows = await conn.fetch("""
        SELECT 
            le.lead_event_id,
            le.lead_id,
            le.event_type,
            le.event_at,
            le.metadata_json,
            COALESCE(NULLIF(TRIM(CONCAT(cust.first_name, ' ', cust.last_name)), ''), cust.company_name, 'Unknown') AS customer_name,
            cust.mobile AS customer_mobile,
            l.status AS lead_status,
            c.name AS campaign_name
        FROM lead_events le
        JOIN leads l ON le.lead_id = l.lead_id
        LEFT JOIN customers cust ON l.customer_id = cust.customer_id
        LEFT JOIN campaign_leads cl ON l.lead_id = cl.lead_id
        LEFT JOIN campaigns c ON cl.campaign_id = c.campaign_id
        WHERE le.lead_id = $1
        ORDER BY le.event_at ASC
    """, lead_id)

    items = []
    for r in rows:
        d = dict(r)
        if isinstance(d.get("metadata_json"), str):
            try:
                d["metadata_json"] = json.loads(d["metadata_json"])
            except Exception:
                pass
        items.append(LeadEventOut(**d))

    return CollectionEnvelope(
        data=items,
        meta=CollectionMeta(page=1, page_size=len(items), total=len(items))
    )


@router.post("/leads/{lead_id}/events", response_model=ResponseEnvelope[LeadEventOut], status_code=status.HTTP_201_CREATED)
async def create_event_for_lead(
    lead_id: str,
    payload: LeadEventCreateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    payload.lead_id = lead_id
    return await record_lead_event(payload, conn)
