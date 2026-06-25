from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.poi_category import POICategory
from app.schemas.poi import POIResponse


async def get_category_ids(db: AsyncSession, poi_id: UUID) -> list[int]:
    stmt = select(POICategory.category_id).where(POICategory.poi_id == poi_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_category_ids_batch(db: AsyncSession, poi_ids: list[UUID]) -> dict[UUID, list[int]]:
    if not poi_ids:
        return {}
    stmt = (
        select(POICategory.poi_id, POICategory.category_id)
        .where(POICategory.poi_id.in_(poi_ids))
    )
    result = await db.execute(stmt)
    mapping: dict[UUID, list[int]] = {poi_id: [] for poi_id in poi_ids}
    for poi_id, category_id in result.all():
        mapping.setdefault(poi_id, []).append(category_id)
    return mapping


_OSM_METADATA_PATTERNS = [
    re.compile(r"\s*Clasificaci[óo]n OSM relevante:\s*[^.]*\.?"),
    re.compile(r"\s*Horario informado en OSM:\s*[^.]*\.?"),
    re.compile(r"\s*La informaci[óo]n OSM indica[^.]*\.?"),
    re.compile(r"\s*Operador informado:\s*[^.]*\.?"),
]


def sanitize_description(description: str | None) -> str | None:
    if not description:
        return description
    for pattern in _OSM_METADATA_PATTERNS:
        description = pattern.sub("", description)
    return description.strip()


def _is_valid_image_url(url: str | None) -> bool:
    if not url or not isinstance(url, str):
        return False
    return url.startswith("http://") or url.startswith("https://") or url.startswith("/media/")


def sanitize_multimedia_urls(multimedia: dict[str, Any] | None) -> dict[str, Any] | None:
    if not multimedia or not isinstance(multimedia, dict):
        return multimedia
    cleaned = dict(multimedia)
    for key in ("cover", "image", "image_url"):
        if key in cleaned and not _is_valid_image_url(cleaned.get(key)):
            cleaned[key] = None
    gallery = cleaned.get("gallery")
    if isinstance(gallery, list):
        cleaned["gallery"] = [url for url in gallery if _is_valid_image_url(url)]
    return cleaned


def build_poi_response_from_row(
    poi,
    latitude: float,
    longitude: float,
    category_ids: list[int],
    distance_meters: float | None = None,
) -> POIResponse:
    sanitized_multimedia = sanitize_multimedia_urls(poi.multimedia_urls)

    # Extract cover image URL for direct access
    image_url = None
    if sanitized_multimedia:
        image_url = (
            sanitized_multimedia.get("cover")
            or sanitized_multimedia.get("image")
            or sanitized_multimedia.get("image_url")
        )
        if sanitized_multimedia.get("gallery") and not image_url:
            gallery = sanitized_multimedia["gallery"]
            image_url = gallery[0] if gallery else None

    return POIResponse(
        id=poi.id,
        name=poi.name,
        description=sanitize_description(poi.description),
        access_type=poi.access_type,
        contact_phone=poi.contact_phone,
        contact_email=poi.contact_email,
        multimedia_urls=sanitized_multimedia,
        image_url=image_url,
        opening_hours_text=poi.opening_hours_text,
        visit_rules=poi.visit_rules,
        category_ids=category_ids,
        latitude=float(latitude),
        longitude=float(longitude),
        distance_meters=distance_meters,
        verification_status=poi.verification_status,
        confidence_score=float(poi.confidence_score) if poi.confidence_score is not None else 0.0,
        entrepreneur_id=poi.entrepreneur_id,
        created_by_user_id=poi.created_by_user_id,
        created_by_user_name=getattr(poi, "created_by_user_name", None),
        created_at=poi.created_at,
    )