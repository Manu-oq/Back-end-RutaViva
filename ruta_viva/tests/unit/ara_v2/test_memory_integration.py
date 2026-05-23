from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ara_session import AraSession
from app.models.conversation_memory import ConversationMemory
from app.models.tourist_profile import TouristProfile
from app.models.user import User
from app.schemas.ara_comprehension import ComprehensionResult, MemoryFact
from app.services.ara_v2.memory_service import MemoryService


class MockEmbeddingService:
    async def get_embedding(self, text: str) -> list[float]:
        return [0.1] * 1536


class FailingEmbeddingService:
    async def get_embedding(self, text: str) -> list[float]:
        raise RuntimeError("OpenAI is down")


@pytest.fixture
def memory_service() -> MemoryService:
    return MemoryService(MockEmbeddingService())


@pytest.fixture
def failing_memory_service() -> MemoryService:
    return MemoryService(FailingEmbeddingService())


async def _ensure_tourist_exists(db_session: AsyncSession, tourist_id) -> None:
    user = User(id=tourist_id, email=f"test-{tourist_id}@rutaviva.cl", password_hash="hash", is_active=True)
    db_session.add(user)
    await db_session.flush()
    profile = TouristProfile(user_id=tourist_id, full_name="Test Tourist", has_own_transport=False)
    db_session.add(profile)
    await db_session.flush()


class TestStoreFactFromComprehension:
    """Test que hechos del Comprensor se guardan en conversation_memory."""

    @pytest.mark.asyncio
    async def test_store_fact_from_comprehension(self, db_session: AsyncSession, memory_service: MemoryService):
        """ComprehensionResult con actualizaciones_memoria -> hechos guardados en DB."""
        tourist_id = uuid4()

        await _ensure_tourist_exists(db_session, tourist_id)

        facts = [
            MemoryFact(hecho="vegetariano", categoria="restriccion", confianza=0.9),
        ]

        for fact in facts:
            await memory_service.store_fact(
                db=db_session,
                tourist_id=tourist_id,
                session_id=None,
                hecho=fact.hecho,
                categoria=fact.categoria,
                confianza=fact.confianza,
            )

        stmt = select(ConversationMemory).where(
            ConversationMemory.tourist_id == tourist_id,
            ConversationMemory.hecho == "vegetariano",
        )
        result = await db_session.execute(stmt)
        saved = result.scalar_one_or_none()
        assert saved is not None
        assert saved.categoria == "restriccion"
        assert saved.confianza == 0.9


class TestRetrieveFactsAcrossTurns:
    """Test que hechos de turnos anteriores se recuperan en turnos posteriores."""

    @pytest.mark.asyncio
    async def test_retrieve_facts_across_turns(self, db_session: AsyncSession, memory_service: MemoryService):
        """Turno 1: guarda 'vegetariano'. Turno 2: recupera como relevante."""
        tourist_id = uuid4()

        await _ensure_tourist_exists(db_session, tourist_id)

        await memory_service.store_fact(
            db=db_session,
            tourist_id=tourist_id,
            session_id=None,
            hecho="dieta vegetariana",
            categoria="restriccion",
            confianza=0.9,
        )

        facts = await memory_service.retrieve_relevant_facts(
            db_session, tourist_id, "quiero comer algo sin carne", top_k=5
        )

        assert len(facts) >= 1
        assert any("vegetarian" in f["hecho"].lower() for f in facts)


class TestUserIsolation:
    """Test de aislamiento estricto entre usuarios."""

    @pytest.mark.asyncio
    async def test_isolation_user_a_vs_user_b(self, db_session: AsyncSession, memory_service: MemoryService):
        """Usuario A: 'Soy vegetariano'. Usuario B: no ve hechos de A."""
        user_a = uuid4()
        user_b = uuid4()

        await _ensure_tourist_exists(db_session, user_a)
        await _ensure_tourist_exists(db_session, user_b)

        await memory_service.store_fact(
            db=db_session,
            tourist_id=user_a,
            session_id=None,
            hecho="dieta vegetariana",
            categoria="restriccion",
            confianza=0.9,
        )

        facts_b = await memory_service.retrieve_relevant_facts(
            db_session, user_b, "comida vegetariana", top_k=5
        )
        assert len(facts_b) == 0, f"User B should see 0 facts but got {len(facts_b)}"

        facts_a = await memory_service.retrieve_relevant_facts(
            db_session, user_a, "comida vegetariana", top_k=5
        )
        assert len(facts_a) >= 1


class TestUpdateProfileEmbedding:
    """Test que preferencias fuertes actualizan TouristProfile.interests_embedding."""

    @pytest.mark.asyncio
    async def test_update_profile_embedding(self, db_session: AsyncSession, memory_service: MemoryService):
        """Guardar preferencia con confianza 0.9 -> interests_embedding se actualiza."""
        user = User(email="profile-test@test.cl", password_hash="hash", is_active=True)
        db_session.add(user)
        await db_session.flush()

        profile = TouristProfile(user_id=user.id, full_name="Profile Test", has_own_transport=False)
        db_session.add(profile)
        await db_session.flush()

        assert profile.interests_embedding is None

        updated = await memory_service.update_tourist_profile_embedding(
            db_session, user.id, "prefiere senderismo facil", 0.9
        )

        assert updated is True
        await db_session.refresh(profile)
        assert profile.interests_embedding is not None
        assert len(profile.interests_embedding) == 1536

    @pytest.mark.asyncio
    async def test_no_update_profile_for_low_confidence(self, db_session: AsyncSession, memory_service: MemoryService):
        """Guardar hecho con confianza 0.5 -> interests_embedding NO cambia."""
        user = User(email="low-conf@test.cl", password_hash="hash", is_active=True)
        db_session.add(user)
        await db_session.flush()

        profile = TouristProfile(user_id=user.id, full_name="Low Conf", has_own_transport=False)
        db_session.add(profile)
        await db_session.flush()

        updated = await memory_service.update_tourist_profile_embedding(
            db_session, user.id, "algo con confianza baja", 0.5
        )

        assert updated is False
        await db_session.refresh(profile)
        assert profile.interests_embedding is None


class TestEmbeddingFailureDoesNotBlock:
    """Test que fallo de embedding no bloquea el flujo."""

    @pytest.mark.asyncio
    async def test_embedding_failure_does_not_block_store(self, db_session: AsyncSession, failing_memory_service: MemoryService):
        """Mockear embedding service para que falle -> store_fact raises."""
        tourist_id = uuid4()

        with pytest.raises(RuntimeError):
            await failing_memory_service.store_fact(
                db=db_session,
                tourist_id=tourist_id,
                session_id=None,
                hecho="test hecho",
                categoria="preferencia",
                confianza=0.8,
            )

    @pytest.mark.asyncio
    async def test_profile_update_failure_does_not_block(self, db_session: AsyncSession, failing_memory_service: MemoryService):
        """Mockear embedding para profile update -> retorna False sin crashear."""
        user = User(email="fail-test@test.cl", password_hash="hash", is_active=True)
        db_session.add(user)
        await db_session.flush()

        profile = TouristProfile(user_id=user.id, full_name="Fail Test", has_own_transport=False)
        db_session.add(profile)
        await db_session.flush()

        updated = await failing_memory_service.update_tourist_profile_embedding(
            db_session, user.id, "prefiere algo", 0.9
        )

        assert updated is False


class TestConversationProcessorIntegration:
    """Tests del ConversationProcessor con mocks."""

    @pytest.mark.asyncio
    async def test_processor_calls_memory_retrieve_before_comprehend(self, db_session: AsyncSession):
        """Verificar que processor recupera memoria ANTES de comprender."""
        from app.services.ara_v2.conversation_processor import ConversationProcessor

        processor = ConversationProcessor()

        user = User(email="proc-test@test.cl", password_hash="hash", is_active=True)
        db_session.add(user)
        await db_session.flush()

        profile = TouristProfile(user_id=user.id, full_name="Proc Test", has_own_transport=False)
        db_session.add(profile)
        await db_session.flush()

        session = AraSession(
            tourist_id=user.id,
            initial_query="Villarrica",
            status="clarifying",
        )
        session.set_coordinates(-39.28, -71.95)
        session.messages = []
        db_session.add(session)
        await db_session.flush()

        mock_comprehension = ComprehensionResult(
            intenciones=["search_pois"],
            intencion_principal="search_pois",
            confianza=0.8,
            entidades=[],
            herramientas_necesarias=["search_pois"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        with patch("app.services.ara_v2.conversation_processor.get_comprensor") as mock_get_comprensor, \
             patch("app.services.ara_v2.conversation_processor.get_memory_service") as mock_get_ms:
            mock_comprensor = MagicMock()
            mock_comprensor.comprehend = AsyncMock(return_value=mock_comprehension)
            mock_get_comprensor.return_value = mock_comprensor

            mock_ms = MagicMock()
            mock_ms.retrieve_relevant_facts = AsyncMock(return_value=[])
            mock_ms.store_fact = AsyncMock()
            mock_ms.update_tourist_profile_embedding = AsyncMock(return_value=False)
            mock_get_ms.return_value = mock_ms

            result = await processor.process_user_message(
                db_session, session, user, "Quiero ir a Villarrica"
            )

            assert result.intencion_principal == "search_pois"
            mock_comprensor.comprehend.assert_called_once()
            call_kwargs = mock_comprensor.comprehend.call_args[1]
            assert "relevant_facts" in call_kwargs
