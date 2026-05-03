from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TouristProfileBase(BaseModel):
    full_name: str
    has_own_transport: bool = False
    system_preferences: dict[str, Any] | None = None


class TouristProfileCreate(TouristProfileBase):
    pass


class TouristProfileUpdate(BaseModel):
    full_name: str | None = None
    has_own_transport: bool | None = None
    system_preferences: dict[str, Any] | None = None


class TouristProfileResponse(TouristProfileBase):
    user_id: UUID

    model_config = ConfigDict(from_attributes=True)
