from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.schemas.ara_comprehension import ComprehensionResult, ExtractedEntity
from app.services.ara_v2.conversation_processor import ConversationProcessor
from app.services.ara_v2.slot_state import are_all_slots_filled, is_slot_filled


def _make_comprehension_with_category(category: str = "naturaleza") -> ComprehensionResult:
    return ComprehensionResult(
        confianza=0.9,
        entidades=[ExtractedEntity(tipo="categoria", valor=category, confianza=0.9)],
    )


def _make_comprehension_without_category() -> ComprehensionResult:
    return ComprehensionResult(confianza=0.5)


def _make_session_with_slots(slots: list[dict]) -> MagicMock:
    session = MagicMock()
    session.preferences_data = {"trip_draft": {"slots": slots}}
    return session


class TestFillEmptySlotsOnCategory:
    def test_activity_goes_to_category_selected(self) -> None:
        trip_draft = {
            "slots": [
                {"type": "activity", "period": "morning", "status": "empty"},
            ]
        }
        comprehension = _make_comprehension_with_category("naturaleza")

        ConversationProcessor._fill_empty_slots_on_category(trip_draft, comprehension)

        assert trip_draft["slots"][0]["status"] == "category_selected"

    def test_meal_goes_to_filled(self) -> None:
        trip_draft = {
            "slots": [
                {"type": "meal", "meal_type": "lunch", "status": "empty", "poi_id": None},
            ]
        }
        comprehension = _make_comprehension_with_category("gastronomia")

        ConversationProcessor._fill_empty_slots_on_category(trip_draft, comprehension)

        assert trip_draft["slots"][0]["status"] == "filled"

    def test_no_category_does_nothing(self) -> None:
        trip_draft = {
            "slots": [
                {"type": "activity", "period": "morning", "status": "empty"},
            ]
        }
        comprehension = _make_comprehension_without_category()

        ConversationProcessor._fill_empty_slots_on_category(trip_draft, comprehension)

        assert trip_draft["slots"][0]["status"] == "empty"

    def test_only_fills_first_empty_slot(self) -> None:
        trip_draft = {
            "slots": [
                {"type": "activity", "period": "morning", "status": "empty"},
                {"type": "activity", "period": "afternoon", "status": "empty"},
            ]
        }
        comprehension = _make_comprehension_with_category("cultura")

        ConversationProcessor._fill_empty_slots_on_category(trip_draft, comprehension)

        assert trip_draft["slots"][0]["status"] == "category_selected"
        assert trip_draft["slots"][1]["status"] == "empty"


class TestIsSlotFilled:
    def test_activity_category_selected_without_poi_id_returns_false(self) -> None:
        slot = {"type": "activity", "period": "morning", "status": "category_selected"}

        assert is_slot_filled(slot) is False

    def test_activity_filled_with_poi_id_returns_true(self) -> None:
        slot = {"type": "activity", "period": "morning", "status": "filled", "poi_id": str(uuid4())}

        assert is_slot_filled(slot) is True

    def test_activity_filled_without_poi_id_returns_false(self) -> None:
        slot = {"type": "activity", "period": "morning", "status": "filled"}

        assert is_slot_filled(slot) is False

    def test_activity_requested_without_poi_id_returns_false(self) -> None:
        slot = {"type": "activity", "period": "afternoon", "status": "requested"}

        assert is_slot_filled(slot) is False

    def test_meal_filled_without_poi_id_returns_true(self) -> None:
        slot = {"type": "meal", "meal_type": "lunch", "status": "filled"}

        assert is_slot_filled(slot) is True

    def test_meal_requested_without_poi_id_returns_true(self) -> None:
        slot = {"type": "meal", "meal_type": "breakfast", "status": "requested"}

        assert is_slot_filled(slot) is True


class TestAreAllSlotsFilled:
    def test_with_one_category_selected_returns_false(self) -> None:
        slots = [
            {"type": "activity", "period": "morning", "status": "filled", "poi_id": str(uuid4())},
            {"type": "activity", "period": "afternoon", "status": "category_selected"},
        ]
        session = _make_session_with_slots(slots)

        assert are_all_slots_filled(session) is False

    def test_all_filled_returns_true(self) -> None:
        slots = [
            {"type": "activity", "period": "morning", "status": "filled", "poi_id": str(uuid4())},
            {"type": "meal", "meal_type": "lunch", "status": "filled"},
        ]
        session = _make_session_with_slots(slots)

        assert are_all_slots_filled(session) is True

    def test_no_slots_returns_false(self) -> None:
        session = _make_session_with_slots([])

        assert are_all_slots_filled(session) is False

    def test_mixed_meal_requested_and_activity_filled_returns_true(self) -> None:
        slots = [
            {"type": "activity", "period": "morning", "status": "filled", "poi_id": str(uuid4())},
            {"type": "meal", "meal_type": "lunch", "status": "requested", "poi_id": None},
        ]
        session = _make_session_with_slots(slots)

        assert are_all_slots_filled(session) is True

    def test_activity_empty_among_filled_returns_false(self) -> None:
        slots = [
            {"type": "activity", "period": "morning", "status": "filled", "poi_id": str(uuid4())},
            {"type": "activity", "period": "afternoon", "status": "empty"},
        ]
        session = _make_session_with_slots(slots)

        assert are_all_slots_filled(session) is False
