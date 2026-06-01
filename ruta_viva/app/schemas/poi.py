from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class POIBase(BaseModel):
    name: str
    description: str = Field(min_length=60)
    access_type: Literal["public", "restricted", "private"]
    contact_phone: str | None = None
    contact_email: str | None = None
    multimedia_urls: dict[str, Any] | None = None
    opening_hours_text: str | None = None
    visit_rules: dict[str, Any] | None = None
    category_ids: list[int] = Field(default_factory=list)


class POICreate(POIBase):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    image_url: str


class POIUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    access_type: Literal["public", "restricted", "private"] | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    opening_hours_text: str | None = None
    visit_rules: dict[str, Any] | None = None
    category_ids: list[int] | None = None
    latitude: float | None = None
    longitude: float | None = None


class POIMediaAppend(BaseModel):
    image_url: str


class PotentialDuplicate(BaseModel):
    id: UUID
    name: str
    description: str
    latitude: float
    longitude: float
    category_ids: list[int] = Field(default_factory=list)
    distance_meters: float
    semantic_similarity: float


class POICreationCheck(BaseModel):
    potential_duplicates: list[PotentialDuplicate]
    pending_creation: dict[str, Any]


class POIResponse(POIBase):
    id: UUID
    latitude: float
    longitude: float
    distance_meters: float | None = None
    image_url: str | None = None
    verification_status: str = "pending"
    confidence_score: float = 0.0

    model_config = ConfigDict(from_attributes=True)
