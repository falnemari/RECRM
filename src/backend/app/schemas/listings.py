from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field

class ListingSourceMetric(BaseModel):
    source: str
    total_listings: int
    published_count: int

class ListingsSummaryOut(BaseModel):
    total_listings: int
    published_listings: int
    paused_listings: int
    expired_listings: int
    portal_listings: int
    website_listings: int
    sources: List[ListingSourceMetric]

class ListingMediaOut(BaseModel):
    media_id: str
    storage_uri: str
    media_type: str
    sort_order: int

class ListingOut(BaseModel):
    listing_id: str
    unit_id: str
    unit_number: str
    listing_source: str
    external_listing_id: Optional[str] = None
    title_ar: Optional[str] = None
    title_en: Optional[str] = None
    description_ar: Optional[str] = None
    description_en: Optional[str] = None
    published_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    status: str
    asking_price: Optional[float] = None
    rent_price: Optional[float] = None
    unit_status: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    area_sqm: Optional[float] = None
    property_type_en: Optional[str] = None
    property_type_ar: Optional[str] = None
    building_name: Optional[str] = None
    project_name_en: Optional[str] = None
    project_name_ar: Optional[str] = None
    city_name_en: Optional[str] = None
    city_name_ar: Optional[str] = None
    media: List[ListingMediaOut] = []

class ListingCreateIn(BaseModel):
    unit_id: str
    listing_source: str = Field("WEBSITE", description="Listing channel: WEBSITE, PORTAL_A, PORTAL_B, etc.")
    external_listing_id: Optional[str] = None
    title_ar: Optional[str] = None
    title_en: Optional[str] = None
    description_ar: Optional[str] = None
    description_en: Optional[str] = None
    expires_at: Optional[datetime] = None
    status: Optional[str] = Field("PUBLISHED", description="PUBLISHED, PAUSED, DRAFT")

class ListingUpdateIn(BaseModel):
    title_ar: Optional[str] = None
    title_en: Optional[str] = None
    description_ar: Optional[str] = None
    description_en: Optional[str] = None
    listing_source: Optional[str] = None
    external_listing_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    status: Optional[str] = None

