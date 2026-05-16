from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class WeatherDailyForecast(BaseModel):
    date: date
    label: str
    description: str
    temperature_c: int
    precipitation_probability: int


class WeatherForecastResponse(BaseModel):
    lat: float
    lon: float
    start_date: date | None = None
    end_date: date | None = None
    daily: list[WeatherDailyForecast]
    forecast: str
