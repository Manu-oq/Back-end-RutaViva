from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.itinerary_constants import CHILE_TZ
from app.repositories.itinerary_repository import ItineraryRepository
from app.schemas.itinerary import ItineraryStepWeather, ItineraryStepWeatherResponse


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

    step_ids = [step.id for step in itinerary.steps if step.arrival_time is not None]
    coord_by_step = await _get_step_coordinates_batch(db, itinerary_repo, step_ids)

    forecast_by_date: dict[date, ItineraryStepWeather] = {}
    seen_coords: dict[tuple[float, float], set[date]] = {}

    for step in itinerary.steps:
        if step.arrival_time is None:
            continue

        step_date = step.arrival_time.astimezone(CHILE_TZ).date() if step.arrival_time.tzinfo else step.arrival_time.date()

        coords = coord_by_step.get(step.id)
        if coords is None:
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
            pass

    results: list[ItineraryStepWeatherResponse] = []
    for step in itinerary.steps:
        step_date = None
        if step.arrival_time is not None:
            step_date = step.arrival_time.astimezone(CHILE_TZ).date() if step.arrival_time.tzinfo else step.arrival_time.date()

        weather = forecast_by_date.get(step_date) if step_date else None
        results.append(
            ItineraryStepWeatherResponse(
                step_id=step.id,
                poi_id=step.poi_id,
                poi_name=step.poi_name,
                day_date=step.day_date,
                weather=weather,
            )
        )

    return results
