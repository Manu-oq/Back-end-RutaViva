from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from cachetools import TTLCache

from app.core.config import settings
from app.core.http_client import get_client
from app.schemas.weather import WeatherDailyForecast

logger = logging.getLogger(__name__)


OPENWEATHER_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"
OPENWEATHER_TIMEOUT_SECONDS = 15.0
MAX_FORECAST_DAYS = 5

_weather_cache: TTLCache = TTLCache(maxsize=100, ttl=1800)

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

    # Compute min/max from daytime hours (06:00-21:00)
    daytime_temps = [
        float(item["main"]["temp"])
        for item in items
        if 6 <= _parse_forecast_datetime(item).hour <= 21
    ]
    daytime_mins = [
        float(item["main"]["temp_min"])
        for item in items
        if 6 <= _parse_forecast_datetime(item).hour <= 21 and "temp_min" in item.get("main", {})
    ]
    daytime_maxs = [
        float(item["main"]["temp_max"])
        for item in items
        if 6 <= _parse_forecast_datetime(item).hour <= 21 and "temp_max" in item.get("main", {})
    ]

    max_temp = round(max(daytime_temps)) if daytime_temps else round(float(representative.get("main", {}).get("temp", 0)))
    min_temp = round(min(daytime_mins)) if daytime_mins else None
    max_temp_explicit = round(max(daytime_maxs)) if daytime_maxs else None

    # Precipitation probability (max across all blocks)
    pop_values = [float(item.get("pop", 0)) for item in items]
    max_pop = max(pop_values, default=0)

    # Precipitation amount in mm (sum of rain + snow across all 3h blocks)
    total_precip_mm = 0.0
    for item in items:
        rain_3h = float(item.get("rain", {}).get("3h", 0))
        snow_3h = float(item.get("snow", {}).get("3h", 0))
        total_precip_mm += rain_3h + snow_3h
    precip_mm = round(total_precip_mm, 1) if total_precip_mm > 0 else None

    logger.debug(
        "Forecast %s: raw_daytime_temps=%s min=%s max=%s°C desc=%s pop=%d%% precip=%.1fmm",
        representative_dt.date(),
        daytime_temps,
        min_temp,
        max_temp_explicit or max_temp,
        description.capitalize(),
        round(max_pop * 100),
        total_precip_mm,
    )

    return WeatherDailyForecast(
        date=representative_dt.date(),
        label=f"{day_name} {day_number}",
        description=description.capitalize(),
        temperature_c=max_temp,
        min_temp_c=min_temp,
        max_temp_c=max_temp_explicit,
        precipitation_probability=round(max_pop * 100),
        precipitation_mm=precip_mm,
    )


def _format_day_summary(day: WeatherDailyForecast) -> str:
    temp_str = f"{day.temperature_c}°C"
    if day.min_temp_c is not None and day.max_temp_c is not None:
        temp_str = f"{day.min_temp_c}°C / {day.max_temp_c}°C"

    rain_parts = []
    if day.precipitation_probability >= 20:
        rain_parts.append(f"probabilidad de lluvia {day.precipitation_probability}%")
    if day.precipitation_mm is not None and day.precipitation_mm > 0:
        rain_parts.append(f"{day.precipitation_mm} mm de lluvia")

    rain_suffix = ""
    if rain_parts:
        rain_suffix = f", {', '.join(rain_parts)}"

    return f"{day.label}: {day.description}, {temp_str}{rain_suffix}."


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
    daily_forecast = await get_daily_forecast(lat=lat, lon=lon, start_date=start_date, end_date=end_date)
    return format_forecast_summary(daily_forecast)


async def get_daily_forecast(
    lat: float,
    lon: float,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[WeatherDailyForecast]:
    cache_key = (round(lat, 2), round(lon, 2))
    cached = _weather_cache.get(cache_key)
    if cached is not None:
        return _filter_forecast_by_dates(cached, start_date, end_date)

    if not settings.openweather_api_key:
        raise ValueError("OPENWEATHER_API_KEY is required to get weather forecast.")

    params = {
        "lat": lat,
        "lon": lon,
        "appid": settings.openweather_api_key,
        "units": "metric",
        "lang": "es",
    }

    client = get_client("openweather", base_url=OPENWEATHER_FORECAST_URL, timeout=OPENWEATHER_TIMEOUT_SECONDS)
    response = await client.get("", params=params)
    response.raise_for_status()

    payload = response.json()
    forecast_items = payload.get("list", [])
    if not forecast_items:
        return []

    logger.info(
        "OWM forecast response: lat=%.4f lon=%.4f items=%d city=%s",
        lat,
        lon,
        len(forecast_items),
        payload.get("city", {}).get("name", "unknown"),
    )

    items_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in forecast_items:
        forecast_dt = _parse_forecast_datetime(item)
        forecast_date = forecast_dt.date()
        items_by_date[forecast_date.isoformat()].append(item)

    all_days = [
        _build_day_forecast(items)
        for _, items in sorted(items_by_date.items())[:MAX_FORECAST_DAYS]
    ]

    _weather_cache[cache_key] = all_days
    return _filter_forecast_by_dates(all_days, start_date, end_date)


def _filter_forecast_by_dates(
    forecasts: list[WeatherDailyForecast],
    start_date: date | None,
    end_date: date | None,
) -> list[WeatherDailyForecast]:
    if start_date is None and end_date is None:
        return forecasts
    return [
        day for day in forecasts
        if (start_date is None or day.date >= start_date)
        and (end_date is None or day.date <= end_date)
    ]
