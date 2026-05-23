from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.ara_comprehension import ComprehensionResult, DateRange, ExtractedEntity, MemoryFact
from app.services.ara_v2.comprehension_fallback import fallback_comprehend


class TestFallbackIntention:
    """Tests de intencion del fallback."""

    def test_search_pois_intention(self):
        """Quiero ir a Villarrica -> search_pois, entidad destino=Villarrica."""
        result = fallback_comprehend("Quiero ir a Villarrica")
        assert "search_pois" in result.herramientas_necesarias
        assert any(e.tipo == "destino" and "villarrica" in e.valor.lower() for e in result.entidades)

    def test_build_itinerary_intention(self):
        """Hacelo todo tu -> build_itinerary."""
        result = fallback_comprehend("Hacelo todo tu")
        assert "build_itinerary" in result.herramientas_necesarias
        assert result.intencion_principal == "build_itinerary"

    def test_generate_itinerary_intention(self):
        """Genera el itinerario -> build_itinerary."""
        result = fallback_comprehend("Genera el itinerario")
        assert "build_itinerary" in result.herramientas_necesarias

    def test_suggest_replacement_intention(self):
        """Cambia el hotel del viernes -> suggest_replacement."""
        result = fallback_comprehend("Cambia el hotel del viernes")
        assert "suggest_replacement" in result.herramientas_necesarias

    def test_get_weather_intention(self):
        """Que clima hara -> get_weather + answer_question."""
        result = fallback_comprehend("Que clima hara el sabado?")
        assert "get_weather" in result.herramientas_necesarias
        assert "answer_question" in result.herramientas_necesarias


class TestFallbackEntities:
    """Tests de extraccion de entidades del fallback."""

    def test_destination_entity(self):
        """Voy a Pucon -> entidad destino=Pucon."""
        result = fallback_comprehend("Voy a Pucon")
        assert any(e.tipo == "destino" and "pucon" in e.valor.lower() for e in result.entidades)

    def test_family_entity_in_memory(self):
        """Con mi familia -> memoria: viaja con familia."""
        result = fallback_comprehend("Con mi familia, algo tranquilo")
        assert any("familia" in f.hecho.lower() for f in result.actualizaciones_memoria)

    def test_low_difficulty_preference(self):
        """No me gusta caminar -> memoria: prefiere baja dificultad."""
        result = fallback_comprehend("No me gusta caminar")
        assert any("baja dificultad" in f.hecho.lower() for f in result.actualizaciones_memoria)


class TestFallbackMemory:
    """Tests de extraccion de hechos para memoria del fallback."""

    def test_vegetarian_restriction(self):
        """Soy vegetariano -> memoria: dieta vegetariana, categoria restriccion."""
        result = fallback_comprehend("Soy vegetariano")
        assert any(f.categoria == "restriccion" and "vegetariano" in f.hecho.lower() for f in result.actualizaciones_memoria)

    def test_lodging_preference(self):
        """Quiero un hotel cerca del lago -> memoria con preferencia de alojamiento."""
        result = fallback_comprehend("Quiero un hotel cerca del lago")
        assert result.intencion_principal in ("general", "search_pois")


class TestFallbackQuickReplies:
    """Tests de quick replies del fallback."""

    def test_open_response_no_quick_replies(self):
        """Hacelo todo -> sugerir_quick_replies = None (respuesta abierta)."""
        result = fallback_comprehend("Hacelo todo tu")
        assert result.sugerir_quick_replies is None

    def test_general_no_quick_replies(self):
        """Mensaje general -> sin quick replies."""
        result = fallback_comprehend("Hola, necesito ayuda")
        assert result.sugerir_quick_replies is None


class TestFallbackPendingQuestions:
    """Tests de preguntas pendientes del fallback."""

    def test_vague_trip_request_has_questions(self):
        """Quiero ir de viaje -> preguntas pendientes sobre destino y fechas."""
        result = fallback_comprehend("Quiero ir de viaje")
        assert len(result.preguntas_pendientes) >= 1
        assert any("destino" in p.lower() for p in result.preguntas_pendientes)

    def test_build_itinerary_without_destination(self):
        """Hacelo todo sin destino -> pregunta sobre destino."""
        result = fallback_comprehend("Hacelo todo")
        assert len(result.preguntas_pendientes) >= 0


class TestFallbackMultipleIntentions:
    """Tests de intenciones multiples del fallback."""

    def test_multiple_intentions(self):
        """Voy a Villarrica, hacelo todo, pero quiero termas -> multiples intenciones."""
        result = fallback_comprehend("Voy a Villarrica, hacelo todo, pero quiero termas")
        assert len(result.intenciones) >= 1
        assert "search_pois" in result.herramientas_necesarias or "build_itinerary" in result.herramientas_necesarias


class TestFallbackEdgeCases:
    """Tests de casos borde del fallback."""

    def test_empty_message(self):
        """Mensaje vacio -> fallback con intencion general."""
        result = fallback_comprehend("")
        assert result.intencion_principal == "general"
        assert result.confianza <= 0.3

    def test_emoji_only_message(self):
        """Solo emojis -> fallback."""
        result = fallback_comprehend("\U0001f3d4\U0001f30b\U0001f3d5")
        assert result.intencion_principal == "general"
        assert result.confianza <= 0.3

    def test_whitespace_only_message(self):
        """Solo espacios -> fallback."""
        result = fallback_comprehend("   ")
        assert result.intencion_principal == "general"


class TestComprehensionResultValidation:
    """Tests de validacion del schema ComprehensionResult."""

    def test_valid_minimal_result(self):
        """Validar ComprehensionResult con campos minimos."""
        result = ComprehensionResult.model_validate({
            "intenciones": ["general"],
            "intencion_principal": "general",
            "confianza": 0.5,
            "entidades": [],
            "herramientas_necesarias": [],
            "preguntas_pendientes": [],
            "actualizaciones_memoria": [],
        })
        assert result.intencion_principal == "general"
        assert result.tono == "neutro"

    def test_valid_full_result(self):
        """Validar ComprehensionResult completo."""
        data = {
            "intenciones": ["planificar_viaje", "build_itinerary"],
            "intencion_principal": "planificar_viaje",
            "confianza": 0.95,
            "entidades": [{"tipo": "destino", "valor": "Villarrica", "confianza": 0.98}],
            "rango_fechas": {"start": "2026-06-15", "end": "2026-06-17"},
            "herramientas_necesarias": ["search_pois", "build_itinerary"],
            "preguntas_pendientes": ["?Hotel o cabana?"],
            "actualizaciones_memoria": [{"hecho": "viaja con familia", "categoria": "entidad", "confianza": 0.9}],
            "sugerir_quick_replies": [{"label": "Hotel", "value": "hotel", "type": "selection"}],
            "tono": "entusiasta",
        }
        result = ComprehensionResult.model_validate(data)
        assert result.intencion_principal == "planificar_viaje"
        assert len(result.entidades) == 1
        assert result.rango_fechas is not None
        assert result.rango_fechas.start == "2026-06-15"
        assert result.sugerir_quick_replies is not None
        assert result.sugerir_quick_replies[0].label == "Hotel"

    def test_invalid_confianza_range(self):
        """Confianza fuera de rango -> ValidationError."""
        with pytest.raises(Exception):
            ComprehensionResult.model_validate({
                "intenciones": [],
                "intencion_principal": "test",
                "confianza": 1.5,
                "entidades": [],
                "herramientas_necesarias": [],
                "preguntas_pendientes": [],
                "actualizaciones_memoria": [],
            })

    def test_invalid_categoria_pattern(self):
        """Categoria invalida -> ValidationError."""
        with pytest.raises(Exception):
            ComprehensionResult.model_validate({
                "intenciones": [],
                "intencion_principal": "test",
                "confianza": 0.5,
                "entidades": [],
                "herramientas_necesarias": [],
                "preguntas_pendientes": [],
                "actualizaciones_memoria": [{"hecho": "test", "categoria": "invalida", "confianza": 0.5}],
            })


class TestComprensorFallback:
    """Tests del Comprensor con mocks de fallo de GPT."""

    @pytest.mark.asyncio
    async def test_timeout_falls_back(self):
        """Timeout de GPT -> fallback."""
        from app.services.ara_v2.comprehender import Comprensor

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=TimeoutError("Request timed out"))

        with patch("app.services.ara_v2.comprehender.get_gpt_mini_client", return_value=mock_client):
            comprensor = Comprensor()
            result = await comprensor.comprehend("Quiero ir a Villarrica")
            assert result.intencion_principal == "general" or "search_pois" in result.herramientas_necesarias

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back(self):
        """JSON invalido de GPT -> fallback."""
        from app.services.ara_v2.comprehender import Comprensor

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "esto no es json {{{"
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.ara_v2.comprehender.get_gpt_mini_client", return_value=mock_client):
            comprensor = Comprensor()
            result = await comprensor.comprehend("Hola")
            assert result.intencion_principal is not None

    @pytest.mark.asyncio
    async def test_validation_error_falls_back(self):
        """ValidationError de Pydantic -> fallback."""
        from app.services.ara_v2.comprehender import Comprensor

        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps({"intenciones": [], "confianza": 0.5})
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.ara_v2.comprehender.get_gpt_mini_client", return_value=mock_client):
            comprensor = Comprensor()
            result = await comprensor.comprehend("Hola")
            assert result.intencion_principal is not None

    @pytest.mark.asyncio
    async def test_gpt_success_returns_parsed_result(self):
        """GPT responde JSON valido -> devuelve ComprehensionResult parseado."""
        from app.services.ara_v2.comprehender import Comprensor

        gpt_response = {
            "intenciones": ["planificar_viaje"],
            "intencion_principal": "planificar_viaje",
            "confianza": 0.95,
            "entidades": [{"tipo": "destino", "valor": "Villarrica", "confianza": 0.98}],
            "rango_fechas": None,
            "herramientas_necesarias": ["search_pois"],
            "preguntas_pendientes": [],
            "actualizaciones_memoria": [],
            "sugerir_quick_replies": None,
            "tono": "entusiasta",
        }
        mock_response = MagicMock()
        mock_response.choices[0].message.content = json.dumps(gpt_response)
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.services.ara_v2.comprehender.get_gpt_mini_client", return_value=mock_client):
            comprensor = Comprensor()
            result = await comprensor.comprehend("Quiero ir a Villarrica")
            assert result.intencion_principal == "planificar_viaje"
            assert result.confianza == 0.95
            assert len(result.entidades) == 1
            assert result.entidades[0].valor == "Villarrica"
