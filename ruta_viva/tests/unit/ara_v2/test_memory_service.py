from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation_memory import ConversationMemory
from app.models.tourist_profile import TouristProfile
from app.models.user import User
from app.services.ara_v2.memory_service import MemoryService


class MockEmbeddingService:
    async def get_embedding(self, text: str) -> list[float]:
        return [0.1] * 1536


@pytest.fixture
def memory_service() -> MemoryService:
    return MemoryService(MockEmbeddingService())


@pytest.fixture
def tourist_id() -> str:
    return "00000000-0000-0000-0000-000000000001"


@pytest.mark.asyncio
async def _ensure_tourist_exists(db_session: AsyncSession, tourist_id: str) -> None:
    user = User(id=tourist_id, email=f"test-{tourist_id[:8]}@rutaviva.cl", password_hash="hash", is_active=True)
    db_session.add(user)
    await db_session.flush()
    profile = TouristProfile(user_id=tourist_id, full_name="Test Tourist", has_own_transport=False)
    db_session.add(profile)
    await db_session.flush()


class TestStoreFact:
    @pytest.mark.asyncio
    async def test_store_fact_creates_record(self, db_session: AsyncSession, memory_service: MemoryService, tourist_id: str):
        await _ensure_tourist_exists(db_session, tourist_id)
        fact = await memory_service.store_fact(
            db=db_session,
            tourist_id=tourist_id,
            session_id=None,
            hecho="prefiere baja dificultad",
            categoria="preferencia",
            confianza=0.8,
        )
        assert fact.id is not None
        assert fact.hecho == "prefiere baja dificultad"
        assert fact.categoria == "preferencia"
        assert fact.confianza == 0.8
        assert fact.embedding is not None
        assert len(fact.embedding) == 1536

    @pytest.mark.asyncio
    async def test_store_fact_with_context(self, db_session: AsyncSession, memory_service: MemoryService, tourist_id: str):
        await _ensure_tourist_exists(db_session, tourist_id)
        fact = await memory_service.store_fact(
            db=db_session,
            tourist_id=tourist_id,
            session_id=None,
            hecho="no come mariscos",
            categoria="restriccion",
            confianza=0.9,
            contexto={"source": "user_message", "turn": 3},
        )
        assert fact.contexto == {"source": "user_message", "turn": 3}


class TestRetrieveRelevantFacts:
    @pytest.mark.asyncio
    async def test_retrieve_returns_relevant_facts(self, db_session: AsyncSession, memory_service: MemoryService, tourist_id: str):
        await _ensure_tourist_exists(db_session, tourist_id)
        await memory_service.store_fact(db_session, tourist_id, None, "prefiere senderismo facil", "preferencia", 0.8)
        await memory_service.store_fact(db_session, tourist_id, None, "no come mariscos", "restriccion", 0.9)

        results = await memory_service.retrieve_relevant_facts(db_session, tourist_id, "caminata suave", top_k=2)

        assert len(results) == 2
        assert results[0]["hecho"] in ("prefiere senderismo facil", "no come mariscos")
        assert "distance" in results[0]
        assert 0 <= results[0]["distance"] <= 1

    @pytest.mark.asyncio
    async def test_retrieve_respects_top_k(self, db_session: AsyncSession, memory_service: MemoryService, tourist_id: str):
        await _ensure_tourist_exists(db_session, tourist_id)
        for i in range(5):
            await memory_service.store_fact(db_session, tourist_id, None, f"hecho numero {i}", "preferencia", 0.5)

        results = await memory_service.retrieve_relevant_facts(db_session, tourist_id, "algo", top_k=2)
        assert len(results) == 2


class TestUserIsolation:
    @pytest.mark.asyncio
    async def test_user_a_facts_not_visible_to_user_b(self, db_session: AsyncSession, memory_service: MemoryService):
        user_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        user_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

        await _ensure_tourist_exists(db_session, user_a)
        await _ensure_tourist_exists(db_session, user_b)

        await memory_service.store_fact(db_session, user_a, None, "prefiere hotel economico", "preferencia", 0.7)
        await memory_service.store_fact(db_session, user_a, None, "viaja con ninos", "restriccion", 0.9)

        results = await memory_service.retrieve_relevant_facts(db_session, user_b, "hotel", top_k=5)
        assert len(results) == 0, f"User B should see 0 facts but got {len(results)}"

        results_a = await memory_service.retrieve_relevant_facts(db_session, user_a, "hotel", top_k=5)
        assert len(results_a) >= 1
        assert any("hotel" in r["hecho"].lower() for r in results_a)


class TestUserProfileSummary:
    @pytest.mark.asyncio
    async def test_summary_groups_by_category(self, db_session: AsyncSession, memory_service: MemoryService, tourist_id: str):
        await _ensure_tourist_exists(db_session, tourist_id)
        await memory_service.store_fact(db_session, tourist_id, None, "prefiere baja dificultad", "preferencia", 0.8)
        await memory_service.store_fact(db_session, tourist_id, None, "no come mariscos", "restriccion", 0.9)
        await memory_service.store_fact(db_session, tourist_id, None, "le gusta el cafe", "preferencia", 0.6)

        summary = await memory_service.get_user_profile_summary(db_session, tourist_id)

        assert "preferencia" in summary
        assert "restriccion" in summary
        assert len(summary["preferencia"]) == 2
        assert len(summary["restriccion"]) == 1
        assert summary["preferencia"][0]["confianza"] >= summary["preferencia"][1]["confianza"]
