from __future__ import annotations

from app.services.ara_v2.prompt_manager import (
    build_comprehension_prompt,
    build_generation_prompt,
)


class TestComprehensionPrompt:
    def test_contains_system_role(self):
        prompt = build_comprehension_prompt({"initial_query": "Villarrica", "turn_count": 1})
        assert "Ara" in prompt
        assert "comprensión" in prompt.lower()

    def test_contains_json_format_instruction(self):
        prompt = build_comprehension_prompt({"initial_query": "Villarrica"})
        assert "JSON" in prompt
        assert '"intenciones"' in prompt

    def test_injects_relevant_facts(self):
        context = {
            "initial_query": "Villarrica",
            "turn_count": 3,
            "lodging": {"name": "Hotel Test"},
            "relevant_facts": [
                {"hecho": "prefiere baja dificultad", "categoria": "preferencia", "confianza": 0.8},
            ],
        }
        prompt = build_comprehension_prompt(context)
        assert "prefiere baja dificultad" in prompt
        assert "[preferencia]" in prompt

    def test_injects_candidate_pois_count(self):
        context = {
            "initial_query": "Villarrica",
            "candidate_pois": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
        }
        prompt = build_comprehension_prompt(context)
        assert "3 POIs" in prompt


class TestGenerationPrompt:
    def test_contains_generation_rules(self):
        prompt = build_generation_prompt({"user_query": "Villarrica"})
        assert "planificador de viajes" in prompt.lower()
        assert "REGLAS DE GENERACIÓN" in prompt

    def test_injects_weather_forecast(self):
        context = {
            "user_query": "Villarrica",
            "weather_forecast": "Lluvia el sabado",
            "schedule_guidance": "Dia 1: Villarrica",
        }
        prompt = build_generation_prompt(context)
        assert "Lluvia el sabado" in prompt

    def test_injects_pois(self):
        context = {
            "user_query": "Villarrica",
            "context_pois": [
                {"name": "Volcan Villarrica", "category": "Naturaleza", "description": "Volcan activo"},
            ],
            "weather_forecast": "",
            "schedule_guidance": "",
        }
        prompt = build_generation_prompt(context)
        assert "Volcan Villarrica" in prompt
        assert "Naturaleza" in prompt

    def test_injects_preferences(self):
        context = {
            "user_query": "Villarrica",
            "food_preferences": ["vegetariano", "sin mariscos"],
            "activity_preferences": ["senderismo"],
            "weather_forecast": "",
            "schedule_guidance": "",
        }
        prompt = build_generation_prompt(context)
        assert "vegetariano" in prompt
        assert "sin mariscos" in prompt
        assert "senderismo" in prompt
