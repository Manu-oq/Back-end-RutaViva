from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenerateItineraryRequest(BaseModel):
    query: str = Field(max_length=15000)
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
    poi_name: str | None = None
    poi_description: str | None = None
    step_order: int
    arrival_time: datetime | None = None
    departure_time: datetime | None = None
    day_index: int | None = None
    day_date: date | None = None
    day_label: str | None = None
    ai_context: dict[str, Any] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ItineraryStepCreate(BaseModel):
    poi_id: UUID
    arrival_time: datetime | None = None
    departure_time: datetime | None = None
    ai_context: dict[str, Any] | None = None
    model_config = ConfigDict(from_attributes=True)


class ItineraryStatusUpdate(BaseModel):
    status: Literal["planned", "active", "completed", "cancelled"]


class ItineraryStepUpdate(BaseModel):
    poi_id: UUID | None = None
    arrival_time: datetime | None = None
    departure_time: datetime | None = None
    ai_context: dict[str, Any] | None = None


class RescheduleStepRequest(BaseModel):
    arrival_time: datetime
    duration_minutes: int | None = None


class StepDayPosition(BaseModel):
    step_id: UUID
    day_index: int = Field(gt=0)
    position: int = Field(ge=0)


class ReorderStepsWithTimesRequest(BaseModel):
    steps: list[StepDayPosition] = Field(min_length=1)


class ReorderItineraryStepsRequest(BaseModel):
    step_ids: list[UUID] = Field(min_length=1)


class ItineraryResponse(BaseModel):
    id: UUID
    tourist_id: UUID
    title: str
    start_date: date | None = None
    end_date: date | None = None
    status: str
    is_past: bool = False
    is_editable: bool = True
    steps: list[ItineraryStepResponse] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ItineraryStepWeather(BaseModel):
    description: str
    temperature_c: int
    precipitation_probability: int


class ItineraryStepWeatherResponse(BaseModel):
    step_id: UUID
    poi_id: UUID
    poi_name: str | None = None
    day_date: date | None = None
    weather_available: bool = False
    weather_status: Literal["available", "out_of_range", "not_applicable", "unavailable"] = "unavailable"
    weather_message: str | None = None
    weather: ItineraryStepWeather | None = None


class ItineraryExportStep(BaseModel):
    day: int
    date: str
    order: int
    poi_name: str
    poi_description: str | None = None
    poi_address: str | None = None
    arrival_time: str | None = None
    departure_time: str | None = None
    tips: str | None = None
    weather: dict[str, Any] | None = None
    latitude: float | None = None
    longitude: float | None = None


class ItineraryExportResponse(BaseModel):
    title: str
    start_date: str | None = None
    end_date: str | None = None
    steps: list[ItineraryExportStep]
    total_days: int
    total_steps: int
    generated_at: str | None = None


class ShareResponse(BaseModel):
    share_url: str
    public_id: str


class PaginatedItineraryResponse(BaseModel):
    items: list[ItineraryResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class StepVisitRequest(BaseModel):
    note: str | None = None


class StepVisitResponse(BaseModel):
    id: UUID
    step_id: UUID
    poi_id: UUID
    visited_at: datetime
    source: str = "itinerary"
    note: str | None = None
