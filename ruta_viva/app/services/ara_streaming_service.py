from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.ara_repository import AraRepository
from app.repositories.itinerary_repository import ItineraryRepository
from app.schemas.ara import AraGenerateItineraryRequest, AraGenerateItineraryResponse
from app.services.ara_itinerary_core import generate_itinerary_core
from app.services.embedding_service import OpenAIEmbeddingService
from app.services.llm_service import ItineraryGenerator

logger = logging.getLogger(__name__)

ara_repository = AraRepository()
itinerary_repository = ItineraryRepository()

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
    saved_session: Any = None
    saved_itinerary: Any = None

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
        nonlocal created_itinerary_id, saved_session, saved_itinerary
        try:
            if current_user.tourist_profile is None:
                await event_queue.put({
                    "event": "error",
                    "data": {"message": "Only tourist users can use Ara."},
                })
                return

            session = await ara_repository.get_session(db, session_id, current_user.id)
            if session is None:
                await event_queue.put({
                    "event": "error",
                    "data": {"message": "Ara session not found."},
                })
                return

            itinerary, context_pois, generation_payload = await generate_itinerary_core(
                session=session,
                payload=payload,
                db=db,
                current_user=current_user,
                embedding_service=embedding_service,
                llm_service=llm_service,
                on_phase=_on_phase,
            )
            created_itinerary_id = itinerary.id
            saved_session = session
            saved_itinerary = itinerary

            # Post-save: update session preferences and add assistant message
            await db.refresh(session, ["preferences_data", "status", "candidate_poi_ids", "generated_itinerary_id"])
            preferences = dict(session.preferences_data or {})
            preferences["conversation_mode"] = "post_generation"
            preferences["active_itinerary_id"] = str(itinerary.id)
            preferences["active_itinerary_poi_ids"] = [str(step.poi_id) for step in itinerary.steps]
            await ara_repository.update_session_context(
                db,
                session,
                status="completed",
                preferences_data=preferences,
                candidate_poi_ids=[],
                generated_itinerary_id=itinerary.id,
            )
            await ara_repository.add_message(
                db,
                session.id,
                "assistant",
                "Listo, armé un itinerario personalizado con lo que conversamos.",
                metadata={"generated_itinerary_id": str(itinerary.id)},
            )
            await ara_repository.commit_or_rollback(db)

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

    try:
        while True:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
                if event["event"] in ("result", "error"):
                    break
            except asyncio.TimeoutError:
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
                await itinerary_repository.mark_itinerary_abandoned(db, created_itinerary_id)
                await db.commit()
            except Exception:
                logger.exception("Failed to mark itinerary %s as abandoned", created_itinerary_id)
        raise

    await task
