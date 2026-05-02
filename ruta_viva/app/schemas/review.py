from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReviewCreate(BaseModel):
    poi_id: UUID
    rating_stars: int = Field(ge=1, le=5)
    text_content: str


class ReviewResponse(ReviewCreate):
    id: UUID
    tourist_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
