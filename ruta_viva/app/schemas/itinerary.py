from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenerateItineraryRequest(BaseModel):
    query: str
    lat: float
    lon: float
    radius: float = Field(default=5000, gt=0)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_date_range(self) -> "GenerateItineraryRequest":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be greater than or equal to start_date.")

        trip_days = (self.end_date - self.start_date).days + 1
        if trip_days > 7:
            raise ValueError("Itinerary generation supports a maximum range of 7 days.")

        return self


class GeneratedItineraryStep(BaseModel):
    step_order: int = Field(gt=0)
    poi_id: UUID
    arrival_time: datetime | None = None
    departure_time: datetime | None = None
    ai_context: dict[str, Any] | None = None


class GeneratedItinerary(BaseModel):
    title: str
    status: str = "planned"
    steps: list[GeneratedItineraryStep] = Field(default_factory=list)


class ItineraryStepResponse(BaseModel):
    id: UUID
    itinerary_id: UUID
    poi_id: UUID
    poi_nombre: str | None = None
    poi_descripcion: str | None = None
    step_order: int
    arrival_time: datetime | None = None
    departure_time: datetime | None = None
    day_index: int | None = None
    day_date: date | None = None
    day_label: str | None = None
    ai_context: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class ItineraryStepUpdate(BaseModel):
    poi_id: UUID | None = None
    arrival_time: datetime | None = None
    departure_time: datetime | None = None
    ai_context: dict[str, Any] | None = None


class ReorderItineraryStepsRequest(BaseModel):
    step_ids: list[UUID] = Field(min_length=1)


class ItineraryResponse(BaseModel):
    id: UUID
    tourist_id: UUID
    title: str
    start_date: date | None = None
    end_date: date | None = None
    status: str
    steps: list[ItineraryStepResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
