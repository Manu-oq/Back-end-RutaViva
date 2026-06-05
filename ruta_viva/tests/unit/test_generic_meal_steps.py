from __future__ import annotations

from datetime import date, datetime, timedelta
from uuid import uuid4

from app.core.itinerary_constants import CHILE_TZ
from app.repositories.itinerary_repository import ItineraryRepository
from app.schemas.ara_comprehension import ComprehensionResult, QuickReplySuggestion, ToolExecutionResult
from app.schemas.itinerary import GenerateItineraryRequest, GeneratedItinerary, GeneratedItineraryStep
from app.schemas.poi import POIResponse
from app.services.ara_itinerary_core import normalize_generic_meal_steps
from app.services.ara_v2.response_generator import ResponseGenerator
from app.services.itinerary_generation_service import (
    repair_duplicate_poi_steps,
    validate_generated_itinerary_rules,
)


def _poi(*, poi_id=None, name="POI", category_ids=None) -> POIResponse:
    return POIResponse(
        id=poi_id or uuid4(),
        name=name,
        description="Descripción suficiente para pruebas",
        access_type="public",
        category_ids=category_ids or [1],
        latitude=-39.0,
        longitude=-72.0,
    )


def _payload() -> GenerateItineraryRequest:
    return GenerateItineraryRequest(
        query="arma una ruta",
        lat=-39.0,
        lon=-72.0,
        radius=5000,
        start_date=date(2026, 6, 15),
        end_date=date(2026, 6, 15),
    )


def test_normalize_generic_meal_steps_creates_requested_meal_without_poi() -> None:
    generated = GeneratedItinerary(title="Ruta", steps=[])

    normalized = normalize_generic_meal_steps(
        generated,
        [{"type": "meal", "meal_type": "lunch", "time": "13:30"}],
        date(2026, 6, 15),
    )

    assert len(normalized.steps) == 1
    step = normalized.steps[0]
    assert step.poi_id is None
    assert step.name == "Almuerzo"
    assert step.is_generic is True
    assert step.lat is None
    assert step.lon is None
    assert step.ai_context["is_generic_meal"] is True
    assert step.arrival_time == datetime(2026, 6, 15, 13, 30, tzinfo=CHILE_TZ)


def test_repairs_and_validation_ignore_generic_steps() -> None:
    real_poi = _poi(category_ids=[1])
    duplicate = GeneratedItineraryStep(
        step_order=1,
        poi_id=real_poi.id,
        arrival_time=datetime(2026, 6, 15, 9, tzinfo=CHILE_TZ),
        departure_time=datetime(2026, 6, 15, 10, tzinfo=CHILE_TZ),
    )
    generic = GeneratedItineraryStep(
        step_order=2,
        poi_id=None,
        name="Almuerzo",
        is_generic=True,
        arrival_time=datetime(2026, 6, 15, 13, tzinfo=CHILE_TZ),
        departure_time=datetime(2026, 6, 15, 14, tzinfo=CHILE_TZ),
        ai_context={"is_generic_meal": True},
    )
    itinerary = GeneratedItinerary(title="Ruta", steps=[duplicate, generic])

    repaired = repair_duplicate_poi_steps(itinerary, [real_poi], _payload())
    assert repaired.steps[1].poi_id is None

    validate_generated_itinerary_rules(repaired, [real_poi], _payload())


def test_step_to_response_serializes_generic_step_without_poi() -> None:
    class Step:
        id = uuid4()
        itinerary_id = uuid4()
        poi_id = None
        name = "Desayuno"
        is_generic = True
        poi = None
        step_order = 1
        arrival_time = datetime(2026, 6, 15, 9, tzinfo=CHILE_TZ)
        departure_time = datetime(2026, 6, 15, 10, tzinfo=CHILE_TZ)
        ai_context = {"is_generic_meal": True}
        created_at = None
        updated_at = None

    response = ItineraryRepository()._step_to_response(Step(), date(2026, 6, 15))

    assert response.poi_id is None
    assert response.name == "Desayuno"
    assert response.poi_name == "Desayuno"
    assert response.is_generic is True
    assert response.lat is None
    assert response.lon is None


def test_clarify_response_filters_generate_quick_reply_when_slots_missing() -> None:
    class Session:
        preferences_data = {"trip_draft": {"slots": [{"status": "empty"}]}}

    comprehension = ComprehensionResult(
        confianza=0.9,
        sugerir_quick_replies=[
            QuickReplySuggestion(label="Generar", value="generar", type="generate"),
            QuickReplySuggestion(label="Agregar tarde", value="tarde", type="action"),
        ],
    )
    tool_result = ToolExecutionResult(status="clarify", response_text="Falta completar algo")

    response = ResponseGenerator._generate_clarify_response(comprehension, tool_result, Session())

    assert [reply.type for reply in response["quick_replies"]] == ["action"]
