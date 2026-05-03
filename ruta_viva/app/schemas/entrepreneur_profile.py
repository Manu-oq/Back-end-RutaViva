from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EntrepreneurProfileCreate(BaseModel):
    admin_data: dict[str, Any] | None = None


class EntrepreneurProfileResponse(EntrepreneurProfileCreate):
    user_id: UUID

    model_config = ConfigDict(from_attributes=True)
