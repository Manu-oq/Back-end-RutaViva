from datetime import date

import httpx
from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.weather import WeatherForecastResponse
from app.services.weather_service import format_forecast_summary, get_daily_forecast


router = APIRouter(tags=["weather"])


@router.get("/forecast", response_model=WeatherForecastResponse)
async def read_weather_forecast(
    lat: float = Query(...),
    lon: float = Query(...),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
) -> WeatherForecastResponse:
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_date must be greater than or equal to start_date.",
        )

    try:
        daily = await get_daily_forecast(lat=lat, lon=lon, start_date=start_date, end_date=end_date)
        forecast = format_forecast_summary(daily)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Weather forecast provider failed.",
        ) from exc

    return WeatherForecastResponse(
        lat=lat,
        lon=lon,
        start_date=start_date,
        end_date=end_date,
        daily=daily,
        forecast=forecast,
    )
