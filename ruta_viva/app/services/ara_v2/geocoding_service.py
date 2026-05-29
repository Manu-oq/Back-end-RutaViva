"""Geocoding service — resolves destination names to coordinates.

Uses GPT-4o-mini for geocoding with a simple dict cache and hardcoded
fallback for known La Araucanía destinations.
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

# Hardcoded fallback coordinates for known La Araucanía destinations
_KNOWN_DESTINATION_COORDS: dict[str, tuple[float, float]] = {
    "villarrica": (-39.2857, -72.2279),
    "pucon": (-39.2781, -71.9717),
    "pucon ": (-39.2781, -71.9717),
    "temuco": (-38.7359, -72.5904),
    "angol": (-37.7987, -72.7098),
    "padre las casas": (-38.7667, -72.6000),
    "lonquimay": (-38.4333, -71.4833),
    "curacautin": (-38.4167, -72.3000),
    "melipeuco": (-38.8500, -71.7000),
    "cunco": (-38.9667, -72.0000),
    "gorbea": (-39.0500, -72.6333),
    "lautaro": (-38.5333, -72.4333),
    "perquenco": (-38.6167, -72.3333),
    "galvarino": (-38.5500, -72.7500),
    "nueva imperial": (-38.7667, -72.9667),
    "carahue": (-38.7000, -73.1667),
    "teodoro schmidt": (-38.9333, -73.0167),
    "saavedra": (-38.7833, -73.3833),
    "toltén": (-39.0667, -73.0833),
    "freire": (-38.9500, -72.6167),
    "pitrufquén": (-38.9833, -72.6167),
    "loncoche": (-39.3500, -72.6333),
    "vilcún": (-38.4667, -72.1167),
    "parque nacional villarrica": (-39.4167, -71.9333),
    "parque nacional huerquehue": (-39.0833, -71.7500),
    "parque nacional congillio": (-38.5667, -71.6833),
    "termas de puyehue": (-40.7000, -72.3667),
    "termas de palguin": (-39.1500, -71.7500),
    "termas de molchan": (-39.1333, -71.7333),
    "volcan villarrica": (-39.4200, -71.9300),
    "volcan llaima": (-38.6900, -71.7200),
    "volcan lonquimay": (-38.4300, -71.3500),
    "lago villarrica": (-39.2500, -72.0000),
    "lago llaima": (-38.7500, -71.6500),
    "lago calafquen": (-39.5833, -72.2167),
    "lago caburgua": (-39.1167, -71.8833),
}

# Simple in-memory cache: destination_name → (lat, lon)
_cache: dict[str, tuple[float, float]] = {}


async def geocode_destination(destination_name: str) -> tuple[float, float] | None:
    """Resolve a destination name to (lat, lon) coordinates.

    Checks cache first, then GPT-4o-mini, then hardcoded fallback.
    """
    key = destination_name.lower().strip()

    # 1. Check cache
    if key in _cache:
        return _cache[key]

    # 2. Try GPT-4o-mini
    coords = await _geocode_with_gpt(destination_name)
    if coords:
        _cache[key] = coords
        return coords

    # 3. Hardcoded fallback
    if key in _KNOWN_DESTINATION_COORDS:
        coords = _KNOWN_DESTINATION_COORDS[key]
        _cache[key] = coords
        return coords

    logger.warning("Could not geocode destination: %s", destination_name)
    return None


async def _geocode_with_gpt(destination_name: str) -> tuple[float, float] | None:
    """Use GPT-4o-mini to geocode a destination name."""
    try:
        from app.services.ara_v2.utils import get_gpt_mini_client

        client = get_gpt_mini_client()
        model = settings.openai_gpt_mini_model

        response = await client.chat.completions.create(
            model=model,
            temperature=0.0,
            max_tokens=30,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a geocoding assistant for La Araucanía, Chile. "
                        "Respond ONLY with two numbers separated by a comma: latitude,longitude. "
                        "Example: -39.2857,-72.2279. No explanation."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Dame las coordenadas de {destination_name}, La Araucanía, Chile.",
                },
            ],
        )

        content = response.choices[0].message.content or ""
        parts = content.strip().split(",")
        if len(parts) == 2:
            lat = float(parts[0].strip())
            lon = float(parts[1].strip())
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return (lat, lon)
    except Exception as exc:
        logger.warning("GPT geocoding failed for '%s': %s", destination_name, exc)

    return None
