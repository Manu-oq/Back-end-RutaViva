from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ara_session import AraSession
from app.models.user import User
from app.schemas.ara_comprehension import ComprehensionResult, ExtractedEntity, ToolExecutionResult
from app.schemas.itinerary import ItineraryResponse
from app.services.ara_v2.tool_orchestrator import ToolOrchestrator

ToolExecutionResult.model_rebuild()


def _make_session(user_id=None, lat=-39.28, lon=-71.95, start_date=None, end_date=None):
    session = AraSession(
        tourist_id=user_id or uuid4(),
        initial_query="Villarrica",
        status="clarifying",
    )
    if lat is not None and lon is not None:
        session.set_coordinates(lat, lon)
    session.start_date = start_date
    session.end_date = end_date
    session.messages = []
    session.candidate_poi_ids = []
    return session


def _make_user():
    user = User(email="orch-test@test.cl", password_hash="hash", is_active=True)
    return user


class TestSearchPoisTool:
    @pytest.mark.asyncio
    async def test_search_pois_tool(self, db_session: AsyncSession):
        orchestrator = ToolOrchestrator()
        user = _make_user()
        session = _make_session(user_id=user.id)

        comprehension = ComprehensionResult(
            intenciones=["search_pois"],
            intencion_principal="search_pois",
            confianza=0.8,
            entidades=[ExtractedEntity(tipo="destino", valor="Villarrica", confianza=0.9)],
            herramientas_necesarias=["search_pois"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        mock_poi = MagicMock()
        mock_poi.id = uuid4()
        mock_poi.name = "Volcan Villarrica"

        with patch("app.services.ara_v2.tool_orchestrator.search_candidate_pois", new=AsyncMock(return_value=[mock_poi])):
            result = await orchestrator.execute(comprehension, session, user, db_session)

            assert result.candidate_pois is not None
            assert len(result.candidate_pois) == 1


class TestGetWeatherTool:
    @pytest.mark.asyncio
    async def test_get_weather_tool(self, db_session: AsyncSession):
        orchestrator = ToolOrchestrator()
        user = _make_user()
        session = _make_session(
            user_id=user.id,
            start_date=date(2026, 6, 15),
            end_date=date(2026, 6, 17),
        )

        comprehension = ComprehensionResult(
            intenciones=["get_weather"],
            intencion_principal="get_weather",
            confianza=0.8,
            entidades=[],
            herramientas_necesarias=["get_weather"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        with patch("app.services.weather_service.get_forecast", new=AsyncMock(return_value="Soleado, 22C")):
            result = await orchestrator.execute(comprehension, session, user, db_session)

            assert result.weather_forecast is not None


class TestBuildItineraryTool:
    @pytest.mark.asyncio
    async def test_build_itinerary_tool(self, db_session: AsyncSession):
        orchestrator = ToolOrchestrator()
        user = _make_user()
        session = _make_session(
            user_id=user.id,
            start_date=date(2026, 6, 15),
            end_date=date(2026, 6, 17),
        )

        comprehension = ComprehensionResult(
            intenciones=["build_itinerary"],
            intencion_principal="build_itinerary",
            confianza=0.9,
            entidades=[],
            herramientas_necesarias=["build_itinerary"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        mock_poi = MagicMock()
        mock_poi.id = uuid4()
        mock_poi.name = "Volcan"

        mock_itinerary = MagicMock()
        mock_itinerary.id = uuid4()

        with patch("app.services.ara_v2.tool_orchestrator.search_candidate_pois", new=AsyncMock(return_value=[mock_poi])), \
             patch("app.services.ara_v2.tool_orchestrator.get_itinerary_generator") as mock_gen, \
             patch("app.services.ara_v2.tool_orchestrator.validate_generated_itinerary_rules", return_value={"days": []}), \
             patch("app.services.ara_v2.tool_orchestrator.itinerary_repository") as mock_repo, \
             patch("app.services.ara_v2.tool_orchestrator.build_schedule_guidance", return_value=""):

            mock_gen.return_value.generate_itinerary = AsyncMock(return_value={"days": []})
            mock_repo.create_generated_itinerary = AsyncMock(return_value=mock_itinerary)

            result = await orchestrator.execute(comprehension, session, user, db_session)

            assert result.status == "generate"
            assert result.itinerary is not None

    @pytest.mark.asyncio
    async def test_build_itinerary_without_pois(self, db_session: AsyncSession):
        orchestrator = ToolOrchestrator()
        user = _make_user()
        session = _make_session(
            user_id=user.id,
            start_date=date(2026, 6, 15),
            end_date=date(2026, 6, 17),
        )

        comprehension = ComprehensionResult(
            intenciones=["build_itinerary"],
            intencion_principal="build_itinerary",
            confianza=0.9,
            entidades=[],
            herramientas_necesarias=["build_itinerary"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        mock_poi = MagicMock()
        mock_poi.id = uuid4()
        mock_itinerary = MagicMock()
        mock_itinerary.id = uuid4()

        with patch("app.services.ara_v2.tool_orchestrator.search_candidate_pois", new=AsyncMock(return_value=[mock_poi])), \
             patch("app.services.ara_v2.tool_orchestrator.get_itinerary_generator") as mock_gen, \
             patch("app.services.ara_v2.tool_orchestrator.validate_generated_itinerary_rules", return_value={"days": []}), \
             patch("app.services.ara_v2.tool_orchestrator.itinerary_repository") as mock_repo, \
             patch("app.services.ara_v2.tool_orchestrator.build_schedule_guidance", return_value=""):

            mock_gen.return_value.generate_itinerary = AsyncMock(return_value={"days": []})
            mock_repo.create_generated_itinerary = AsyncMock(return_value=mock_itinerary)

            result = await orchestrator.execute(comprehension, session, user, db_session)

            assert result.status == "generate"
            assert result.candidate_pois is not None


class TestAnswerQuestionTool:
    @pytest.mark.asyncio
    async def test_answer_question_tool(self, db_session: AsyncSession):
        orchestrator = ToolOrchestrator()
        user = _make_user()
        session = _make_session(user_id=user.id)
        session.messages = [MagicMock(role="user", content="Es dificil subir el volcan?")]

        comprehension = ComprehensionResult(
            intenciones=["answer_question"],
            intencion_principal="answer_question",
            confianza=0.8,
            entidades=[ExtractedEntity(tipo="poi", valor="Volcan Villarrica", confianza=0.9)],
            herramientas_necesarias=["answer_question"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        with patch("app.services.ara_v2.answer_service.get_answer_service") as mock_ans:
            mock_ans.return_value.answer = AsyncMock(return_value={
                "text": "El volcan tiene dificultad media.",
                "evidence_level": "confirmed",
                "poi_id": "123",
            })
            result = await orchestrator.execute(comprehension, session, user, db_session)

            assert result.response_text is not None
            assert "volcan" in result.response_text.lower() or "dificultad" in result.response_text.lower()
            assert result.status == "respond"


class TestSuggestReplacementTool:
    @pytest.mark.asyncio
    async def test_suggest_replacement_tool(self, db_session: AsyncSession):
        orchestrator = ToolOrchestrator()
        user = _make_user()
        session = _make_session(user_id=user.id)
        session.preferences_data = {
            "replacement_context": {
                "itinerary_id": str(uuid4()),
                "step_id": str(uuid4()),
            }
        }

        comprehension = ComprehensionResult(
            intenciones=["suggest_replacement"],
            intencion_principal="suggest_replacement",
            confianza=0.8,
            entidades=[],
            herramientas_necesarias=["suggest_replacement"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        with patch("app.services.ara_conversation_orchestrator.build_step_replacement_context", new=AsyncMock(return_value=None)):
            result = await orchestrator.execute(comprehension, session, user, db_session)

            assert result.status in ("replace", "error")


class TestClarificationWhenPendingQuestions:
    @pytest.mark.asyncio
    async def test_clarification_when_pending_questions(self, db_session: AsyncSession):
        orchestrator = ToolOrchestrator()
        user = _make_user()
        session = _make_session(user_id=user.id)

        comprehension = ComprehensionResult(
            intenciones=["general"],
            intencion_principal="general",
            confianza=0.5,
            entidades=[],
            herramientas_necesarias=[],
            preguntas_pendientes=["A que destino queres ir?"],
            actualizaciones_memoria=[],
        )

        result = await orchestrator.execute(comprehension, session, user, db_session)

        assert result.status == "clarify"
        assert result.response_text is not None
        assert "destino" in result.response_text.lower()


class TestParallelExecution:
    @pytest.mark.asyncio
    async def test_parallel_execution(self, db_session: AsyncSession):
        orchestrator = ToolOrchestrator()
        user = _make_user()
        session = _make_session(
            user_id=user.id,
            start_date=date(2026, 6, 15),
            end_date=date(2026, 6, 17),
        )

        comprehension = ComprehensionResult(
            intenciones=["search_pois", "get_weather"],
            intencion_principal="search_pois",
            confianza=0.8,
            entidades=[ExtractedEntity(tipo="destino", valor="Villarrica", confianza=0.9)],
            herramientas_necesarias=["search_pois", "get_weather"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        mock_poi = MagicMock()
        mock_poi.id = uuid4()

        with patch("app.services.ara_v2.tool_orchestrator.search_candidate_pois", new=AsyncMock(return_value=[mock_poi])), \
             patch("app.services.weather_service.get_forecast", new=AsyncMock(return_value="Soleado")):

            result = await orchestrator.execute(comprehension, session, user, db_session)

            assert result.candidate_pois is not None
            assert result.weather_forecast is not None


class TestToolFailureGraceful:
    @pytest.mark.asyncio
    async def test_tool_failure_graceful(self, db_session: AsyncSession):
        orchestrator = ToolOrchestrator()
        user = _make_user()
        session = _make_session(user_id=user.id)

        comprehension = ComprehensionResult(
            intenciones=["search_pois"],
            intencion_principal="search_pois",
            confianza=0.8,
            entidades=[ExtractedEntity(tipo="destino", valor="Villarrica", confianza=0.9)],
            herramientas_necesarias=["search_pois"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        with patch("app.services.ara_v2.tool_orchestrator.search_candidate_pois", new=AsyncMock(side_effect=RuntimeError("DB error"))):
            result = await orchestrator.execute(comprehension, session, user, db_session)

            assert result.candidate_pois is not None
            assert len(result.candidate_pois) == 0


class TestNoToolsDefaultResponse:
    @pytest.mark.asyncio
    async def test_no_tools_default_response(self, db_session: AsyncSession):
        orchestrator = ToolOrchestrator()
        user = _make_user()
        session = _make_session(user_id=user.id)

        comprehension = ComprehensionResult(
            intenciones=["general"],
            intencion_principal="general",
            confianza=0.5,
            entidades=[],
            herramientas_necesarias=[],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        result = await orchestrator.execute(comprehension, session, user, db_session)

        assert result.status == "respond"
        assert result.response_text is not None
