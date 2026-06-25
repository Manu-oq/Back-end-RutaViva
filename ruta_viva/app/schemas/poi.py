from typing import Any, Literal
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class POIBase(BaseModel):
    name: str
    description: str
    access_type: Literal["public", "restricted", "private"]
    contact_phone: str | None = None
    contact_email: str | None = None
    multimedia_urls: dict[str, Any] | None = None
    opening_hours_text: str | None = None
    visit_rules: dict[str, Any] | None = None
    category_ids: list[int] = Field(default_factory=list)


class POICreate(POIBase):
    category_ids: list[int] = Field(default_factory=list, max_length=3)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    description: str = Field(min_length=20)
    image_url: str


class POITouristCreate(POICreate):
    image_url: str | None = None


class POIUpdate(BaseModel):
    name: str | None = None
    description: str | None = Field(default=None, min_length=20)
    access_type: Literal["public", "restricted", "private"] | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    opening_hours_text: str | None = None
    visit_rules: dict[str, Any] | None = None
    category_ids: list[int] | None = Field(default=None, max_length=3)
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
    entrepreneur_id: UUID | None = None
    created_by_user_id: UUID | None = None
    created_by_user_name: str | None = None
    created_at: datetime | None = None
    creator_type: Literal["tourist", "entrepreneur"] = "tourist"

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _set_creator_type(self) -> "POIResponse":
        self.creator_type = "entrepreneur" if self.entrepreneur_id is not None else "tourist"
        return self
