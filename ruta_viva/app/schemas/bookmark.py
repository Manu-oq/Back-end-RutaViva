from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BookmarkResponse(BaseModel):
    id: UUID
    tourist_id: UUID
    poi_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BookmarkStatusResponse(BaseModel):
    poi_id: UUID
    is_bookmarked: bool
