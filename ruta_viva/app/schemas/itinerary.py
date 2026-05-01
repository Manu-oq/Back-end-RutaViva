from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GenerateItineraryRequest(BaseModel):
    query: str
    lat: float
    lon: float
    radius: float = Field(default=5000, gt=0)
    start_date: date
    end_date: date


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
    step_order: int
    arrival_time: datetime | None = None
    departure_time: datetime | None = None
    ai_context: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class ItineraryResponse(BaseModel):
    id: UUID
    tourist_id: UUID
    title: str
    start_date: date | None = None
    end_date: date | None = None
    status: str
    steps: list[ItineraryStepResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
