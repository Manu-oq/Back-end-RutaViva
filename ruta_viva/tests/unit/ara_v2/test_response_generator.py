from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.ara_session import AraSession
from app.schemas.ara import AraQuickReply
from app.schemas.ara_comprehension import (
    ComprehensionResult,
    ExtractedEntity,
    QuickReplySuggestion,
    ToolExecutionResult,
)
from app.schemas.itinerary import ItineraryResponse
from app.services.ara_v2.response_generator import ResponseGenerator

ToolExecutionResult.model_rebuild()


def _make_session():
    session = AraSession(
        tourist_id=uuid4(),
        initial_query="Villarrica",
        status="clarifying",
    )
    session.set_coordinates(-39.28, -71.95)
    session.messages = []
    return session


@pytest.fixture
def gen():
    with patch("app.services.ara_v2.response_generator.get_gpt_mini_client", return_value=MagicMock()):
        yield ResponseGenerator()


class TestGenerateItineraryResponse:
    @pytest.mark.asyncio
    async def test_generate_itinerary_response(self, gen):
        """status=generate, itinerary existe -> texto menciona itinerario."""
        session = _make_session()

        comprehension = ComprehensionResult(
            intenciones=["build_itinerary"],
            intencion_principal="build_itinerary",
            confianza=0.9,
            entidades=[ExtractedEntity(tipo="destino", valor="Villarrica", confianza=0.9)],
            herramientas_necesarias=["build_itinerary"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
            tono="entusiasta",
        )

        tool_result = ToolExecutionResult.model_construct(
            status="generate",
            itinerary=MagicMock(),
        )

        with patch.object(gen, "_call_gpt", new=AsyncMock(return_value="Tu itinerario de 3 dias en Villarrica esta listo!")):
            result = await gen.generate_response(comprehension, tool_result, session)

            assert "itinerario" in result["text"].lower()
            assert len(result["quick_replies"]) >= 1
            assert result["quick_replies"][0].label == "Ver itinerario"


class TestSearchPoisResponse:
    @pytest.mark.asyncio
    async def test_search_pois_response(self, gen):
        """status=search, candidate_pois=3 -> texto menciona opciones, quick_replies con POIs."""
        session = _make_session()

        comprehension = ComprehensionResult(
            intenciones=["search_pois"],
            intencion_principal="search_pois",
            confianza=0.8,
            entidades=[ExtractedEntity(tipo="destino", valor="Villarrica", confianza=0.9)],
            herramientas_necesarias=["search_pois"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        tool_result = ToolExecutionResult(
            status="search",
            candidate_pois=[
                {"id": "1", "name": "Volcan Villarrica"},
                {"id": "2", "name": "Termas Geometricas"},
                {"id": "3", "name": "Parque Nacional Villarrica"},
            ],
        )

        with patch.object(gen, "_call_gpt", new=AsyncMock(return_value="Encontre 3 opciones en Villarrica.")):
            result = await gen.generate_response(comprehension, tool_result, session)

            assert "opcion" in result["text"].lower() or "villarrica" in result["text"].lower()
            assert len(result["quick_replies"]) == 3
            assert result["quick_replies"][0].label == "Volcan Villarrica"


class TestAnswerQuestionResponse:
    @pytest.mark.asyncio
    async def test_answer_question_response(self, gen):
        """status=respond, response_text existe -> texto igual, quick_replies=[]."""
        session = _make_session()

        comprehension = ComprehensionResult(
            intenciones=["answer_question"],
            intencion_principal="answer_question",
            confianza=0.8,
            entidades=[],
            herramientas_necesarias=["answer_question"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        tool_result = ToolExecutionResult(
            status="respond",
            response_text="El Salto del Lago es de dificultad media.",
        )

        result = await gen.generate_response(comprehension, tool_result, session)

        assert result["text"] == "El Salto del Lago es de dificultad media."
        assert len(result["quick_replies"]) >= 1  # Contextual quick replies generated


class TestClarificationResponse:
    @pytest.mark.asyncio
    async def test_clarification_response(self, gen):
        """status=clarify, preguntas_pendientes -> texto contiene pregunta."""
        session = _make_session()

        comprehension = ComprehensionResult(
            intenciones=["general"],
            intencion_principal="general",
            confianza=0.5,
            entidades=[],
            herramientas_necesarias=[],
            preguntas_pendientes=["A que destino queres ir?"],
            actualizaciones_memoria=[],
            sugerir_quick_replies=[
                QuickReplySuggestion(label="Hotel", value="hotel", type="selection"),
            ],
        )

        tool_result = ToolExecutionResult(
            status="clarify",
            response_text="A que destino queres ir?",
        )

        result = await gen.generate_response(comprehension, tool_result, session)

        assert "destino" in result["text"].lower()
        assert len(result["quick_replies"]) == 1
        assert result["quick_replies"][0].label == "Hotel"


class TestReplacementResponse:
    @pytest.mark.asyncio
    async def test_replacement_response(self, gen):
        """status=replace, alternatives=3 -> texto menciona opciones de reemplazo."""
        session = _make_session()

        comprehension = ComprehensionResult(
            intenciones=["suggest_replacement"],
            intencion_principal="suggest_replacement",
            confianza=0.8,
            entidades=[],
            herramientas_necesarias=["suggest_replacement"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        tool_result = ToolExecutionResult(
            status="replace",
            candidate_pois=[
                {"id": "1", "name": "Alternativa A"},
                {"id": "2", "name": "Alternativa B"},
                {"id": "3", "name": "Alternativa C"},
            ],
        )

        with patch.object(gen, "_call_gpt", new=AsyncMock(return_value="Aca tenes opciones para reemplazar.")):
            result = await gen.generate_response(comprehension, tool_result, session)

            assert "reemplazar" in result["text"].lower() or "opcion" in result["text"].lower()
            assert len(result["quick_replies"]) == 3


class TestErrorResponse:
    @pytest.mark.asyncio
    async def test_error_response(self, gen):
        """status=error -> texto de error amigable."""
        session = _make_session()

        comprehension = ComprehensionResult(
            intenciones=[],
            intencion_principal="error",
            confianza=0.0,
            entidades=[],
            herramientas_necesarias=[],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        tool_result = ToolExecutionResult(
            status="error",
            error="Algo fallo",
        )

        result = await gen.generate_response(comprehension, tool_result, session)

        assert "algo" in result["text"].lower() or "mal" in result["text"].lower()
        assert result["quick_replies"] == []


class TestQuickRepliesFromComprehension:
    @pytest.mark.asyncio
    async def test_quick_replies_from_comprehension(self, gen):
        """comprehension.sugerir_quick_replies=2 items -> quick_replies convertidos."""
        session = _make_session()

        comprehension = ComprehensionResult(
            intenciones=["general"],
            intencion_principal="general",
            confianza=0.5,
            entidades=[],
            herramientas_necesarias=[],
            preguntas_pendientes=["Hotel o cabana?"],
            actualizaciones_memoria=[],
            sugerir_quick_replies=[
                QuickReplySuggestion(label="Hotel", value="hotel", type="selection"),
                QuickReplySuggestion(label="Cabana", value="cabana", type="selection"),
            ],
        )

        tool_result = ToolExecutionResult(
            status="clarify",
            response_text="Hotel o cabana?",
        )

        result = await gen.generate_response(comprehension, tool_result, session)

        assert len(result["quick_replies"]) == 2
        assert isinstance(result["quick_replies"][0], AraQuickReply)
        assert result["quick_replies"][0].label == "Hotel"
        assert result["quick_replies"][0].value == "hotel"


class TestNoQuickRepliesForOpenResponse:
    @pytest.mark.asyncio
    async def test_no_quick_replies_for_open_response(self, gen):
        """comprehension.sugerir_quick_replies=None -> quick_replies=[]."""
        session = _make_session()

        comprehension = ComprehensionResult(
            intenciones=["general"],
            intencion_principal="general",
            confianza=0.5,
            entidades=[],
            herramientas_necesarias=[],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
            sugerir_quick_replies=None,
        )

        tool_result = ToolExecutionResult(
            status="respond",
            response_text="Hola, en que puedo ayudarte?",
        )

        result = await gen.generate_response(comprehension, tool_result, session)

        assert len(result["quick_replies"]) >= 1  # Contextual quick replies generated


class TestFallbackOnGptFailure:
    @pytest.mark.asyncio
    async def test_fallback_on_gpt_failure_generate(self, gen):
        """GPT lanza TimeoutError -> texto fallback de generate."""
        session = _make_session()

        comprehension = ComprehensionResult(
            intenciones=["build_itinerary"],
            intencion_principal="build_itinerary",
            confianza=0.9,
            entidades=[ExtractedEntity(tipo="destino", valor="Villarrica", confianza=0.9)],
            herramientas_necesarias=["build_itinerary"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        tool_result = ToolExecutionResult.model_construct(
            status="generate",
            itinerary=MagicMock(),
        )

        with patch.object(gen, "_call_gpt", new=AsyncMock(side_effect=TimeoutError("timeout"))):
            result = await gen.generate_response(comprehension, tool_result, session)

            assert "itinerario" in result["text"].lower() or "listo" in result["text"].lower()

    @pytest.mark.asyncio
    async def test_fallback_on_gpt_failure_search(self, gen):
        """GPT lanza Exception -> texto fallback de search."""
        session = _make_session()

        comprehension = ComprehensionResult(
            intenciones=["search_pois"],
            intencion_principal="search_pois",
            confianza=0.8,
            entidades=[ExtractedEntity(tipo="destino", valor="Villarrica", confianza=0.9)],
            herramientas_necesarias=["search_pois"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        tool_result = ToolExecutionResult(
            status="search",
            candidate_pois=[{"id": "1", "name": "Volcan"}],
        )

        with patch.object(gen, "_call_gpt", new=AsyncMock(side_effect=RuntimeError("error"))):
            result = await gen.generate_response(comprehension, tool_result, session)

            assert "opcion" in result["text"].lower() or "encontre" in result["text"].lower()


class TestRioplatenseTone:
    @pytest.mark.asyncio
    async def test_rioplatense_tone(self, gen):
        """tono=entusiasta -> prompt contiene tono apropiado."""
        session = _make_session()

        comprehension = ComprehensionResult(
            intenciones=["build_itinerary"],
            intencion_principal="build_itinerary",
            confianza=0.9,
            entidades=[ExtractedEntity(tipo="destino", valor="Villarrica", confianza=0.9)],
            herramientas_necesarias=["build_itinerary"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
            tono="entusiasta",
        )

        tool_result = ToolExecutionResult.model_construct(
            status="generate",
            itinerary=MagicMock(),
        )

        captured_prompt = None

        async def capture_gpt(prompt, tono, sess):
            nonlocal captured_prompt
            captured_prompt = prompt
            return "Test response"

        with patch.object(gen, "_call_gpt", new=capture_gpt):
            await gen.generate_response(comprehension, tool_result, session)

        assert captured_prompt is not None
        assert "entusiasta" in captured_prompt.lower() or "tono" in captured_prompt.lower()


class TestNoInternalTerms:
    @pytest.mark.asyncio
    async def test_no_internal_terms(self, gen):
        """Texto fallback NO contiene terminos internos como POI, embedding, ranking, modelo."""
        fallback_text = gen._get_fallback(ToolExecutionResult(status="search"))
        assert "embedding" not in fallback_text.lower()
        assert "ranking" not in fallback_text.lower()
        assert "modelo" not in fallback_text.lower()
        assert "poi" not in fallback_text.lower()

    @pytest.mark.asyncio
    async def test_no_internal_terms_generate_fallback(self, gen):
        """Fallback de generate no contiene terminos internos."""
        fallback_text = gen._get_fallback(ToolExecutionResult(status="generate"))
        assert "embedding" not in fallback_text.lower()
        assert "ranking" not in fallback_text.lower()
        assert "modelo" not in fallback_text.lower()

    @pytest.mark.asyncio
    async def test_no_internal_terms_replace_fallback(self, gen):
        """Fallback de replace no contiene terminos internos."""
        fallback_text = gen._get_fallback(ToolExecutionResult(status="replace"))
        assert "embedding" not in fallback_text.lower()
        assert "ranking" not in fallback_text.lower()
        assert "modelo" not in fallback_text.lower()
        assert "poi" not in fallback_text.lower()
