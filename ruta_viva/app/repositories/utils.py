from __future__ import annotations

import re
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


def build_poi_response_from_row(
    poi,
    latitude: float,
    longitude: float,
    category_ids: list[int],
    distance_meters: float | None = None,
) -> POIResponse:
    return POIResponse(
        id=poi.id,
        name=poi.name,
        description=sanitize_description(poi.description),
        access_type=poi.access_type,
        contact_phone=poi.contact_phone,
        contact_email=poi.contact_email,
        multimedia_urls=poi.multimedia_urls,
        opening_hours_text=poi.opening_hours_text,
        visit_rules=poi.visit_rules,
        category_ids=category_ids,
        latitude=float(latitude),
        longitude=float(longitude),
        distance_meters=distance_meters,
        verification_status=poi.verification_status,
        confidence_score=float(poi.confidence_score) if poi.confidence_score is not None else 0.0,
    )