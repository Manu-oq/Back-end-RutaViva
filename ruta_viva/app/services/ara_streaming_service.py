from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator
from uuid import UUID

import httpx
from app.db.session import AsyncSessionLocal
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.ara_repository import AraRepository
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.ara import AraGenerateItineraryRequest, AraGenerateItineraryResponse
from app.services.ara_itinerary_core import generate_itinerary_core
from app.services.embedding_service import OpenAIEmbeddingService
from app.services.llm_service import ItineraryGenerator

logger = logging.getLogger(__name__)

ara_repository = AraRepository()
itinerary_repository = ItineraryRepository()
poi_repository = POIRepository()

_PHASE_MESSAGES = {
    "validating": "Validando datos...",
    "searching": "Buscando lugares...",
    "weather": "Consultando el clima...",
    "generating": "Armando tu itinerario con IA...",
    "repairing": "Verificando horarios y calidad...",
    "saving": "Guardando...",
}


async def stream_itinerary_generation(
    session_id: UUID,
    payload: AraGenerateItineraryRequest | None,
    db: AsyncSession,
    current_user: User,
    embedding_service: OpenAIEmbeddingService,
    llm_service: ItineraryGenerator,
) -> AsyncGenerator[str, None]:
    """SSE wrapper around generate_itinerary_core()."""
    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    created_itinerary_id: UUID | None = None

    async def _on_phase(name: str, extra: dict[str, Any] | None = None) -> None:
        message = _PHASE_MESSAGES.get(name)
        if name == "searching" and extra and extra.get("poi_count", 0) < 5:
            await event_queue.put({
                "event": "warning",
                "data": {
                    "message": "Encontré pocos puntos de interés. ¿Querés que amplíe la búsqueda?",
                    "poi_count": extra["poi_count"],
                    "action": "expand_search",
                },
            })
        elif message:
            await event_queue.put({
                "event": "status",
                "data": {"phase": name, "message": message},
            })

    async def _run_core() -> None:
        nonlocal created_itinerary_id

        async with AsyncSessionLocal() as my_db:
            try:
                if current_user.tourist_profile is None:
                    await event_queue.put({
                        "event": "error",
                        "data": {"message": "Only tourist users can use Ara."},
                    })
                    return

                session = await ara_repository.get_session(my_db, session_id, current_user.id)
                if session is None:
                    await event_queue.put({
                        "event": "error",
                        "data": {"message": "Ara session not found."},
                    })
                    return

                itinerary, context_pois, generation_payload = await generate_itinerary_core(
                    session=session,
                    payload=payload,
                    db=my_db,
                    current_user=current_user,
                    embedding_service=embedding_service,
                    llm_service=llm_service,
                    on_phase=_on_phase,
                    ara_repository=ara_repository,
                    itinerary_repository=itinerary_repository,
                    poi_repository=poi_repository,
                )
                created_itinerary_id = itinerary.id

                session = await ara_repository.get_session(my_db, session_id, current_user.id)

                preferences = dict(session.preferences_data or {})
                preferences["conversation_mode"] = "post_generation"
                preferences["active_itinerary_id"] = str(itinerary.id)
                preferences["active_itinerary_poi_ids"] = [str(step.poi_id) for step in itinerary.steps]
                await ara_repository.update_session_context(
                    my_db,
                    session,
                    status="completed",
                    preferences_data=preferences,
                    candidate_poi_ids=[],
                    generated_itinerary_id=itinerary.id,
                )
                await ara_repository.add_message(
                    my_db,
                    session.id,
                    "assistant",
                    "Listo, armé un itinerario personalizado con lo que conversamos.",
                    metadata={"generated_itinerary_id": str(itinerary.id)},
                )
                await ara_repository.commit_or_rollback(my_db)

                await event_queue.put({
                    "event": "result",
                    "data": AraGenerateItineraryResponse(
                        session_id=session_id,
                        status="completed",
                        itinerary=itinerary,
                    ).model_dump(mode="json"),
                })

            except ValueError as exc:
                await event_queue.put({"event": "error", "data": {"message": str(exc)}})
            except httpx.HTTPError:
                await event_queue.put({
                    "event": "error",
                    "data": {"message": "Weather forecast provider failed while generating the itinerary."},
                })
            except Exception:
                logger.exception("Streaming itinerary generation failed unexpectedly.")
                await event_queue.put({
                    "event": "error",
                    "data": {"message": "Ocurrió un error inesperado generando el itinerario."},
                })

    task = asyncio.create_task(_run_core())

    last_event_time = time.monotonic()
    try:
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                last_event_time = time.monotonic()
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
                if event["event"] in ("result", "error"):
                    break
            except asyncio.TimeoutError:
                if time.monotonic() - last_event_time >= 5.0:
                    yield ": heartbeat\n\n"
                    last_event_time = time.monotonic()
                if task.done():
                    # Drain remaining events
                    while not event_queue.empty():
                        event = event_queue.get_nowait()
                        yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
                    break

    except asyncio.CancelledError:
        if created_itinerary_id is not None:
            logger.warning(
                "Client disconnected after itinerary %s was created. Marking as abandoned.",
                created_itinerary_id,
            )
            try:
                async with AsyncSessionLocal() as new_db:
                    await itinerary_repository.mark_itinerary_abandoned(new_db, created_itinerary_id)
                    await new_db.commit()
            except Exception:
                logger.exception("Failed to mark itinerary %s as abandoned", created_itinerary_id)
        raise

    finally:
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
