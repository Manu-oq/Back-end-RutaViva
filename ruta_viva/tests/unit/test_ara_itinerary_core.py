from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.models.user import User
from app.schemas.ara import AraGenerateItineraryRequest
from app.schemas.itinerary import GeneratedItinerary, GeneratedItineraryStep
from app.schemas.poi import POIResponse


def _make_poi(
    poi_id: UUID | None = None,
    name: str = "Test POI",
    lat: float = -39.0,
    lon: float = -72.0,
) -> POIResponse:
    return POIResponse(
        id=poi_id or uuid4(),
        name=name,
        description=f"Test description for {name}",
        access_type="public",
        latitude=lat,
        longitude=lon,
        category_ids=[1],
        verification_status="verified",
        confidence_score=0.8,
    )


def _make_user(has_transport: bool = False) -> MagicMock:
    profile = MagicMock()
    profile.has_own_transport = has_transport
    profile.interests_embedding = None
    user = MagicMock(spec=User)
    user.tourist_profile = profile
    user.id = uuid4()
    return user


def _make_session(lat: float = -39.0, lon: float = -72.0) -> MagicMock:
    session = MagicMock()
    session.id = uuid4()
    session.lat = lat
    session.lon = lon
    session.radius = 5000
    session.start_date = date(2026, 6, 15)
    session.end_date = date(2026, 6, 17)
    session.status = "clarifying"
    session.initial_query = "viaje a Pucon"
    session.intent_data = {"initial_query": "viaje a Pucon"}
    session.preferences_data = {"trip_draft": {"has_destination": True}}
    session.messages = []
    session.candidate_poi_ids = []
    session.generated_itinerary_id = None
    return session


def _make_valid_llm_response(poi_id: UUID | None = None) -> dict:
    return {
        "title": "Fin de semana en Pucón",
        "status": "planned",
        "steps": [
            {
                "step_order": 1,
                "poi_id": str(poi_id or uuid4()),
                "arrival_time": "2026-06-15T09:00:00-04:00",
                "departure_time": "2026-06-15T12:00:00-04:00",
                "ai_context": {"reason": "Primer dia", "tips": "Llevar agua"},
            },
            {
                "step_order": 2,
                "poi_id": str(uuid4()),
                "arrival_time": "2026-06-16T09:00:00-04:00",
                "departure_time": "2026-06-16T12:00:00-04:00",
                "ai_context": {"reason": "Segundo dia", "tips": "Ropa abrigada"},
            },
        ],
    }


@pytest.fixture
def mock_dependencies():
    with (
        patch("app.services.ara_itinerary_core.EmbeddingCache") as mock_cache,
        patch("app.services.ara_itinerary_core.build_refined_query") as mock_refined,
        patch("app.services.ara_itinerary_core.normalize_dates") as mock_dates,
        patch("app.services.ara_itinerary_core.trip_days") as mock_trip,
        patch("app.services.ara_itinerary_core.get_forecast") as mock_weather,
        patch("app.services.ara_itinerary_core.build_schedule_guidance") as mock_schedule,
        patch("app.services.ara_itinerary_core.repair_invalid_poi_ids") as mock_repair_ids,
        patch("app.services.ara_itinerary_core.repair_latest_start_times") as mock_repair_times,
        patch("app.services.ara_itinerary_core.repair_lodging_duplicates") as mock_repair_lodging,
        patch("app.services.ara_itinerary_core.repair_duplicate_poi_steps") as mock_repair_dupes,
        patch("app.services.ara_itinerary_core.repair_schedule_and_category_issues") as mock_repair_sched,
        patch("app.services.ara_itinerary_core.normalize_generated_itinerary_times") as mock_norm,
        patch("app.services.ara_itinerary_core.validate_generated_itinerary_rules") as mock_validate,
        patch("app.services.ara_itinerary_core.sanitize_generated_itinerary_context") as mock_sanitize,
        patch("app.services.ara_itinerary_core.POIRepository") as mock_poi_repo,
        patch("app.services.osrm_client.get_osrm_client") as mock_osrm,
    ):
        mock_refined.return_value = "consulta refinada"
        mock_dates.return_value = (date(2026, 6, 15), date(2026, 6, 17))
        mock_trip.return_value = 3
        mock_weather.return_value = "clima simulado"
        mock_schedule.return_value = "guia de programacion"

        ara_instance = MagicMock()
        ara_instance.update_session_context = AsyncMock()

        repo_instance = MagicMock()
        repo_instance.create_generated_itinerary = AsyncMock()
        repo_instance.get_itinerary_by_id = AsyncMock()

        poi_instance = MagicMock()
        poi_instance.get_pois_by_ids = AsyncMock(return_value=[])
        poi_instance.search_hybrid = AsyncMock(return_value=[])
        mock_poi_repo.return_value = poi_instance

        yield {
            "cache": mock_cache,
            "refined": mock_refined,
            "dates": mock_dates,
            "trip": mock_trip,
            "weather": mock_weather,
            "schedule": mock_schedule,
            "repair_ids": mock_repair_ids,
            "repair_times": mock_repair_times,
            "repair_lodging": mock_repair_lodging,
            "repair_dupes": mock_repair_dupes,
            "repair_sched": mock_repair_sched,
            "norm": mock_norm,
            "validate": mock_validate,
            "sanitize": mock_sanitize,
            "itinerary_repo": repo_instance,
            "ara_repo": ara_instance,
            "poi_repo": poi_instance,
            "osrm": mock_osrm,
        }


class TestTransportInPrompt:
    @pytest.mark.asyncio
    async def test_has_transport_passed_to_llm(self, mock_dependencies):
        from app.services.ara_itinerary_core import generate_itinerary_core

        user = _make_user(has_transport=True)
        session = _make_session()
        poi = _make_poi()
        mock_dependencies["poi_repo"].search_hybrid = AsyncMock(return_value=[poi])

        llm_response = _make_valid_llm_response(poi.id)
        llm = MagicMock()
        llm.generate_itinerary = AsyncMock(return_value=llm_response)

        mock_dependencies["itinerary_repo"].create_generated_itinerary = AsyncMock()
        mock_dependencies["itinerary_repo"].get_itinerary_by_id = AsyncMock()

        await generate_itinerary_core(
                session=session,
                payload=None,
                db=MagicMock(),
                current_user=user,
                embedding_service=MagicMock(),
                llm_service=llm,
                candidate_pois=[poi],
                ara_repository=mock_dependencies["ara_repo"],
                itinerary_repository=mock_dependencies["itinerary_repo"],
                poi_repository=mock_dependencies["poi_repo"],
            )

        call_kwargs = llm.generate_itinerary.call_args
        assert call_kwargs is not None
        assert call_kwargs.kwargs.get("has_own_transport") is True

    @pytest.mark.asyncio
    async def test_no_transport_passed_to_llm(self, mock_dependencies):
        from app.services.ara_itinerary_core import generate_itinerary_core

        user = _make_user(has_transport=False)
        session = _make_session()
        poi = _make_poi()
        mock_dependencies["poi_repo"].search_hybrid = AsyncMock(return_value=[poi])

        llm_response = _make_valid_llm_response(poi.id)
        llm = MagicMock()
        llm.generate_itinerary = AsyncMock(return_value=llm_response)

        mock_dependencies["itinerary_repo"].create_generated_itinerary = AsyncMock()
        mock_dependencies["itinerary_repo"].get_itinerary_by_id = AsyncMock()

        await generate_itinerary_core(
            session=session,
            payload=None,
            db=MagicMock(),
            current_user=user,
            embedding_service=MagicMock(),
            llm_service=llm,
            candidate_pois=[poi],
            ara_repository=mock_dependencies["ara_repo"],
            itinerary_repository=mock_dependencies["itinerary_repo"],
            poi_repository=mock_dependencies["poi_repo"],
        )

        call_kwargs = llm.generate_itinerary.call_args
        assert call_kwargs.kwargs.get("has_own_transport") is False


class TestTravelMatrix:
    @pytest.mark.asyncio
    async def test_osrm_matrix_included_in_query(self, mock_dependencies):
        from app.services.ara_itinerary_core import generate_itinerary_core

        user = _make_user(has_transport=True)
        session = _make_session()
        poi_a = _make_poi(name="Plaza Pucón", lat=-39.282, lon=-71.977)
        poi_b = _make_poi(name="Volcán Villarrica", lat=-39.420, lon=-71.940)
        mock_dependencies["poi_repo"].search_hybrid = AsyncMock(return_value=[poi_a, poi_b])

        osrm_client = MagicMock()
        osrm_client.get_table = AsyncMock(return_value=[
            [{"duration_seconds": 0, "distance_meters": 0}, {"duration_seconds": 1800, "distance_meters": 25000}],
            [{"duration_seconds": 1800, "distance_meters": 25000}, {"duration_seconds": 0, "distance_meters": 0}],
        ])
        mock_dependencies["osrm"].return_value = osrm_client

        llm_response = _make_valid_llm_response()
        llm = MagicMock()
        llm.generate_itinerary = AsyncMock(return_value=llm_response)

        mock_dependencies["itinerary_repo"].create_generated_itinerary = AsyncMock()
        mock_dependencies["itinerary_repo"].get_itinerary_by_id = AsyncMock()

        await generate_itinerary_core(
            session=session,
            payload=None,
            db=MagicMock(),
            current_user=user,
            embedding_service=MagicMock(),
            llm_service=llm,
            candidate_pois=[poi_a, poi_b],
            ara_repository=mock_dependencies["ara_repo"],
            itinerary_repository=mock_dependencies["itinerary_repo"],
            poi_repository=mock_dependencies["poi_repo"],
        )

        enriched_query = llm.generate_itinerary.call_args.args[0]
        assert "Tiempos de traslado" in enriched_query
        assert "Plaza Pucón" in enriched_query
        assert "Volcán Villarrica" in enriched_query

    @pytest.mark.asyncio
    async def test_haversine_fallback_when_osrm_unavailable(self, mock_dependencies):
        from app.services.ara_itinerary_core import generate_itinerary_core

        user = _make_user(has_transport=False)
        session = _make_session()
        poi_a = _make_poi(name="Plaza Pucón", lat=-39.282, lon=-71.977)
        poi_b = _make_poi(name="Volcán Villarrica", lat=-39.420, lon=-71.940)
        mock_dependencies["poi_repo"].search_hybrid = AsyncMock(return_value=[poi_a, poi_b])

        osrm_client = MagicMock()
        osrm_client.get_table = AsyncMock(return_value=None)
        mock_dependencies["osrm"].return_value = osrm_client

        llm_response = _make_valid_llm_response()
        llm = MagicMock()
        llm.generate_itinerary = AsyncMock(return_value=llm_response)

        mock_dependencies["itinerary_repo"].create_generated_itinerary = AsyncMock()
        mock_dependencies["itinerary_repo"].get_itinerary_by_id = AsyncMock()

        await generate_itinerary_core(
            session=session,
            payload=None,
            db=MagicMock(),
            current_user=user,
            embedding_service=MagicMock(),
            llm_service=llm,
            candidate_pois=[poi_a, poi_b],
            ara_repository=mock_dependencies["ara_repo"],
            itinerary_repository=mock_dependencies["itinerary_repo"],
            poi_repository=mock_dependencies["poi_repo"],
        )

        enriched_query = llm.generate_itinerary.call_args.args[0]
        assert "Haversine" in enriched_query
        assert "pie (estimado)" in enriched_query

    @pytest.mark.asyncio
    async def test_single_poi_no_matrix(self, mock_dependencies):
        from app.services.ara_itinerary_core import generate_itinerary_core

        user = _make_user()
        session = _make_session()
        poi = _make_poi()
        mock_dependencies["poi_repo"].search_hybrid = AsyncMock(return_value=[poi])

        llm_response = _make_valid_llm_response(poi.id)
        llm = MagicMock()
        llm.generate_itinerary = AsyncMock(return_value=llm_response)

        mock_dependencies["itinerary_repo"].create_generated_itinerary = AsyncMock()
        mock_dependencies["itinerary_repo"].get_itinerary_by_id = AsyncMock()

        await generate_itinerary_core(
            session=session,
            payload=None,
            db=MagicMock(),
            current_user=user,
            embedding_service=MagicMock(),
            llm_service=llm,
            candidate_pois=[poi],
            ara_repository=mock_dependencies["ara_repo"],
            itinerary_repository=mock_dependencies["itinerary_repo"],
            poi_repository=mock_dependencies["poi_repo"],
        )

        enriched_query = llm.generate_itinerary.call_args.args[0]
        assert "Tiempos de traslado" not in enriched_query


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_no_tourist_profile_raises(self, mock_dependencies):
        from app.services.ara_itinerary_core import generate_itinerary_core

        user = _make_user()
        user.tourist_profile = None
        session = _make_session()

        with pytest.raises(ValueError, match="Only tourist users"):
            await generate_itinerary_core(
                session=session,
                payload=None,
                db=MagicMock(),
                current_user=user,
                embedding_service=MagicMock(),
                llm_service=MagicMock(),
                ara_repository=mock_dependencies["ara_repo"],
                itinerary_repository=mock_dependencies["itinerary_repo"],
                poi_repository=mock_dependencies["poi_repo"],
            )

    @pytest.mark.asyncio
    async def test_no_destination_raises(self, mock_dependencies):
        from app.services.ara_itinerary_core import generate_itinerary_core

        user = _make_user()
        session = _make_session()
        session.lat = None
        session.lon = None
        session.preferences_data = {}

        with pytest.raises(ValueError, match="destination"):
            await generate_itinerary_core(
                session=session,
                payload=None,
                db=MagicMock(),
                current_user=user,
                embedding_service=MagicMock(),
                llm_service=MagicMock(),
                ara_repository=mock_dependencies["ara_repo"],
                itinerary_repository=mock_dependencies["itinerary_repo"],
                poi_repository=mock_dependencies["poi_repo"],
            )

    @pytest.mark.asyncio
    async def test_payload_with_final_instruction(self, mock_dependencies):
        from app.services.ara_itinerary_core import generate_itinerary_core

        user = _make_user()
        session = _make_session()
        poi = _make_poi()
        mock_dependencies["poi_repo"].search_hybrid = AsyncMock(return_value=[poi])

        llm_response = _make_valid_llm_response(poi.id)
        llm = MagicMock()
        llm.generate_itinerary = AsyncMock(return_value=llm_response)

        mock_dependencies["itinerary_repo"].create_generated_itinerary = AsyncMock()
        mock_dependencies["itinerary_repo"].get_itinerary_by_id = AsyncMock()

        payload = AraGenerateItineraryRequest(final_instruction="priorizar naturaleza")

        await generate_itinerary_core(
            session=session,
            payload=payload,
            db=MagicMock(),
            current_user=user,
            embedding_service=MagicMock(),
            llm_service=llm,
            candidate_pois=[poi],
            ara_repository=mock_dependencies["ara_repo"],
            itinerary_repository=mock_dependencies["itinerary_repo"],
            poi_repository=mock_dependencies["poi_repo"],
        )

        assert llm.generate_itinerary.called

    @pytest.mark.asyncio
    async def test_surprise_route_boosts_search(self, mock_dependencies):
        from app.services.ara_itinerary_core import generate_itinerary_core

        user = _make_user()
        session = _make_session()
        session.preferences_data = {"surprise_route_requested": True, "trip_draft": {"has_destination": True}}
        poi = _make_poi()
        mock_dependencies["poi_repo"].search_hybrid = AsyncMock(return_value=[poi])

        llm_response = _make_valid_llm_response(poi.id)
        llm = MagicMock()
        llm.generate_itinerary = AsyncMock(return_value=llm_response)

        mock_dependencies["itinerary_repo"].create_generated_itinerary = AsyncMock()
        mock_dependencies["itinerary_repo"].get_itinerary_by_id = AsyncMock()

        await generate_itinerary_core(
            session=session,
            payload=None,
            db=MagicMock(),
            current_user=user,
            embedding_service=MagicMock(),
            llm_service=llm,
            candidate_pois=[poi],
            ara_repository=mock_dependencies["ara_repo"],
            itinerary_repository=mock_dependencies["itinerary_repo"],
            poi_repository=mock_dependencies["poi_repo"],
        )

        assert llm.generate_itinerary.called


class TestBuildTravelMatrix:
    @pytest.mark.asyncio
    async def test_two_pois_builds_matrix(self):
        from app.services.ara_itinerary_core import _build_travel_matrix

        poi_a = _make_poi(name="A", lat=-39.0, lon=-72.0)
        poi_b = _make_poi(name="B", lat=-39.1, lon=-72.1)

        osrm_client = MagicMock()
        osrm_client.get_table = AsyncMock(return_value=[
            [{"duration_seconds": 0, "distance_meters": 0}, {"duration_seconds": 600, "distance_meters": 5000}],
            [{"duration_seconds": 600, "distance_meters": 5000}, {"duration_seconds": 0, "distance_meters": 0}],
        ])

        with patch("app.services.osrm_client.get_osrm_client", return_value=osrm_client):
            result = await _build_travel_matrix([poi_a, poi_b], profile="driving")

        assert result is not None
        assert "Tiempos de traslado" in result
        assert "A → B" in result
        assert "5.0km" in result
        assert "10min" in result

    @pytest.mark.asyncio
    async def test_single_poi_returns_none(self):
        from app.services.ara_itinerary_core import _build_travel_matrix

        result = await _build_travel_matrix([_make_poi()], profile="driving")
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_pois_returns_none(self):
        from app.services.ara_itinerary_core import _build_travel_matrix

        result = await _build_travel_matrix([], profile="driving")
        assert result is None

    @pytest.mark.asyncio
    async def test_haversine_fallback_when_osrm_table_returns_none(self):
        from app.services.ara_itinerary_core import _build_travel_matrix

        poi_a = _make_poi(name="A", lat=-39.0, lon=-72.0)
        poi_b = _make_poi(name="B", lat=-39.1, lon=-72.1)

        osrm_client = MagicMock()
        osrm_client.get_table = AsyncMock(return_value=None)

        with patch("app.services.osrm_client.get_osrm_client", return_value=osrm_client):
            result = await _build_travel_matrix([poi_a, poi_b], profile="foot")

        assert result is not None
        assert "Haversine" in result
        assert "pie (estimado)" in result

    @pytest.mark.asyncio
    async def test_max_pois_limit(self):
        from app.services.ara_itinerary_core import _build_travel_matrix

        pois = [_make_poi(name=f"POI{i}", lat=-39.0 + i * 0.01, lon=-72.0 + i * 0.01) for i in range(20)]

        osrm_client = MagicMock()
        osrm_client.get_table = AsyncMock(return_value=None)

        with patch("app.services.osrm_client.get_osrm_client", return_value=osrm_client):
            result = await _build_travel_matrix(pois, profile="foot", max_pois=5)

        assert result is not None
        assert "POI0" in result
        assert "POI5" not in result


class TestGenericMealSteps:
    @pytest.mark.asyncio
    async def test_meal_slots_are_saved_as_generic_steps(self, mock_dependencies):
        from app.services.ara_itinerary_core import generate_itinerary_core

        user = _make_user()
        session = _make_session()
        session.preferences_data = {
            "trip_draft": {
                "has_destination": True,
                "slots": [
                    {
                        "type": "meal",
                        "meal_type": "lunch",
                        "time": "13:30",
                        "status": "requested",
                        "poi_id": None,
                    }
                ],
            }
        }
        poi = _make_poi()

        llm = MagicMock()
        llm.generate_itinerary = AsyncMock(
            return_value={
                "title": "Ruta con almuerzo",
                "status": "planned",
                "steps": [
                    {
                        "step_order": 1,
                        "poi_id": str(poi.id),
                        "arrival_time": "2026-06-15T09:00:00-04:00",
                        "departure_time": "2026-06-15T11:00:00-04:00",
                        "ai_context": {"reason": "Actividad principal"},
                    }
                ],
            }
        )

        repo = MagicMock()
        repo.create_generated_itinerary = AsyncMock(return_value=MagicMock(id=uuid4()))
        ara_repo = MagicMock()
        ara_repo.update_session_context = AsyncMock()

        passthrough = lambda itinerary, *args, **kwargs: itinerary
        mock_dependencies["norm"].side_effect = passthrough
        mock_dependencies["repair_ids"].side_effect = passthrough
        mock_dependencies["repair_times"].side_effect = passthrough
        mock_dependencies["repair_lodging"].side_effect = passthrough
        mock_dependencies["repair_dupes"].side_effect = passthrough
        mock_dependencies["repair_sched"].side_effect = passthrough
        mock_dependencies["sanitize"].side_effect = passthrough
        mock_dependencies["validate"].return_value = None

        await generate_itinerary_core(
            session=session,
            payload=None,
            db=MagicMock(),
            current_user=user,
            embedding_service=MagicMock(),
            llm_service=llm,
            candidate_pois=[poi],
            ara_repository=ara_repo,
            itinerary_repository=repo,
            poi_repository=mock_dependencies["poi_repo"],
        )

        saved_itinerary = repo.create_generated_itinerary.call_args.args[4]
        generic_steps = [step for step in saved_itinerary.steps if step.is_generic]
        assert len(generic_steps) == 1
        assert generic_steps[0].poi_id is None
        assert generic_steps[0].name == "Almuerzo"
        assert generic_steps[0].lat is None
        assert generic_steps[0].lon is None
        assert generic_steps[0].ai_context["is_generic_meal"] is True
