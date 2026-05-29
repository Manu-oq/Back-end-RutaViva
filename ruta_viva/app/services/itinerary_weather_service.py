from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.itinerary_constants import CHILE_TZ
from app.repositories.itinerary_repository import ItineraryRepository
from app.schemas.itinerary import ItineraryStepWeather, ItineraryStepWeatherResponse

NOT_APPLICABLE_MESSAGE = "El clima ya no se consulta para itinerarios finalizados o pasados."
OUT_OF_RANGE_MESSAGE = "El pronóstico detallado estará disponible más cerca de la fecha del viaje."
UNAVAILABLE_MESSAGE = "No se pudo obtener el clima para esta etapa."


def _today_in_chile() -> date:
    return datetime.now(CHILE_TZ).date()


def _is_within_forecast_range(step_date: date, weather_service_module: Any) -> bool:
    max_forecast_days = getattr(weather_service_module, "MAX_FORECAST_DAYS", 5)
    latest_supported_date = _today_in_chile() + timedelta(days=max_forecast_days)
    return step_date <= latest_supported_date


def _build_weather_response(
    step,
    *,
    weather: ItineraryStepWeather | None = None,
    weather_available: bool,
    weather_status: str,
    weather_message: str | None = None,
) -> ItineraryStepWeatherResponse:
    return ItineraryStepWeatherResponse(
        step_id=step.id,
        poi_id=step.poi_id,
        poi_name=step.poi_name,
        day_date=step.day_date,
        weather_available=weather_available,
        weather_status=weather_status,
        weather_message=weather_message,
        weather=weather,
    )


async def _get_step_coordinates_batch(
    db: AsyncSession,
    itinerary_repo: ItineraryRepository,
    step_ids: list[UUID],
) -> dict[UUID, tuple[float, float]]:
    return await itinerary_repo.get_step_coordinates_batch(db, step_ids)


async def get_itinerary_step_weather(
    db: AsyncSession,
    itinerary_id: UUID,
    tourist_id: UUID,
    itinerary_repo: ItineraryRepository,
    weather_service_module: Any,
) -> list[ItineraryStepWeatherResponse]:
    itinerary = await itinerary_repo.get_itinerary_by_id(
        db,
        itinerary_id=itinerary_id,
        tourist_id=tourist_id,
    )
    if itinerary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Itinerary not found.")
    if not itinerary.steps:
        return []
    if itinerary.is_past or itinerary.status in {"completed", "cancelled"}:
        return [
            _build_weather_response(
                step,
                weather_available=False,
                weather_status="not_applicable",
                weather_message=NOT_APPLICABLE_MESSAGE,
            )
            for step in itinerary.steps
        ]

    step_ids = [step.id for step in itinerary.steps if step.arrival_time is not None]
    coord_by_step = await _get_step_coordinates_batch(db, itinerary_repo, step_ids)

    forecast_by_date: dict[date, ItineraryStepWeather] = {}
    unavailable_dates: set[date] = set()
    out_of_range_dates: set[date] = set()
    seen_coords: dict[tuple[float, float], set[date]] = {}

    for step in itinerary.steps:
        if step.arrival_time is None:
            continue

        step_date = step.arrival_time.astimezone(CHILE_TZ).date() if step.arrival_time.tzinfo else step.arrival_time.date()
        if not _is_within_forecast_range(step_date, weather_service_module):
            out_of_range_dates.add(step_date)
            continue

        coords = coord_by_step.get(step.id)
        if coords is None:
            unavailable_dates.add(step_date)
            continue

        step_lat, step_lon = coords
        coord_key = (round(step_lat, 2), round(step_lon, 2))

        if coord_key in seen_coords and step_date in seen_coords[coord_key]:
            continue

        try:
            daily = await weather_service_module.get_daily_forecast(
                lat=step_lat,
                lon=step_lon,
                start_date=step_date,
                end_date=step_date,
            )
            if daily:
                forecast_by_date[step_date] = ItineraryStepWeather(
                    description=daily[0].description,
                    temperature_c=daily[0].temperature_c,
                    precipitation_probability=daily[0].precipitation_probability,
                )
            seen_coords.setdefault(coord_key, set()).add(step_date)
        except (ValueError, httpx.HTTPError):
            unavailable_dates.add(step_date)

    results: list[ItineraryStepWeatherResponse] = []
    for step in itinerary.steps:
        step_date = None
        if step.arrival_time is not None:
            step_date = step.arrival_time.astimezone(CHILE_TZ).date() if step.arrival_time.tzinfo else step.arrival_time.date()

        if step_date is None:
            results.append(
                _build_weather_response(
                    step,
                    weather_available=False,
                    weather_status="unavailable",
                    weather_message=UNAVAILABLE_MESSAGE,
                )
            )
            continue

        weather = forecast_by_date.get(step_date)
        if weather is not None:
            results.append(
                _build_weather_response(
                    step,
                    weather=weather,
                    weather_available=True,
                    weather_status="available",
                )
            )
            continue

        if step_date in out_of_range_dates:
            results.append(
                _build_weather_response(
                    step,
                    weather_available=False,
                    weather_status="out_of_range",
                    weather_message=OUT_OF_RANGE_MESSAGE,
                )
            )
            continue

        results.append(
            _build_weather_response(
                step,
                weather_available=False,
                weather_status="unavailable",
                weather_message=UNAVAILABLE_MESSAGE if step_date in unavailable_dates else UNAVAILABLE_MESSAGE,
            )
        )

    return results
