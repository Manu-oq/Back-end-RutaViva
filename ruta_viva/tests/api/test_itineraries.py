from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from geoalchemy2.elements import WKTElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import itineraries as itineraries_endpoint
from app.core.security import create_access_token
from app.core.time_utils import CHILE_TZ
from app.models.itinerary import Itinerary
from app.models.itinerary_step import ItineraryStep
from app.models.poi import POI
from app.models.tourist_profile import TouristProfile
from app.models.user import User
from app.repositories.itinerary_repository import ItineraryRepository
from app.schemas.weather import WeatherDailyForecast


async def _create_tourist_user(db_session: AsyncSession, email: str | None = None) -> User:
    if email is None:
        from uuid import uuid4
        email = f"itinerary-test-{uuid4().hex[:8]}@rutaviva.cl"
    user = User(
        email=email,
        password_hash="hashed-password",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        TouristProfile(
            user_id=user.id,
            full_name="Itinerary Test User",
            has_own_transport=False,
        )
    )
    await db_session.flush()
    return user


async def _create_poi(db_session: AsyncSession, name: str, lon: float, lat: float) -> POI:
    poi = POI(
        name=name,
        description=f"{name} description",
        location=WKTElement(f"POINT({lon} {lat})", srid=4326),
        description_embedding=[0.0] * 1536,
        access_type="public",
        multimedia_urls={"cover": None, "gallery": []},
        visit_rules={},
        verification_status="verified",
        confidence_score=1.0,
    )
    db_session.add(poi)
    await db_session.flush()
    return poi


async def _create_itinerary_fixture(
    db_session: AsyncSession,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    status: str = "planned",
) -> tuple[User, Itinerary]:
    user = await _create_tourist_user(db_session)
    poi_1 = await _create_poi(db_session, "POI 1", -72.0, -39.0)
    poi_2 = await _create_poi(db_session, "POI 2", -72.1, -39.1)
    poi_3 = await _create_poi(db_session, "POI 3", -72.2, -39.2)
    itinerary_start_date = start_date or (datetime.now(CHILE_TZ).date() + timedelta(days=7))
    itinerary_end_date = end_date or (itinerary_start_date + timedelta(days=1))

    itinerary = Itinerary(
        tourist_id=user.id,
        title="Test itinerary",
        start_date=itinerary_start_date,
        end_date=itinerary_end_date,
        status=status,
    )
    db_session.add(itinerary)
    await db_session.flush()

    steps = [
        ItineraryStep(
            itinerary_id=itinerary.id,
            poi_id=poi_1.id,
            step_order=1,
            arrival_time=datetime(
                itinerary_start_date.year, itinerary_start_date.month, itinerary_start_date.day, 9, 0, tzinfo=CHILE_TZ
            ),
            departure_time=datetime(
                itinerary_start_date.year, itinerary_start_date.month, itinerary_start_date.day, 10, 0, tzinfo=CHILE_TZ
            ),
        ),
        ItineraryStep(
            itinerary_id=itinerary.id,
            poi_id=poi_2.id,
            step_order=2,
            arrival_time=datetime(
                itinerary_start_date.year, itinerary_start_date.month, itinerary_start_date.day, 10, 15, tzinfo=CHILE_TZ
            ),
            departure_time=datetime(
                itinerary_start_date.year, itinerary_start_date.month, itinerary_start_date.day, 11, 15, tzinfo=CHILE_TZ
            ),
        ),
        ItineraryStep(
            itinerary_id=itinerary.id,
            poi_id=poi_3.id,
            step_order=3,
            arrival_time=datetime(
                itinerary_end_date.year, itinerary_end_date.month, itinerary_end_date.day, 9, 0, tzinfo=CHILE_TZ
            ),
            departure_time=datetime(
                itinerary_end_date.year, itinerary_end_date.month, itinerary_end_date.day, 10, 30, tzinfo=CHILE_TZ
            ),
        ),
    ]
    db_session.add_all(steps)
    await db_session.flush()
    return user, itinerary


@pytest.mark.asyncio
async def test_reorder_with_times_recalculates_order_and_times(
    async_client,
    db_session: AsyncSession,
) -> None:
    user, itinerary = await _create_itinerary_fixture(db_session)
    repository = ItineraryRepository()
    itinerary_state = await repository.get_itinerary_by_id(db_session, itinerary.id, user.id)
    assert itinerary_state is not None

    headers = {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}
    reordered_steps = [
        {
            "step_id": str(itinerary_state.steps[1].id),
            "day_index": 1,
            "position": 0,
        },
        {
            "step_id": str(itinerary_state.steps[0].id),
            "day_index": 1,
            "position": 1,
        },
        {
            "step_id": str(itinerary_state.steps[2].id),
            "day_index": 2,
            "position": 0,
        },
    ]

    response = await async_client.patch(
        f"/api/v1/itineraries/{itinerary.id}/steps/reorder-with-times",
        json={"steps": reordered_steps},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert [step["step_order"] for step in payload["steps"]] == [2, 1, 3]
    assert [step["day_index"] for step in payload["steps"]] == [1, 1, 2]
    assert [step["poi_name"] for step in payload["steps"]] == ["POI 1", "POI 2", "POI 3"]
    assert datetime.fromisoformat(payload["steps"][0]["arrival_time"]).astimezone(CHILE_TZ).strftime("%H:%M:%S") == "10:15:00"
    assert datetime.fromisoformat(payload["steps"][0]["departure_time"]).astimezone(CHILE_TZ).strftime("%H:%M:%S") == "11:15:00"
    assert datetime.fromisoformat(payload["steps"][1]["arrival_time"]).astimezone(CHILE_TZ).strftime("%H:%M:%S") == "09:00:00"
    assert datetime.fromisoformat(payload["steps"][1]["departure_time"]).astimezone(CHILE_TZ).strftime("%H:%M:%S") == "10:00:00"
    assert datetime.fromisoformat(payload["steps"][2]["arrival_time"]).astimezone(CHILE_TZ).strftime("%H:%M:%S") == "09:00:00"
    assert datetime.fromisoformat(payload["steps"][2]["departure_time"]).astimezone(CHILE_TZ).strftime("%H:%M:%S") == "10:30:00"


@pytest.mark.asyncio
async def test_reorder_with_times_requires_all_steps(
    async_client,
    db_session: AsyncSession,
) -> None:
    user, itinerary = await _create_itinerary_fixture(db_session)
    repository = ItineraryRepository()
    itinerary_state = await repository.get_itinerary_by_id(db_session, itinerary.id, user.id)
    assert itinerary_state is not None

    headers = {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}
    response = await async_client.patch(
        f"/api/v1/itineraries/{itinerary.id}/steps/reorder-with-times",
        json={
            "steps": [
                {
                    "step_id": str(itinerary_state.steps[0].id),
                    "day_index": 1,
                    "position": 0,
                },
                {
                    "step_id": str(itinerary_state.steps[1].id),
                    "day_index": 1,
                    "position": 1,
                },
            ]
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert "missing itinerary step ids" in response.json()["detail"]


@pytest.mark.asyncio
async def test_reorder_with_times_rejects_duplicate_step_ids(
    async_client,
    db_session: AsyncSession,
) -> None:
    user, itinerary = await _create_itinerary_fixture(db_session)
    repository = ItineraryRepository()
    itinerary_state = await repository.get_itinerary_by_id(db_session, itinerary.id, user.id)
    assert itinerary_state is not None

    headers = {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}
    response = await async_client.patch(
        f"/api/v1/itineraries/{itinerary.id}/steps/reorder-with-times",
        json={
            "steps": [
                {
                    "step_id": str(itinerary_state.steps[0].id),
                    "day_index": 1,
                    "position": 0,
                },
                {
                    "step_id": str(itinerary_state.steps[0].id),
                    "day_index": 1,
                    "position": 1,
                },
                {
                    "step_id": str(itinerary_state.steps[2].id),
                    "day_index": 2,
                    "position": 0,
                },
            ]
        },
        headers=headers,
    )

    assert response.status_code == 422
    assert "duplicate step ids" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_itinerary_exposes_editability_flags(
    async_client,
    db_session: AsyncSession,
) -> None:
    future_start = datetime.now(CHILE_TZ).date() + timedelta(days=1)
    future_end = future_start + timedelta(days=1)
    user, itinerary = await _create_itinerary_fixture(
        db_session,
        start_date=future_start,
        end_date=future_end,
    )

    headers = {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}
    response = await async_client.get(
        f"/api/v1/itineraries/{itinerary.id}",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "planned"
    assert payload["is_past"] is False
    assert payload["is_editable"] is True


@pytest.mark.asyncio
async def test_past_itinerary_blocks_reorder_with_times(
    async_client,
    db_session: AsyncSession,
) -> None:
    past_start = datetime.now(CHILE_TZ).date() - timedelta(days=3)
    past_end = datetime.now(CHILE_TZ).date() - timedelta(days=2)
    user, itinerary = await _create_itinerary_fixture(
        db_session,
        start_date=past_start,
        end_date=past_end,
    )

    repository = ItineraryRepository()
    itinerary_state = await repository.get_itinerary_by_id(db_session, itinerary.id, user.id)
    assert itinerary_state is not None
    assert itinerary_state.is_past is True
    assert itinerary_state.is_editable is False

    headers = {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}
    response = await async_client.patch(
        f"/api/v1/itineraries/{itinerary.id}/steps/reorder-with-times",
        json={
            "steps": [
                {"step_id": str(itinerary_state.steps[1].id), "day_index": 1, "position": 0},
                {"step_id": str(itinerary_state.steps[0].id), "day_index": 1, "position": 1},
                {"step_id": str(itinerary_state.steps[2].id), "day_index": 2, "position": 0},
            ]
        },
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Itinerary is no longer editable."


@pytest.mark.asyncio
async def test_completed_itinerary_blocks_step_updates(
    async_client,
    db_session: AsyncSession,
) -> None:
    future_start = datetime.now(CHILE_TZ).date() + timedelta(days=1)
    future_end = future_start + timedelta(days=1)
    user, itinerary = await _create_itinerary_fixture(
        db_session,
        start_date=future_start,
        end_date=future_end,
        status="completed",
    )

    repository = ItineraryRepository()
    itinerary_state = await repository.get_itinerary_by_id(db_session, itinerary.id, user.id)
    assert itinerary_state is not None
    assert itinerary_state.is_past is False
    assert itinerary_state.is_editable is False

    headers = {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}
    response = await async_client.patch(
        f"/api/v1/itineraries/{itinerary.id}/steps/{itinerary_state.steps[0].id}",
        json={"ai_context": {"note": "updated"}},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Itinerary is no longer editable."


@pytest.mark.asyncio
async def test_past_itinerary_weather_is_not_applicable_without_provider_call(
    async_client,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    past_start = datetime.now(CHILE_TZ).date() - timedelta(days=3)
    past_end = datetime.now(CHILE_TZ).date() - timedelta(days=2)
    user, itinerary = await _create_itinerary_fixture(
        db_session,
        start_date=past_start,
        end_date=past_end,
    )

    calls = 0

    async def fake_get_daily_forecast(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Provider should not be called for past itineraries")

    monkeypatch.setattr(itineraries_endpoint.weather_service_module, "get_daily_forecast", fake_get_daily_forecast)

    headers = {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}
    response = await async_client.get(
        f"/api/v1/itineraries/{itinerary.id}/weather",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls == 0
    assert "itinerary_id" in payload
    assert payload["daily"] == []


@pytest.mark.asyncio
async def test_completed_itinerary_weather_is_not_applicable_without_provider_call(
    async_client,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future_start = datetime.now(CHILE_TZ).date() + timedelta(days=1)
    future_end = future_start + timedelta(days=1)
    user, itinerary = await _create_itinerary_fixture(
        db_session,
        start_date=future_start,
        end_date=future_end,
        status="completed",
    )

    calls = 0

    async def fake_get_daily_forecast(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Provider should not be called for completed itineraries")

    monkeypatch.setattr(itineraries_endpoint.weather_service_module, "get_daily_forecast", fake_get_daily_forecast)

    headers = {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}
    response = await async_client.get(
        f"/api/v1/itineraries/{itinerary.id}/weather",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls == 0
    assert "itinerary_id" in payload
    assert payload["daily"] == []


@pytest.mark.asyncio
async def test_future_itinerary_weather_out_of_range_skips_provider_call(
    async_client,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future_start = datetime.now(CHILE_TZ).date() + timedelta(days=10)
    future_end = future_start + timedelta(days=1)
    user, itinerary = await _create_itinerary_fixture(
        db_session,
        start_date=future_start,
        end_date=future_end,
    )

    calls = 0

    async def fake_get_daily_forecast(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("Provider should not be called for out-of-range itinerary dates")

    monkeypatch.setattr(itineraries_endpoint.weather_service_module, "get_daily_forecast", fake_get_daily_forecast)

    headers = {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}
    response = await async_client.get(
        f"/api/v1/itineraries/{itinerary.id}/weather",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls == 0
    assert "itinerary_id" in payload
    assert payload["daily"] == []


@pytest.mark.asyncio
async def test_future_itinerary_weather_available_calls_provider(
    async_client,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future_start = datetime.now(CHILE_TZ).date() + timedelta(days=1)
    future_end = future_start + timedelta(days=1)
    user, itinerary = await _create_itinerary_fixture(
        db_session,
        start_date=future_start,
        end_date=future_end,
    )

    calls = 0

    async def fake_get_daily_forecast(*args, **kwargs):
        nonlocal calls
        calls += 1
        target_date = kwargs["start_date"]
        return [
            WeatherDailyForecast(
                date=target_date,
                label="Lunes 01",
                description="Soleado",
                temperature_c=20,
                precipitation_probability=10,
            )
        ]

    monkeypatch.setattr(itineraries_endpoint.weather_service_module, "get_daily_forecast", fake_get_daily_forecast)

    headers = {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}
    response = await async_client.get(
        f"/api/v1/itineraries/{itinerary.id}/weather",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert calls >= 1
    assert "itinerary_id" in payload
    assert len(payload["daily"]) >= 1
    assert payload["daily"][0]["description"] == "Soleado"
