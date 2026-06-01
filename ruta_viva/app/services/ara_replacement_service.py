from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.services.embedding_service import OpenAIEmbeddingService
from app.services.itinerary_generation_service import filter_blacklisted_context_pois
from app.services.poi_search_service import search_candidate_pois

logger = logging.getLogger(__name__)

poi_repository = POIRepository()
itinerary_repository = ItineraryRepository()


async def build_step_replacement_context(
    db: AsyncSession,
    current_user: User,
    itinerary_id: UUID,
    step_id: UUID,
) -> tuple[str, object, object] | None:
    itinerary = await itinerary_repository.get_itinerary_by_id(db, itinerary_id, current_user.id)
    if itinerary is None:
        return None
    step = next((candidate for candidate in itinerary.steps if candidate.id == step_id), None)
    if step is None:
        return None
    current_poi = await poi_repository.get_poi_by_id(db, step.poi_id)
    if current_poi is None:
        return None
    return itinerary.title, step, current_poi


async def search_step_replacement_alternatives(
    db: AsyncSession,
    current_user: User,
    embedding_service: OpenAIEmbeddingService,
    *,
    message: str,
    current_poi,
    lat: float | None,
    lon: float | None,
    radius: float | None,
) -> list:
    search_lat = lat if lat is not None else current_poi.latitude
    search_lon = lon if lon is not None else current_poi.longitude
    search_radius = radius or 8000
    search_query = (
        f"Buscar alternativa turistica real para reemplazar este POI: {current_poi.name}. "
        f"Descripcion actual: {current_poi.description}. Preferencias del usuario: {message}"
    )
    alternatives = await search_candidate_pois(
        db,
        poi_repository,
        search_query,
        current_user,
        embedding_service,
        lat=search_lat,
        lon=search_lon,
        radius=search_radius,
        limit=15,
    )
    alternatives = filter_blacklisted_context_pois(message, alternatives)
    result = [poi for poi in alternatives if poi.id != current_poi.id][:5]
    return result


async def execute_step_replacement(
    db: AsyncSession,
    itinerary_id: UUID,
    step_id: UUID,
    new_poi_id: UUID,
    tourist_id: UUID,
) -> tuple[str, object] | None:
    itinerary_model = await itinerary_repository._get_itinerary_model(db, itinerary_id, tourist_id)
    if itinerary_model is None:
        return None

    step = next((s for s in itinerary_model.steps if s.id == step_id), None)
    if step is None:
        return None

    new_poi = await poi_repository.get_poi_by_id(db, new_poi_id)
    if new_poi is None:
        return None

    old_poi_name = step.poi.name if step.poi else "desconocido"

    step.poi_id = new_poi_id
    step.ai_context = None

    await db.flush()
    await db.refresh(step)

    updated_itinerary = await itinerary_repository.get_itinerary_by_id(db, itinerary_id, tourist_id)

    return old_poi_name, updated_itinerary
