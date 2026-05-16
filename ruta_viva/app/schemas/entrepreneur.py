from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EntrepreneurPostCreate(BaseModel):
    title: str
    content: str
    image_url: str | None = None
    is_published: bool = True


class EntrepreneurPostUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    image_url: str | None = None
    is_published: bool | None = None


class EntrepreneurPostResponse(BaseModel):
    id: UUID
    entrepreneur_id: UUID
    title: str
    content: str
    image_url: str | None = None
    is_published: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EntrepreneurMetricsResponse(BaseModel):
    total_pois: int
    total_visits: int
    total_reviews: int
    average_rating: float | None = None
    total_bookmarks: int
    published_posts: int


class EntrepreneurIncomeResponse(BaseModel):
    status: str = "not_configured"
    currency: str = "CLP"
    gross_income: int = 0
    net_income: int = 0
    pending_income: int = 0
    detail: str = "Income metrics will be available when a payment gateway is integrated."


class POIVisitCreate(BaseModel):
    source: str = "frontend"


class POIVisitResponse(BaseModel):
    id: UUID
    poi_id: UUID
    visitor_id: UUID | None = None
    source: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
