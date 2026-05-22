from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.itinerary import ItineraryResponse


class AraQuickReply(BaseModel):
    id: str
    label: str
    value: str
    type: str = "refinement"


class AraMessageResponse(BaseModel):
    id: UUID | None = None
    session_id: UUID | None = None
    role: str
    content: str
    quick_replies: list[AraQuickReply] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AraSessionCreate(BaseModel):
    initial_message: str = Field(min_length=2, max_length=1000)
    lat: float | None = None
    lon: float | None = None
    radius: float = Field(default=5000, gt=0)
    start_date: date | None = None
    end_date: date | None = None
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "AraSessionCreate":
        if self.start_date is not None and self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be greater than or equal to start_date.")
        if self.start_date is not None and self.end_date is not None:
            trip_days = (self.end_date - self.start_date).days + 1
            if trip_days > 7:
                raise ValueError("Ara itinerary generation supports a maximum range of 7 days.")
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon must be sent together.")
        if self.metadata and self.metadata.get("intent") == "change_itinerary_step":
            if not self.metadata.get("itinerary_id") or not self.metadata.get("step_id"):
                raise ValueError("metadata.itinerary_id and metadata.step_id are required for change_itinerary_step.")
        return self


class AraMessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class AraGenerateItineraryRequest(BaseModel):
    final_instruction: str | None = Field(default=None, max_length=1000)


class AraIntentInfo(BaseModel):
    intents: list[str] = Field(default_factory=list)
    primary_intent: str | None = None
    specificity: str | None = None
    locations: list[str] = Field(default_factory=list)
    turn_count: int = 0


class AraPreferenceSummary(BaseModel):
    tags: list[str] = Field(default_factory=list)
    positive_preferences: list[str] = Field(default_factory=list)
    negative_constraints: list[str] = Field(default_factory=list)
    completed_dimensions: list[str] = Field(default_factory=list)
    trip_draft: dict[str, Any] | None = None
    destination_scope: str | None = None
    selected_poi_ids: list[str] = Field(default_factory=list)
    conversation_mode: str | None = None
    route_ready_score: float = 0.0
    lodging: dict[str, Any] | None = None
    day_focus: int = 0


class AraCandidatePOI(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    category_ids: list[int] = Field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    image_url: str | None = None
    distance_meters: float | None = None
    poi_role: str | None = None


class AraSessionResponse(BaseModel):
    session_id: UUID
    status: str
    user_message: AraMessageResponse | None = None
    assistant_message: AraMessageResponse | None = None
    quick_replies: list[AraQuickReply] = Field(default_factory=list)
    intent: AraIntentInfo | None = None
    preferences: AraPreferenceSummary | None = None
    candidate_pois: list[AraCandidatePOI] = Field(default_factory=list)
    generated_itinerary_id: UUID | None = None
    active_itinerary_id: UUID | None = None
    destination_context: dict[str, Any] | None = None
    weather: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None


class AraMessagesResponse(BaseModel):
    session_id: UUID
    status: str
    messages: list[AraMessageResponse]


class AraGenerateItineraryResponse(BaseModel):
    session_id: UUID
    status: str
    itinerary: ItineraryResponse


class AraGenerateItineraryAcceptedResponse(BaseModel):
    session_id: UUID
    status: str
    generated_itinerary_id: UUID | None = None
    detail: str


class AraGenerationStatusResponse(BaseModel):
    session_id: UUID
    status: str
    generated_itinerary_id: UUID | None = None
    itinerary: ItineraryResponse | None = None
    detail: str | None = None
