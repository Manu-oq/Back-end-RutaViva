from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EntrepreneurProfileCreate(BaseModel):
    rut: str | None = Field(default=None, pattern=r"^\d{7,8}-[\dkK]$")
    admin_data: dict[str, Any] | None = None

    @field_validator("rut")
    @classmethod
    def normalize_rut(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return v.upper()


class EntrepreneurProfileResponse(EntrepreneurProfileCreate):
    user_id: UUID
    verification_status: str = "unverified"

    model_config = ConfigDict(from_attributes=True)
