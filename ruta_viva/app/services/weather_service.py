from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.weather import WeatherDailyForecast


OPENWEATHER_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
OPENWEATHER_TIMEOUT_SECONDS = 15.0
MAX_FORECAST_DAYS = 5

DAY_NAMES_ES = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo",
}


def _parse_forecast_datetime(item: dict[str, Any]) -> datetime:
    return datetime.strptime(item["dt_txt"], "%Y-%m-%d %H:%M:%S")


def _select_representative_item(items: list[dict[str, Any]]) -> dict[str, Any]:
    """
    OpenWeatherMap entrega bloques cada 3 horas. Para resumir un día completo
    elegimos el bloque más cercano al mediodía porque suele representar mejor
    la actividad turística diurna que los bloques de madrugada.
    """
    return min(
        items,
        key=lambda item: abs(_parse_forecast_datetime(item).hour - 12),
    )


def _build_day_forecast(items: list[dict[str, Any]]) -> WeatherDailyForecast:
    representative = _select_representative_item(items)
    representative_dt = _parse_forecast_datetime(representative)

    day_name = DAY_NAMES_ES[representative_dt.weekday()]
    day_number = representative_dt.strftime("%d")

    weather_items = representative.get("weather", [])
    description = "sin descripción"
    if weather_items:
        description = weather_items[0].get("description", description)

    main = representative.get("main", {})
    temp = round(float(main.get("temp", 0)))

    pop_values = [float(item.get("pop", 0)) for item in items]
    max_pop = max(pop_values, default=0)

    return WeatherDailyForecast(
        date=representative_dt.date(),
        label=f"{day_name} {day_number}",
        description=description.capitalize(),
        temperature_c=temp,
        precipitation_probability=round(max_pop * 100),
    )


def _format_day_summary(day: WeatherDailyForecast) -> str:
    rain_suffix = ""
    if day.precipitation_probability >= 20:
        rain_suffix = f", probabilidad de lluvia {day.precipitation_probability}%"

    return f"{day.label}: {day.description}, {day.temperature_c}°C{rain_suffix}."


def format_forecast_summary(daily_forecast: list[WeatherDailyForecast]) -> str:
    if not daily_forecast:
        return "Pronóstico no disponible para el rango de fechas solicitado."

    return " ".join(_format_day_summary(day) for day in daily_forecast)


async def get_forecast(
    lat: float,
    lon: float,
    start_date: date | None = None,
    end_date: date | None = None,
) -> str:
    """
    Obtiene el pronóstico de 5 días de OpenWeatherMap y lo transforma en un
    resumen compacto, legible para un LLM, orientado a decisiones de itinerario.
    """
    daily_forecast = await get_daily_forecast(lat=lat, lon=lon, start_date=start_date, end_date=end_date)
    return format_forecast_summary(daily_forecast)


async def get_daily_forecast(
    lat: float,
    lon: float,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[WeatherDailyForecast]:
    """
    Obtiene el pronóstico de 5 días de OpenWeatherMap y lo transforma en
    una lista diaria estructurada para frontend.
    """
    if not settings.openweather_api_key:
        raise ValueError("OPENWEATHER_API_KEY is required to get weather forecast.")

    params = {
        "lat": lat,
        "lon": lon,
        "appid": settings.openweather_api_key,
        "units": "metric",
        "lang": "es",
    }

    async with httpx.AsyncClient(timeout=OPENWEATHER_TIMEOUT_SECONDS) as client:
        response = await client.get(OPENWEATHER_FORECAST_URL, params=params)
        response.raise_for_status()

    payload = response.json()
    forecast_items = payload.get("list", [])
    if not forecast_items:
        return []

    items_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in forecast_items:
        forecast_dt = _parse_forecast_datetime(item)
        forecast_date = forecast_dt.date()
        if start_date is not None and forecast_date < start_date:
            continue
        if end_date is not None and forecast_date > end_date:
            continue
        items_by_date[forecast_date.isoformat()].append(item)

    return [
        _build_day_forecast(items)
        for _, items in sorted(items_by_date.items())[:MAX_FORECAST_DAYS]
    ]
