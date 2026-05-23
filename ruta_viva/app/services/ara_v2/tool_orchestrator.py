from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ara_session import AraSession
from app.models.user import User
from app.repositories.itinerary_repository import ItineraryRepository
from app.repositories.poi_repository import POIRepository
from app.schemas.ara_comprehension import ComprehensionResult, ToolExecutionResult
from app.schemas.itinerary import GenerateItineraryRequest
from app.services.embedding_service import get_embedding_service
from app.services.itinerary_generation_service import (
    build_schedule_guidance,
    validate_generated_itinerary_rules,
)
from app.services.llm_service import get_itinerary_generator
from app.services.poi_search_service import search_candidate_pois
from app.services.weather_service import get_forecast as get_weather_forecast

logger = logging.getLogger(__name__)

poi_repository = POIRepository()
itinerary_repository = ItineraryRepository()


class ToolOrchestrator:
    """Ejecuta herramientas segun ComprehensionResult. No llama a LLM, solo decide y ejecuta."""

    async def execute(
        self,
        comprehension: ComprehensionResult,
        session: AraSession,
        user: User,
        db: AsyncSession,
    ) -> ToolExecutionResult:
        tools = comprehension.herramientas_necesarias
        result = ToolExecutionResult(status="respond")

        # 1. Herramientas independientes en paralelo
        tasks: list[asyncio.Task] = []
        if "search_pois" in tools:
            tasks.append(asyncio.create_task(self._search_pois(db, user, comprehension, session)))
        if "get_weather" in tools and session.start_date and session.lat is not None:
            tasks.append(asyncio.create_task(self._get_weather(session)))

        if tasks:
            parallel_results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in parallel_results:
                if isinstance(res, Exception):
                    logger.error("Tool failed: %s", res)
                    continue
                if res.get("type") == "pois":
                    result.candidate_pois = res["pois"]
                if res.get("type") == "weather":
                    result.weather_forecast = res["forecast"]

        # 2. Herramientas dependientes en secuencia
        if "build_itinerary" in tools:
            if not result.candidate_pois:
                search_res = await self._search_pois(db, user, comprehension, session)
                result.candidate_pois = search_res.get("pois", [])

            try:
                itinerary = await self._build_itinerary(
                    db, user, comprehension, session, result.candidate_pois or [], result.weather_forecast
                )
                result.itinerary = itinerary
                result.status = "generate"
            except Exception as exc:
                logger.exception("Build itinerary failed")
                result.status = "error"
                result.error = str(exc)
            return result

        if "suggest_replacement" in tools:
            try:
                replacement = await self._suggest_replacement(db, user, comprehension, session)
                result.candidate_pois = replacement.get("alternatives", [])
                result.status = "replace"
            except Exception as exc:
                logger.exception("Suggest replacement failed")
                result.status = "error"
                result.error = str(exc)
            return result

        if "answer_question" in tools:
            from app.services.ara_v2.answer_service import get_answer_service
            try:
                answer = await get_answer_service().answer(db, comprehension, session)
                result.response_text = answer["text"]
                result.status = "respond"
            except Exception as exc:
                logger.exception("Answer question failed")
                result.status = "error"
                result.error = str(exc)
            return result

        # 3. Clarificacion si hay preguntas pendientes
        if comprehension.preguntas_pendientes:
            result.response_text = self._build_clarification_text(comprehension)
            result.quick_replies = comprehension.sugerir_quick_replies
            result.status = "clarify"
            return result

        # 4. Default
        result.response_text = "Entendido. En que mas puedo ayudarte?"
        return result

    async def _search_pois(
        self,
        db: AsyncSession,
        user: User,
        comprehension: ComprehensionResult,
        session: AraSession,
    ) -> dict[str, Any]:
        destinos = [e.valor for e in comprehension.entidades if e.tipo == "destino"]
        destino = destinos[0] if destinos else None
        preferencias = [e.valor for e in comprehension.entidades if e.tipo == "preferencia"]

        lat = session.lat
        lon = session.lon
        radius = session.radius or 8000

        query_parts = [destino] if destino else []
        query_parts.extend(preferencias)
        search_query = " ".join(query_parts) or session.initial_query

        try:
            pois = await search_candidate_pois(
                db, poi_repository, search_query, user,
                get_embedding_service(), lat=lat, lon=lon, radius=radius,
            )
            session.candidate_poi_ids = [poi.id for poi in pois]
            return {"type": "pois", "pois": pois, "count": len(pois)}
        except Exception as exc:
            logger.warning("search_pois failed: %s", exc)
            return {"type": "pois", "pois": [], "count": 0}

    async def _get_weather(self, session: AraSession) -> dict[str, Any]:
        if not (session.lat and session.lon and session.start_date and session.end_date):
            return {"type": "weather", "forecast": None}

        try:
            forecast = await get_weather_forecast(
                lat=session.lat, lon=session.lon,
                start_date=session.start_date, end_date=session.end_date,
            )
            return {"type": "weather", "forecast": forecast}
        except Exception as exc:
            logger.warning("get_weather failed: %s", exc)
            return {"type": "weather", "forecast": None}

    async def _build_itinerary(
        self,
        db: AsyncSession,
        user: User,
        comprehension: ComprehensionResult,
        session: AraSession,
        candidate_pois: list,
        weather_forecast: str | None,
    ) -> Any:
        if not session.start_date or not session.end_date:
            raise ValueError("Fechas de inicio y fin son requeridas para generar itinerario")

        payload = GenerateItineraryRequest(
            query=session.initial_query,
            lat=session.lat,
            lon=session.lon,
            radius=session.radius or 5000,
            start_date=session.start_date,
            end_date=session.end_date,
        )

        user_messages = [m.content for m in session.messages if m.role == "user"] if session.messages else []
        refined_query = f"Consulta: {session.initial_query}. Mensajes: {' | '.join(user_messages)}"

        schedule_guidance = build_schedule_guidance(payload)

        generator = get_itinerary_generator()
        raw_itinerary = await generator.generate_itinerary(
            user_query=refined_query,
            context_pois=candidate_pois,
            weather_forecast=weather_forecast or "No disponible",
            schedule_guidance=schedule_guidance,
        )

        validate_generated_itinerary_rules(raw_itinerary, candidate_pois, payload)

        saved = await itinerary_repository.create_generated_itinerary(
            db, user.id, session.start_date, session.end_date, raw_itinerary
        )
        session.generated_itinerary_id = saved.id
        return saved

    async def _suggest_replacement(
        self,
        db: AsyncSession,
        user: User,
        comprehension: ComprehensionResult,
        session: AraSession,
    ) -> dict[str, Any]:
        from app.services.ara_conversation_orchestrator import (
            build_step_replacement_context,
            search_step_replacement_alternatives,
        )

        replacement_context = (session.preferences_data or {}).get("replacement_context", {})
        itinerary_id = replacement_context.get("itinerary_id")
        step_id = replacement_context.get("step_id")

        if not (itinerary_id and step_id):
            return {"alternatives": [], "error": "No hay contexto de reemplazo disponible"}

        context = await build_step_replacement_context(db, user, UUID(itinerary_id), UUID(step_id))
        if not context:
            return {"alternatives": [], "error": "Itinerario o paso no encontrado"}

        _, step, current_poi = context
        alternatives = await search_step_replacement_alternatives(
            db, user, get_embedding_service(),
            message="", current_poi=current_poi,
            lat=session.lat, lon=session.lon, radius=8000,
        )

        return {"alternatives": alternatives[:3], "current_poi_name": current_poi.name}

    @staticmethod
    def _build_clarification_text(comprehension: ComprehensionResult) -> str:
        questions = comprehension.preguntas_pendientes
        if len(questions) == 1:
            return questions[0]
        return " ".join(f"{i+1}. {q}" for i, q in enumerate(questions))


_orchestrator: ToolOrchestrator | None = None


def get_tool_orchestrator() -> ToolOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ToolOrchestrator()
    return _orchestrator


def reset_tool_orchestrator() -> None:
    global _orchestrator
    _orchestrator = None
