from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class WeatherDailyForecast(BaseModel):
    date: date
    label: str
    description: str
    temperature_c: int
    min_temp_c: int | None = None
    max_temp_c: int | None = None
    precipitation_probability: int
    precipitation_mm: float | None = None


class WeatherForecastResponse(BaseModel):
    lat: float
    lon: float
    start_date: date | None = None
    end_date: date | None = None
    daily: list[WeatherDailyForecast]
    forecast: str
