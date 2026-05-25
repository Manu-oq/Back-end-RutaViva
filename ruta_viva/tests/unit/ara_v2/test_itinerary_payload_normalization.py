from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import UUID, uuid4

from app.schemas.itinerary import GenerateItineraryRequest, GeneratedItinerary
from app.services.itinerary_generation_service import normalize_generated_itinerary_times
from app.services.llm_service import _normalize_itinerary_payload


def test_normalizes_legacy_days_steps_payload_to_flat_steps():
    poi_id = str(uuid4())

    normalized = _normalize_itinerary_payload({
        "title": "Ruta por Pucón",
        "days": [
            {
                "day_index": 0,
                "steps": [
                    {
                        "poi_id": poi_id,
                        "poi_name": "Mirador",
                        "scheduled_time": "09:00",
                        "duration_minutes": 75,
                        "notes": "Vista panorámica",
                    }
                ],
            }
        ],
    })

    itinerary = GeneratedItinerary.model_validate(normalized)

    assert itinerary.steps
    assert itinerary.steps[0].poi_id == UUID(poi_id)
    assert itinerary.steps[0].ai_context["scheduled_time"] == "09:00"
    assert itinerary.steps[0].ai_context["day_position"] == 0


def test_fills_missing_times_from_legacy_ai_context():
    poi_id = str(uuid4())
    itinerary = GeneratedItinerary.model_validate(
        _normalize_itinerary_payload({
            "title": "Ruta por Pucón",
            "days": [
                {
                    "day_index": 0,
                    "steps": [
                        {
                            "poi_id": poi_id,
                            "scheduled_time": "09:30",
                            "duration_minutes": 60,
                        }
                    ],
                }
            ],
        })
    )
    payload = GenerateItineraryRequest(
        query="Pucón naturaleza",
        lat=-39.28,
        lon=-71.95,
        radius=5000,
        start_date=date(2026, 5, 25),
        end_date=date(2026, 5, 27),
    )

    normalized = normalize_generated_itinerary_times(itinerary, payload)

    assert normalized.steps[0].arrival_time is not None
    assert normalized.steps[0].arrival_time.date() == date(2026, 5, 25)
    assert normalized.steps[0].arrival_time.hour == 9
    assert normalized.steps[0].arrival_time.minute == 30
    assert normalized.steps[0].departure_time is not None
    assert normalized.steps[0].departure_time.hour == 10
    assert normalized.steps[0].departure_time.minute == 30


def test_maps_llm_poi_name_to_context_uuid():
    poi_id = uuid4()
    normalized = _normalize_itinerary_payload(
        {
            "title": "Ruta por Pucón",
            "steps": [
                {
                    "step_order": 1,
                    "poi_id": "Pucón Outdoor",
                    "arrival_time": "2026-05-25T09:00:00-04:00",
                    "departure_time": "2026-05-25T10:00:00-04:00",
                }
            ],
        },
        context_pois=[SimpleNamespace(id=poi_id, name="Pucón Outdoor")],
    )
    itinerary = GeneratedItinerary.model_validate(normalized)

    assert itinerary.steps[0].poi_id == poi_id
    assert itinerary.steps[0].ai_context["original_poi_name"] == "Pucón Outdoor"
