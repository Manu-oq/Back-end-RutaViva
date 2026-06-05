from __future__ import annotations

from typing import Any

from app.core.http_client import get_client
from app.schemas.geocoding import GeocodingResult


NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_TIMEOUT_SECONDS = 12.0


async def search_places(
    query: str,
    lat: float | None = None,
    lon: float | None = None,
    limit: int = 8,
) -> list[GeocodingResult]:
    params: dict[str, Any] = {
        "q": query,
        "format": "jsonv2",
        "limit": limit,
        "addressdetails": 1,
    }

    if lat is not None and lon is not None:
        delta = 1.5
        params["viewbox"] = f"{lon - delta},{lat + delta},{lon + delta},{lat - delta}"
        params["bounded"] = 0

    headers = {"User-Agent": "RutaVivaBackend/0.1 (contact: xalex0905@gmail.com)"}

    client = get_client("nominatim", base_url=NOMINATIM_SEARCH_URL, timeout=NOMINATIM_TIMEOUT_SECONDS)
    response = await client.get("", params=params, headers=headers)
    response.raise_for_status()

    results: list[GeocodingResult] = []
    for item in response.json():
        bounding_box = item.get("boundingbox")
        parsed_bounding_box = [float(value) for value in bounding_box] if isinstance(bounding_box, list) else None
        results.append(
            GeocodingResult(
                display_name=item.get("display_name", ""),
                latitude=float(item["lat"]),
                longitude=float(item["lon"]),
                type=item.get("type"),
                importance=float(item["importance"]) if item.get("importance") is not None else None,
                bounding_box=parsed_bounding_box,
            )
        )

    return results
