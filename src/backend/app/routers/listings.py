from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, HTTPException, status
import asyncpg
from app.database import get_db
from app.schemas.common import CollectionEnvelope, CollectionMeta, ResponseEnvelope
from app.schemas.listings import (
    ListingsSummaryOut, ListingSourceMetric,
    ListingOut, ListingCreateIn, ListingUpdateIn, ListingMediaOut
)

router = APIRouter(tags=["Listings & Syndication"])

# ---------------------------------------------------------
# Summary / KPIs
# ---------------------------------------------------------
@router.get("/listings/summary", response_model=ResponseEnvelope[ListingsSummaryOut])
async def get_listings_summary(conn: asyncpg.Connection = Depends(get_db)):
    total = await conn.fetchval("SELECT count(*) FROM listings") or 0
    published = await conn.fetchval("SELECT count(*) FROM listings WHERE status = 'PUBLISHED'") or 0
    paused = await conn.fetchval("SELECT count(*) FROM listings WHERE status = 'PAUSED'") or 0
    expired = await conn.fetchval("""
        SELECT count(*) FROM listings 
        WHERE status = 'EXPIRED' OR (expires_at IS NOT NULL AND expires_at < CURRENT_TIMESTAMP)
    """) or 0
    portal = await conn.fetchval("SELECT count(*) FROM listings WHERE listing_source ILIKE 'PORTAL%'") or 0
    website = await conn.fetchval("SELECT count(*) FROM listings WHERE listing_source = 'WEBSITE'") or 0

    source_rows = await conn.fetch("""
        SELECT 
            listing_source,
            count(*) AS total_listings,
            count(CASE WHEN status = 'PUBLISHED' THEN 1 END) AS published_count
        FROM listings
        GROUP BY listing_source
        ORDER BY total_listings DESC
    """)

    sources = [
        ListingSourceMetric(
            source=r["listing_source"],
            total_listings=r["total_listings"],
            published_count=r["published_count"]
        )
        for r in source_rows
    ]

    return ResponseEnvelope(data=ListingsSummaryOut(
        total_listings=total,
        published_listings=published,
        paused_listings=paused,
        expired_listings=expired,
        portal_listings=portal,
        website_listings=website,
        sources=sources
    ))


# ---------------------------------------------------------
# Listings Collection
# ---------------------------------------------------------
@router.get("/listings", response_model=CollectionEnvelope[ListingOut])
async def list_listings(
    source: Optional[str] = Query(None, description="Filter by listing channel (WEBSITE, PORTAL_A, PORTAL_B)"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status (PUBLISHED, PAUSED, EXPIRED)"),
    city_id: Optional[UUID] = Query(None, description="Filter by city"),
    property_type_id: Optional[UUID] = Query(None, description="Filter by property type"),
    search: Optional[str] = Query(None, description="Search title, unit number or project"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    conn: asyncpg.Connection = Depends(get_db)
):
    offset = (page - 1) * page_size
    conditions = []
    params = []

    if source:
        params.append(source.upper())
        conditions.append(f"UPPER(l.listing_source) = ${len(params)}")

    if status_filter:
        params.append(status_filter.upper())
        conditions.append(f"UPPER(l.status) = ${len(params)}")

    if city_id:
        params.append(city_id)
        conditions.append(f"p.city_id = ${len(params)}")

    if property_type_id:
        params.append(property_type_id)
        conditions.append(f"u.property_type_id = ${len(params)}")

    if search:
        params.append(f"%{search}%")
        conditions.append(f"(l.title_en ILIKE ${len(params)} OR l.title_ar ILIKE ${len(params)} OR u.unit_number ILIKE ${len(params)} OR p.name_en ILIKE ${len(params)} OR p.name_ar ILIKE ${len(params)})")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count_query = f"""
        SELECT count(*) 
        FROM listings l
        JOIN units u ON l.unit_id = u.unit_id
        LEFT JOIN buildings b ON u.building_id = b.building_id
        LEFT JOIN projects p ON b.project_id = p.project_id
        {where_clause}
    """
    total = await conn.fetchval(count_query, *params) or 0

    query = f"""
        SELECT 
            l.listing_id, l.unit_id, l.listing_source, l.external_listing_id,
            l.title_ar, l.title_en, l.description_ar, l.description_en,
            l.published_at, l.expires_at, l.status,
            u.unit_number, u.asking_price, u.rent_price, u.status AS unit_status,
            u.bedrooms, u.bathrooms, u.area_sqm,
            pt.name_en AS property_type_en, pt.name_ar AS property_type_ar,
            b.name AS building_name,
            p.name_en AS project_name_en, p.name_ar AS project_name_ar,
            c.name_en AS city_name_en, c.name_ar AS city_name_ar
        FROM listings l
        JOIN units u ON l.unit_id = u.unit_id
        LEFT JOIN property_types pt ON u.property_type_id = pt.property_type_id
        LEFT JOIN buildings b ON u.building_id = b.building_id
        LEFT JOIN projects p ON b.project_id = p.project_id
        LEFT JOIN cities c ON p.city_id = c.city_id
        {where_clause}
        ORDER BY l.status = 'PUBLISHED' DESC, l.published_at DESC NULLS LAST, l.listing_id ASC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
    """
    rows = await conn.fetch(query, *params, page_size, offset)

    items = []
    for r in rows:
        d = dict(r)
        d["asking_price"] = float(d["asking_price"]) if d.get("asking_price") is not None else None
        d["rent_price"] = float(d["rent_price"]) if d.get("rent_price") is not None else None
        d["area_sqm"] = float(d["area_sqm"]) if d.get("area_sqm") is not None else None
        d["media"] = []
        items.append(ListingOut(**d))

    return CollectionEnvelope(
        data=items,
        meta=CollectionMeta(page=page, page_size=page_size, total=total)
    )


# ---------------------------------------------------------
# Single Listing Operations
# ---------------------------------------------------------
@router.get("/listings/{listing_id}", response_model=ResponseEnvelope[ListingOut])
async def get_listing(listing_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    row = await conn.fetchrow("""
        SELECT 
            l.listing_id, l.unit_id, l.listing_source, l.external_listing_id,
            l.title_ar, l.title_en, l.description_ar, l.description_en,
            l.published_at, l.expires_at, l.status,
            u.unit_number, u.asking_price, u.rent_price, u.status AS unit_status,
            u.bedrooms, u.bathrooms, u.area_sqm,
            pt.name_en AS property_type_en, pt.name_ar AS property_type_ar,
            b.name AS building_name,
            p.name_en AS project_name_en, p.name_ar AS project_name_ar,
            c.name_en AS city_name_en, c.name_ar AS city_name_ar
        FROM listings l
        JOIN units u ON l.unit_id = u.unit_id
        LEFT JOIN property_types pt ON u.property_type_id = pt.property_type_id
        LEFT JOIN buildings b ON u.building_id = b.building_id
        LEFT JOIN projects p ON b.project_id = p.project_id
        LEFT JOIN cities c ON p.city_id = c.city_id
        WHERE l.listing_id = $1
    """, listing_id)

    if not row:
        raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found.")

    d = dict(row)
    d["asking_price"] = float(d["asking_price"]) if d.get("asking_price") is not None else None
    d["rent_price"] = float(d["rent_price"]) if d.get("rent_price") is not None else None
    d["area_sqm"] = float(d["area_sqm"]) if d.get("area_sqm") is not None else None

    # Fetch media photos for the unit
    media_rows = await conn.fetch("""
        SELECT media_id, storage_uri, media_type, sort_order
        FROM property_media
        WHERE unit_id = $1
        ORDER BY sort_order ASC
    """, d["unit_id"])
    d["media"] = [ListingMediaOut(**dict(m)) for m in media_rows]

    return ResponseEnvelope(data=ListingOut(**d))


@router.post("/listings", response_model=ResponseEnvelope[ListingOut], status_code=status.HTTP_201_CREATED)
async def create_listing(payload: ListingCreateIn, conn: asyncpg.Connection = Depends(get_db)):
    # Verify unit exists
    u = await conn.fetchrow("SELECT unit_id, unit_number FROM units WHERE unit_id = $1", payload.unit_id)
    if not u:
        raise HTTPException(status_code=404, detail=f"Unit {payload.unit_id} not found.")

    listing_id = uuid4()
    ext_id = payload.external_listing_id or f"EXT-LIST-{str(uuid4())[:8].upper()}"
    status_str = payload.status.upper() if payload.status else "PUBLISHED"
    published_at = datetime.now(timezone.utc) if status_str == "PUBLISHED" else None

    title_en = payload.title_en or f"Unit {u['unit_number']} - Listing"
    title_ar = payload.title_ar or f"إعلان وحدة {u['unit_number']}"

    await conn.execute("""
        INSERT INTO listings (
            listing_id, unit_id, listing_source, external_listing_id,
            title_ar, title_en, description_ar, description_en,
            published_at, expires_at, status
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
    """, listing_id, payload.unit_id, payload.listing_source.upper(), ext_id,
       title_ar, title_en, payload.description_ar, payload.description_en,
       published_at, payload.expires_at, status_str)

    return await get_listing(listing_id, conn)


@router.patch("/listings/{listing_id}", response_model=ResponseEnvelope[ListingOut])
async def update_listing(
    listing_id: UUID,
    payload: ListingUpdateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    existing = await conn.fetchrow("SELECT * FROM listings WHERE listing_id = $1", listing_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found.")

    update_fields = []
    params = [listing_id]

    if payload.title_ar is not None:
        params.append(payload.title_ar)
        update_fields.append(f"title_ar = ${len(params)}")

    if payload.title_en is not None:
        params.append(payload.title_en)
        update_fields.append(f"title_en = ${len(params)}")

    if payload.description_ar is not None:
        params.append(payload.description_ar)
        update_fields.append(f"description_ar = ${len(params)}")

    if payload.description_en is not None:
        params.append(payload.description_en)
        update_fields.append(f"description_en = ${len(params)}")

    if payload.listing_source is not None:
        params.append(payload.listing_source.upper())
        update_fields.append(f"listing_source = ${len(params)}")

    if payload.external_listing_id is not None:
        params.append(payload.external_listing_id)
        update_fields.append(f"external_listing_id = ${len(params)}")

    if payload.expires_at is not None:
        params.append(payload.expires_at)
        update_fields.append(f"expires_at = ${len(params)}")

    if payload.status is not None:
        st = payload.status.upper()
        params.append(st)
        update_fields.append(f"status = ${len(params)}")
        if st == "PUBLISHED" and not existing["published_at"]:
            update_fields.append("published_at = CURRENT_TIMESTAMP")

    if update_fields:
        query = f"UPDATE listings SET {', '.join(update_fields)} WHERE listing_id = $1"
        await conn.execute(query, *params)

    return await get_listing(listing_id, conn)


# ---------------------------------------------------------
# Action Endpoints per API.md
# ---------------------------------------------------------
@router.post("/listings/{listing_id}/publish", response_model=ResponseEnvelope[ListingOut])
async def publish_listing(listing_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    l = await conn.fetchrow("SELECT listing_id FROM listings WHERE listing_id = $1", listing_id)
    if not l:
        raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found.")

    await conn.execute("""
        UPDATE listings 
        SET status = 'PUBLISHED', published_at = CURRENT_TIMESTAMP 
        WHERE listing_id = $1
    """, listing_id)
    return await get_listing(listing_id, conn)


@router.post("/listings/{listing_id}/pause", response_model=ResponseEnvelope[ListingOut])
async def pause_listing(listing_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    l = await conn.fetchrow("SELECT listing_id FROM listings WHERE listing_id = $1", listing_id)
    if not l:
        raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found.")

    await conn.execute("UPDATE listings SET status = 'PAUSED' WHERE listing_id = $1", listing_id)
    return await get_listing(listing_id, conn)


@router.post("/listings/{listing_id}/expire", response_model=ResponseEnvelope[ListingOut])
async def expire_listing(listing_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    l = await conn.fetchrow("SELECT listing_id FROM listings WHERE listing_id = $1", listing_id)
    if not l:
        raise HTTPException(status_code=404, detail=f"Listing {listing_id} not found.")

    await conn.execute("""
        UPDATE listings 
        SET status = 'EXPIRED', expires_at = CURRENT_TIMESTAMP 
        WHERE listing_id = $1
    """, listing_id)
    return await get_listing(listing_id, conn)


# ---------------------------------------------------------
# Unit Listings Endpoints per API.md: /units/{id}/listings
# ---------------------------------------------------------
@router.get("/units/{unit_id}/listings", response_model=CollectionEnvelope[ListingOut])
async def get_unit_listings(unit_id: UUID, conn: asyncpg.Connection = Depends(get_db)):
    u = await conn.fetchrow("SELECT unit_id FROM units WHERE unit_id = $1", unit_id)
    if not u:
        raise HTTPException(status_code=404, detail=f"Unit {unit_id} not found.")

    query = """
        SELECT 
            l.listing_id, l.unit_id, l.listing_source, l.external_listing_id,
            l.title_ar, l.title_en, l.description_ar, l.description_en,
            l.published_at, l.expires_at, l.status,
            u.unit_number, u.asking_price, u.rent_price, u.status AS unit_status,
            u.bedrooms, u.bathrooms, u.area_sqm,
            pt.name_en AS property_type_en, pt.name_ar AS property_type_ar,
            b.name AS building_name,
            p.name_en AS project_name_en, p.name_ar AS project_name_ar,
            c.name_en AS city_name_en, c.name_ar AS city_name_ar
        FROM listings l
        JOIN units u ON l.unit_id = u.unit_id
        LEFT JOIN property_types pt ON u.property_type_id = pt.property_type_id
        LEFT JOIN buildings b ON u.building_id = b.building_id
        LEFT JOIN projects p ON b.project_id = p.project_id
        LEFT JOIN cities c ON p.city_id = c.city_id
        WHERE l.unit_id = $1
        ORDER BY l.published_at DESC NULLS LAST
    """
    rows = await conn.fetch(query, unit_id)

    items = []
    for r in rows:
        d = dict(r)
        d["asking_price"] = float(d["asking_price"]) if d.get("asking_price") is not None else None
        d["rent_price"] = float(d["rent_price"]) if d.get("rent_price") is not None else None
        d["area_sqm"] = float(d["area_sqm"]) if d.get("area_sqm") is not None else None
        d["media"] = []
        items.append(ListingOut(**d))

    return CollectionEnvelope(
        data=items,
        meta=CollectionMeta(page=1, page_size=len(items), total=len(items))
    )


@router.post("/units/{unit_id}/listings", response_model=ResponseEnvelope[ListingOut], status_code=status.HTTP_201_CREATED)
async def create_unit_listing(
    unit_id: UUID,
    payload: ListingCreateIn,
    conn: asyncpg.Connection = Depends(get_db)
):
    payload.unit_id = unit_id
    return await create_listing(payload, conn)

