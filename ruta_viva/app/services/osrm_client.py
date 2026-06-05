from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from app.core.http_client import get_client
from app.services.geo_service import distance_meters

logger = logging.getLogger(__name__)

OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "http://rutaviva_osrm:5000")
OSRM_TIMEOUT = 10.0

_PROFILE_SPEEDS: dict[str, float] = {
    "driving": 40.0,
    "foot": 5.0,
}


class OSRMClient:
    """Cliente HTTP para el servidor OSRM local."""

    def __init__(self, base_url: str = OSRM_BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")
        self._http_client = get_client("osrm", base_url=self._base_url, timeout=OSRM_TIMEOUT)

    async def get_route(
        self,
        lat_a: float,
        lon_a: float,
        lat_b: float,
        lon_b: float,
        profile: str = "driving",
    ) -> dict[str, float]:
        """Calcula distancia y duracion entre dos puntos usando OSRM.

        Si OSRM no responde, usa Haversine × velocidad estimada como fallback.
        """
        if profile not in _PROFILE_SPEEDS:
            raise ValueError(f"Perfil no soportado: {profile}. Usar: {', '.join(_PROFILE_SPEEDS.keys())}")

        try:
            url = f"/route/v1/{profile}/{lon_a},{lat_a};{lon_b},{lat_b}"
            response = await self._http_client.get(url, params={"overview": "false"})
            response.raise_for_status()

            data = response.json()
            if data.get("code") != "Ok" or not data.get("routes"):
                raise ValueError(f"OSRM response invalid: code={data.get('code')}")

            route = data["routes"][0]
            return {
                "duration_seconds": float(route["duration"]),
                "distance_meters": float(route["distance"]),
            }

        except (httpx.HTTPError, ValueError, KeyError, OSError) as exc:
            logger.warning("OSRM route failed, using Haversine fallback: %s", exc)
            return self._haversine_fallback(lat_a, lon_a, lat_b, lon_b, profile)

    async def get_table(
        self,
        sources: list[tuple[float, float]],
        destinations: list[tuple[float, float]],
        profile: str = "driving",
    ) -> list[list[dict[str, float]]] | None:
        """Calcula matriz de tiempos/distancia entre multiples puntos usando OSRM.

        Retorna lista de listas [source_idx][dest_idx] con {duration_seconds, distance_meters}.
        Retorna None si OSRM no responde.
        """
        if profile not in _PROFILE_SPEEDS:
            raise ValueError(f"Perfil no soportado: {profile}")

        coords = ";".join(f"{lon},{lat}" for lat, lon in sources + destinations)
        source_indices = list(range(len(sources)))
        dest_indices = list(range(len(sources), len(sources) + len(destinations)))

        try:
            url = f"/table/v1/{profile}/{coords}"
            response = await self._http_client.get(url, params={
                "sources": ";".join(str(i) for i in source_indices),
                "destinations": ";".join(str(i) for i in dest_indices),
            })
            response.raise_for_status()

            data = response.json()
            if data.get("code") != "Ok" or not data.get("durations"):
                return None

            durations = data["durations"]
            distances = data.get("distances", [])

            matrix: list[list[dict[str, float]]] = []
            for src_idx, src_durations in enumerate(durations):
                row: list[dict[str, float]] = []
                for dest_idx, duration in enumerate(src_durations):
                    distance = distances[src_idx][dest_idx] if distances and src_idx < len(distances) and dest_idx < len(distances[src_idx]) else 0.0
                    row.append({
                        "duration_seconds": float(duration),
                        "distance_meters": float(distance),
                    })
                matrix.append(row)
            return matrix

        except (httpx.HTTPError, ValueError, KeyError, OSError) as exc:
            logger.warning("OSRM table failed: %s", exc)
            return None

    def _haversine_fallback(
        self,
        lat_a: float,
        lon_a: float,
        lat_b: float,
        lon_b: float,
        profile: str,
    ) -> dict[str, float]:
        """Calcula distancia Haversine y estima duracion usando velocidad promedio."""
        mt = distance_meters(lat_a, lon_a, lat_b, lon_b)
        speed_kmh = _PROFILE_SPEEDS.get(profile, 40.0)
        seconds = (mt / 1000.0) / speed_kmh * 3600.0
        return {
            "duration_seconds": round(seconds, 1),
            "distance_meters": round(mt, 1),
        }


_osrm_client: OSRMClient | None = None


def get_osrm_client() -> OSRMClient:
    global _osrm_client
    if _osrm_client is None:
        _osrm_client = OSRMClient()
    return _osrm_client


def reset_osrm_client() -> None:
    global _osrm_client
    _osrm_client = None
