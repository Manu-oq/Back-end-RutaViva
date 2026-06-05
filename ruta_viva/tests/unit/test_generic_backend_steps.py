from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.itinerary_constants import CHILE_TZ
from app.models.ara_message import AraMessage  # noqa: F401
from app.models.ara_session import AraSession  # noqa: F401
from app.models.bookmark import Bookmark  # noqa: F401
from app.models.category import Category  # noqa: F401
from app.models.conversation_memory import ConversationMemory  # noqa: F401
from app.models.entrepreneur_post import EntrepreneurPost  # noqa: F401
from app.models.entrepreneur_profile import EntrepreneurProfile  # noqa: F401
from app.models.poi_category import POICategory  # noqa: F401
from app.models.review import Review  # noqa: F401
from app.models.itinerary import Itinerary  # noqa: F401
from app.models.itinerary_step import ItineraryStep  # noqa: F401
from app.models.poi import POI  # noqa: F401
from app.models.tourist_profile import TouristProfile  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.poi_visit import POIVisit
from app.repositories.itinerary_repository import ItineraryRepository
from app.schemas.itinerary import GenerateItineraryRequest, GeneratedItinerary, GeneratedItineraryStep
from app.schemas.poi import POIResponse
from app.services.itinerary_generation_service import repair_schedule_and_category_issues


def _poi(name: str = "POI", *, category_ids: list[int] | None = None, visit_rules: dict | None = None) -> POIResponse:
    return POIResponse(
        id=uuid4(),
        name=name,
        description=f"Descripción de prueba para {name}",
        access_type="public",
        latitude=-39.0,
        longitude=-72.0,
        category_ids=category_ids or [1],
        verification_status="verified",
        confidence_score=0.9,
        visit_rules=visit_rules,
    )


def _payload() -> GenerateItineraryRequest:
    return GenerateItineraryRequest(
        query="ruta por Pucón",
        lat=-39.0,
        lon=-72.0,
        radius=5000,
        start_date=date(2026, 6, 15),
        end_date=date(2026, 6, 15),
    )


def test_repair_schedule_and_category_issues_ignores_generic_steps() -> None:
    closed_poi = _poi(
        "Restaurante cerrado",
        category_ids=[2],
        visit_rules={
            "opening_hours_structured": {
                "monday": [{"open": "09:00", "close": "10:00"}],
            }
        },
    )
    replacement = _poi("Reemplazo disponible", category_ids=[1])
    generic_step = GeneratedItineraryStep(
        step_order=1,
        poi_id=None,
        name="Almuerzo",
        is_generic=True,
        lat=None,
        lon=None,
        arrival_time=datetime(2026, 6, 15, 13, tzinfo=CHILE_TZ),
        departure_time=datetime(2026, 6, 15, 14, tzinfo=CHILE_TZ),
        ai_context={"is_generic_meal": True, "meal_type": "lunch"},
    )
    itinerary = GeneratedItinerary(title="Ruta", steps=[generic_step])

    repaired = repair_schedule_and_category_issues(
        itinerary,
        [closed_poi, replacement],
        _payload(),
    )

    assert repaired.steps[0].poi_id is None
    assert repaired.steps[0].name == "Almuerzo"
    assert repaired.steps[0].is_generic is True
    assert "system_repair" not in repaired.steps[0].ai_context


@pytest.mark.asyncio
async def test_create_generated_itinerary_does_not_create_poi_visit_for_generic_steps() -> None:
    real_poi_id = uuid4()
    tourist_id = uuid4()
    generated = GeneratedItinerary(
        title="Ruta mixta",
        steps=[
            GeneratedItineraryStep(
                step_order=1,
                poi_id=None,
                name="Almuerzo",
                is_generic=True,
                arrival_time=datetime(2026, 6, 15, 13, tzinfo=CHILE_TZ),
                departure_time=datetime(2026, 6, 15, 14, tzinfo=CHILE_TZ),
                ai_context={"is_generic_meal": True},
            ),
            GeneratedItineraryStep(
                step_order=2,
                poi_id=real_poi_id,
                arrival_time=datetime(2026, 6, 15, 15, tzinfo=CHILE_TZ),
                departure_time=datetime(2026, 6, 15, 16, tzinfo=CHILE_TZ),
            ),
        ],
    )

    class FakeDB:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.added_all: list[object] = []
            self.commit = AsyncMock()
            self.rollback = AsyncMock()

        def add(self, item: object) -> None:
            self.added.append(item)

        def add_all(self, items) -> None:
            self.added_all.extend(list(items))

        async def flush(self) -> None:
            return None

    db = FakeDB()
    repo = ItineraryRepository()
    repo.get_itinerary_by_id = AsyncMock(return_value=MagicMock(id=uuid4()))  # type: ignore[method-assign]

    await repo.create_generated_itinerary(
        db,  # type: ignore[arg-type]
        tourist_id,
        date(2026, 6, 15),
        date(2026, 6, 15),
        generated,
    )

    visits = [item for item in db.added_all if isinstance(item, POIVisit)]
    assert len(visits) == 1
    assert visits[0].poi_id == real_poi_id
