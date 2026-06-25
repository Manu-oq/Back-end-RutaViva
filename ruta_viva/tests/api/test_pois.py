from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.entrepreneur_profile import EntrepreneurProfile
from app.models.poi import POI
from app.models.tourist_profile import TouristProfile
from app.models.user import User


async def _create_user(db_session: AsyncSession, email: str) -> User:
    user = User(email=email, password_hash="hashed-password", is_active=True)
    db_session.add(user)
    await db_session.flush()
    return user


async def _create_tourist(db_session: AsyncSession, email: str) -> User:
    user = await _create_user(db_session, email)
    db_session.add(TouristProfile(user_id=user.id, full_name="Test Tourist", has_own_transport=False))
    await db_session.flush()
    return user


async def _create_entrepreneur(db_session: AsyncSession, email: str, verification: str = "unverified") -> User:
    user = await _create_user(db_session, email)
    db_session.add(EntrepreneurProfile(
        user_id=user.id,
        verification_status=verification,
        admin_data={"display_name": f"Emp {email.split('@')[0]}"},
    ))
    await db_session.flush()
    return user


def _headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(subject=str(user.id))}"}


def _jitter() -> tuple[float, float]:
    lat = -39.28 + random.uniform(-0.02, 0.02)
    lon = -72.22 + random.uniform(-0.02, 0.02)
    return lat, lon


def _make_create_payload(name: str = "Café Test", desc: str = "Un lindo café en la plaza principal", image: str = "http://img.com/1.jpg") -> dict:
    lat, lon = _jitter()
    return {
        "name": name,
        "description": desc,
        "access_type": "public",
        "latitude": lat,
        "longitude": lon,
        "image_url": image,
        "category_ids": [],
    }


def _make_tourist_payload(name: str = "Mirador Test", desc: str = "Un mirador con vista espectacular", image: str | None = None) -> dict:
    lat, lon = _jitter()
    payload: dict = {
        "name": name,
        "description": desc,
        "access_type": "public",
        "latitude": lat,
        "longitude": lon,
        "category_ids": [],
    }
    if image:
        payload["image_url"] = image
    return payload


class TestCreatePoiTourist:
    @pytest.mark.asyncio
    async def test_creates_poi_with_null_entrepreneur_id(self, async_client, db_session: AsyncSession):
        tourist = await _create_tourist(db_session, "tourist-a@test.com")
        payload = _make_tourist_payload()

        response = await async_client.post("/api/v1/pois/tourist/", json=payload, headers=_headers(tourist))
        assert response.status_code == 201

        data = response.json()
        assert data["entrepreneur_id"] is None
        assert data["created_by_user_id"] == str(tourist.id)
        assert data["verification_status"] == "pending"
        assert data["name"] == "Mirador Test"

    @pytest.mark.asyncio
    async def test_tourist_can_omit_image(self, async_client, db_session: AsyncSession):
        tourist = await _create_tourist(db_session, "tourist-b@test.com")
        payload = _make_tourist_payload(image=None)

        response = await async_client.post("/api/v1/pois/tourist/", json=payload, headers=_headers(tourist))
        assert response.status_code == 201
        data = response.json()
        assert data["image_url"] is None


class TestCreatePoiEntrepreneur:
    @pytest.mark.asyncio
    async def test_creates_poi_with_entrepreneur_id(self, async_client, db_session: AsyncSession):
        ent = await _create_entrepreneur(db_session, "ent-a@test.com")
        payload = _make_create_payload()

        response = await async_client.post("/api/v1/pois/entrepreneur/", json=payload, headers=_headers(ent))
        assert response.status_code == 201

        data = response.json()
        assert data["entrepreneur_id"] == str(ent.id)
        assert data["verification_status"] == "pending"
        assert data["image_url"] == "http://img.com/1.jpg"

    @pytest.mark.asyncio
    async def test_requires_image_url(self, async_client, db_session: AsyncSession):
        ent = await _create_entrepreneur(db_session, "ent-b@test.com")
        payload = _make_create_payload()
        del payload["image_url"]

        response = await async_client.post("/api/v1/pois/entrepreneur/", json=payload, headers=_headers(ent))
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_backward_compat_slash_endpoint(self, async_client, db_session: AsyncSession):
        ent = await _create_entrepreneur(db_session, "ent-c@test.com")
        payload = _make_create_payload()

        response = await async_client.post("/api/v1/pois/", json=payload, headers=_headers(ent))
        assert response.status_code == 201
        data = response.json()
        assert data["entrepreneur_id"] == str(ent.id)


class TestEditPoiAuthorization:
    @pytest.mark.asyncio
    async def test_tourist_can_edit_own_poi_within_24h(self, async_client, db_session: AsyncSession):
        tourist = await _create_tourist(db_session, "tourist-edit@test.com")
        create_resp = await async_client.post(
            "/api/v1/pois/tourist/", json=_make_tourist_payload(), headers=_headers(tourist)
        )
        poi_id = create_resp.json()["id"]

        update_resp = await async_client.put(
            f"/api/v1/pois/{poi_id}",
            json={"name": "Mirador Editado"},
            headers=_headers(tourist),
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["name"] == "Mirador Editado"

    @pytest.mark.asyncio
    async def test_tourist_cannot_edit_poi_after_24h(self, async_client, db_session: AsyncSession):
        tourist = await _create_tourist(db_session, "tourist-late@test.com")
        create_resp = await async_client.post(
            "/api/v1/pois/tourist/", json=_make_tourist_payload(), headers=_headers(tourist)
        )
        poi_id = create_resp.json()["id"]

        poi = await db_session.get(POI, poi_id)
        poi.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
        await db_session.flush()

        update_resp = await async_client.put(
            f"/api/v1/pois/{poi_id}",
            json={"name": "Demasiado tarde"},
            headers=_headers(tourist),
        )
        assert update_resp.status_code == 403

    @pytest.mark.asyncio
    async def test_tourist_cannot_edit_other_tourist_poi(self, async_client, db_session: AsyncSession):
        tourist_a = await _create_tourist(db_session, "tourist-x@test.com")
        create_resp = await async_client.post(
            "/api/v1/pois/tourist/", json=_make_tourist_payload(), headers=_headers(tourist_a)
        )
        poi_id = create_resp.json()["id"]

        tourist_b = await _create_tourist(db_session, "tourist-y@test.com")
        update_resp = await async_client.put(
            f"/api/v1/pois/{poi_id}",
            json={"name": "No debería"},
            headers=_headers(tourist_b),
        )
        assert update_resp.status_code == 403

    @pytest.mark.asyncio
    async def test_tourist_can_delete_within_24h(self, async_client, db_session: AsyncSession):
        tourist = await _create_tourist(db_session, "tourist-del@test.com")
        create_resp = await async_client.post(
            "/api/v1/pois/tourist/", json=_make_tourist_payload(), headers=_headers(tourist)
        )
        poi_id = create_resp.json()["id"]

        delete_resp = await async_client.delete(f"/api/v1/pois/{poi_id}", headers=_headers(tourist))
        assert delete_resp.status_code == 204

    @pytest.mark.asyncio
    async def test_tourist_cannot_delete_poi_after_24h(self, async_client, db_session: AsyncSession):
        tourist = await _create_tourist(db_session, "tourist-late-del@test.com")
        create_resp = await async_client.post(
            "/api/v1/pois/tourist/", json=_make_tourist_payload(), headers=_headers(tourist)
        )
        poi_id = create_resp.json()["id"]

        poi = await db_session.get(POI, poi_id)
        poi.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
        await db_session.flush()

        delete_resp = await async_client.delete(f"/api/v1/pois/{poi_id}", headers=_headers(tourist))
        assert delete_resp.status_code == 403


class TestAppendPoiMediaAuthorization:
    @pytest.mark.asyncio
    async def test_tourist_blocked_after_24h(self, async_client, db_session: AsyncSession):
        tourist = await _create_tourist(db_session, "tourist-media@test.com")
        create_resp = await async_client.post(
            "/api/v1/pois/tourist/", json=_make_tourist_payload(), headers=_headers(tourist)
        )
        poi_id = create_resp.json()["id"]

        poi = await db_session.get(POI, poi_id)
        poi.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
        await db_session.flush()

        resp = await async_client.patch(
            f"/api/v1/pois/{poi_id}/media",
            json={"image_url": "http://img.com/new.jpg"},
            headers=_headers(tourist),
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_other_tourist_blocked_from_media(self, async_client, db_session: AsyncSession):
        tourist_a = await _create_tourist(db_session, "tourist-ma@test.com")
        create_resp = await async_client.post(
            "/api/v1/pois/tourist/", json=_make_tourist_payload(), headers=_headers(tourist_a)
        )
        poi_id = create_resp.json()["id"]

        tourist_b = await _create_tourist(db_session, "tourist-mb@test.com")
        resp = await async_client.patch(
            f"/api/v1/pois/{poi_id}/media",
            json={"image_url": "http://img.com/new.jpg"},
            headers=_headers(tourist_b),
        )
        assert resp.status_code == 403


class TestRecalculateConfidence:
    @pytest.mark.asyncio
    async def test_does_not_override_flagged(self, async_client, db_session: AsyncSession):
        ent = await _create_entrepreneur(db_session, "ent-flag@test.com")
        create_resp = await async_client.post(
            "/api/v1/pois/entrepreneur/", json=_make_create_payload(), headers=_headers(ent)
        )
        poi_id = create_resp.json()["id"]

        poi = await db_session.get(POI, poi_id)
        poi.verification_status = "flagged"
        poi.confidence_score = 0.9
        await db_session.flush()

        resp = await async_client.put(
            f"/api/v1/pois/{poi_id}",
            json={"description": "Un café actualizado con una excelente descripción detallada para testing."},
            headers=_headers(ent),
        )
        assert resp.status_code == 200
        assert resp.json()["verification_status"] == "flagged"

    @pytest.mark.asyncio
    async def test_recalculate_updates_score_not_status_for_flagged(self, async_client, db_session: AsyncSession):
        ent = await _create_entrepreneur(db_session, "ent-flag2@test.com")
        create_resp = await async_client.post(
            "/api/v1/pois/entrepreneur/", json=_make_create_payload(), headers=_headers(ent)
        )
        poi_id = create_resp.json()["id"]

        poi = await db_session.get(POI, poi_id)
        poi.verification_status = "flagged"
        poi.confidence_score = 0.3
        await db_session.flush()

        resp = await async_client.put(
            f"/api/v1/pois/{poi_id}",
            json={"description": "Una descripción nueva mucho más larga que antes para este excelente lugar turístico."},
            headers=_headers(ent),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["verification_status"] == "flagged"
        assert data["confidence_score"] > 0.3


class TestRateLimit:
    @pytest.mark.asyncio
    async def test_tourist_rate_limit_by_created_by_user_id(self, async_client, db_session: AsyncSession):
        tourist = await _create_tourist(db_session, "tourist-rl@test.com")
        headers = _headers(tourist)

        for i in range(5):
            resp = await async_client.post(
                "/api/v1/pois/tourist/",
                json=_make_tourist_payload(name=f"POI {i}", desc="x" * 20),
                headers=headers,
            )
            assert resp.status_code == 201, f"POI {i}: {resp.status_code} {resp.text}"

        resp = await async_client.post(
            "/api/v1/pois/tourist/",
            json=_make_tourist_payload(name="POI 6", desc="x" * 20),
            headers=headers,
        )
        assert resp.status_code == 429, f"Expected 429, got {resp.status_code}"

    @pytest.mark.asyncio
    async def test_entrepreneur_rate_limit_independent(self, async_client, db_session: AsyncSession):
        ent = await _create_entrepreneur(db_session, "ent-rl@test.com")
        tourist = await _create_tourist(db_session, "tourist-rl2@test.com")

        resp = await async_client.post(
            "/api/v1/pois/entrepreneur/", json=_make_create_payload(), headers=_headers(ent)
        )
        assert resp.status_code == 201

        resp = await async_client.post(
            "/api/v1/pois/tourist/",
            json=_make_tourist_payload(name="POI Turista", desc="x" * 20),
            headers=_headers(tourist),
        )
        assert resp.status_code == 201


class TestDescriptionValidation:
    @pytest.mark.asyncio
    async def test_20_chars_passes(self, async_client, db_session: AsyncSession):
        tourist = await _create_tourist(db_session, "tourist-desc@test.com")
        payload = _make_tourist_payload(desc="A" * 20)

        resp = await async_client.post("/api/v1/pois/tourist/", json=payload, headers=_headers(tourist))
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_19_chars_fails(self, async_client, db_session: AsyncSession):
        tourist = await _create_tourist(db_session, "tourist-fail-desc@test.com")
        payload = _make_tourist_payload(desc="A" * 19)

        resp = await async_client.post("/api/v1/pois/tourist/", json=payload, headers=_headers(tourist))
        assert resp.status_code == 422


class TestMyContributions:
    @pytest.mark.asyncio
    async def test_tourist_created_by_user_name(self, async_client, db_session: AsyncSession):
        tourist = await _create_tourist(db_session, "contrib-t@test.com")
        await async_client.post("/api/v1/pois/tourist/", json=_make_tourist_payload(name="POI Turista"), headers=_headers(tourist))

        resp = await async_client.get("/api/v1/pois/my-contributions/", headers=_headers(tourist))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["created_by_user_name"] == "Test Tourist"

    @pytest.mark.asyncio
    async def test_entrepreneur_poi_not_in_my_contributions(self, async_client, db_session: AsyncSession):
        ent = await _create_entrepreneur(db_session, "contrib-e@test.com")
        create_resp = await async_client.post("/api/v1/pois/entrepreneur/", json=_make_create_payload(name="POI Emp"), headers=_headers(ent))
        assert create_resp.status_code == 201

        resp = await async_client.get("/api/v1/pois/my-contributions/", headers=_headers(ent))
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_entrepreneur_in_mine_not_contributions(self, async_client, db_session: AsyncSession):
        ent = await _create_entrepreneur(db_session, "contrib-e2@test.com")
        create_resp = await async_client.post("/api/v1/pois/entrepreneur/", json=_make_create_payload(name="POI Emp Mine"), headers=_headers(ent))
        assert create_resp.status_code == 201

        contributions = await async_client.get("/api/v1/pois/my-contributions/", headers=_headers(ent))
        assert contributions.json() == []

        mine = await async_client.get("/api/v1/pois/mine", headers=_headers(ent))
        assert mine.status_code == 200
        assert len(mine.json()) == 1
        assert mine.json()[0]["name"] == "POI Emp Mine"

    @pytest.mark.asyncio
    async def test_dual_profile_no_overlap(self, async_client, db_session: AsyncSession):
        dual = await _create_user(db_session, "dual@test.com")
        db_session.add(TouristProfile(user_id=dual.id, full_name="Dual Tourist", has_own_transport=False))
        db_session.add(EntrepreneurProfile(
            user_id=dual.id,
            verification_status="unverified",
            admin_data={"display_name": "Dual Emp"},
        ))
        await db_session.flush()

        tourist_resp = await async_client.post(
            "/api/v1/pois/tourist/",
            json=_make_tourist_payload(name="POI Turista Dual"),
            headers=_headers(dual),
        )
        assert tourist_resp.status_code == 201

        ent_resp = await async_client.post(
            "/api/v1/pois/entrepreneur/",
            json=_make_create_payload(name="POI Emprendedor Dual"),
            headers=_headers(dual),
        )
        assert ent_resp.status_code == 201

        contributions = await async_client.get("/api/v1/pois/my-contributions/", headers=_headers(dual))
        assert contributions.status_code == 200
        contrib_data = contributions.json()
        assert len(contrib_data) == 1
        assert contrib_data[0]["name"] == "POI Turista Dual"

        mine = await async_client.get("/api/v1/pois/mine", headers=_headers(dual))
        assert mine.status_code == 200
        mine_data = mine.json()
        assert len(mine_data) == 1
        assert mine_data[0]["name"] == "POI Emprendedor Dual"

    @pytest.mark.asyncio
    async def test_creator_type_field(self, async_client, db_session: AsyncSession):
        dual = await _create_user(db_session, "ct@test.com")
        db_session.add(TouristProfile(user_id=dual.id, full_name="CT Tourist", has_own_transport=False))
        db_session.add(EntrepreneurProfile(
            user_id=dual.id,
            verification_status="unverified",
            admin_data={"display_name": "CT Emp"},
        ))
        await db_session.flush()

        tourist_resp = await async_client.post(
            "/api/v1/pois/tourist/",
            json=_make_tourist_payload(name="CT POI"),
            headers=_headers(dual),
        )
        assert tourist_resp.status_code == 201
        assert tourist_resp.json()["creator_type"] == "tourist"

        ent_resp = await async_client.post(
            "/api/v1/pois/entrepreneur/",
            json=_make_create_payload(name="CT POI Emp"),
            headers=_headers(dual),
        )
        assert ent_resp.status_code == 201
        assert ent_resp.json()["creator_type"] == "entrepreneur"

    @pytest.mark.asyncio
    async def test_cross_user_isolation(self, async_client, db_session: AsyncSession):
        tourist_a = await _create_tourist(db_session, "contrib-a@test.com")
        tourist_b = await _create_tourist(db_session, "contrib-b@test.com")

        await async_client.post("/api/v1/pois/tourist/", json=_make_tourist_payload(name="POI A"), headers=_headers(tourist_a))

        resp = await async_client.get("/api/v1/pois/my-contributions/", headers=_headers(tourist_b))
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_created_at_in_response(self, async_client, db_session: AsyncSession):
        tourist = await _create_tourist(db_session, "contrib-ts@test.com")
        await async_client.post("/api/v1/pois/tourist/", json=_make_tourist_payload(name="POI TS"), headers=_headers(tourist))

        resp = await async_client.get("/api/v1/pois/my-contributions/", headers=_headers(tourist))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["created_at"] is not None
