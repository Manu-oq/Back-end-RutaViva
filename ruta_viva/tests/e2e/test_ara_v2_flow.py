from __future__ import annotations

from datetime import date

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.ara_message import AraMessage
from app.models.ara_session import AraSession
from app.models.tourist_profile import TouristProfile
from app.models.user import User
from app.repositories.ara_repository import AraRepository
from app.schemas.ara import AraMessageCreate, AraMessageResponse, AraSessionCreate, AraSessionResponse
from app.schemas.ara_comprehension import ComprehensionResult, ExtractedEntity, ToolExecutionResult
from app.schemas.itinerary import ItineraryResponse, ItineraryStepResponse
from app.services.ara_conversation_orchestrator import create_session_v2, handle_message_v2
from app.services.ara_v2.conversation_processor import ConversationProcessor

ara_repository = AraRepository()


def _make_user():
    return User(email="e2e@test.cl", password_hash="hash", is_active=True)


def _make_tourist_profile(user_id):
    return TouristProfile(user_id=user_id, full_name="E2E Test", has_own_transport=False)


def _make_session(tourist_id=None):
    session = AraSession(
        tourist_id=tourist_id or uuid4(),
        initial_query="Villarrica",
        status="clarifying",
    )
    session.set_coordinates(-39.28, -71.95)
    session.messages = []
    session.candidate_poi_ids = []
    return session


def _sessionmaker_from(session: AsyncSession):
    return async_sessionmaker(
        bind=session.bind,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )


async def _fake_process_user_message(
    db: AsyncSession,
    session: AraSession,
    current_user: User,
    user_message: str,
) -> AraSessionResponse:
    user_msg = AraMessage(session_id=session.id, role="user", content=user_message)
    assistant_msg = AraMessage(session_id=session.id, role="assistant", content="Te ayudo con esa ruta.")
    db.add_all([user_msg, assistant_msg])
    await db.flush()
    return AraSessionResponse(
        session_id=session.id,
        status=session.status,
        user_message=AraMessageResponse(
            id=user_msg.id,
            session_id=session.id,
            role="user",
            content=user_msg.content,
        ),
        assistant_message=AraMessageResponse(
            id=assistant_msg.id,
            session_id=session.id,
            role="assistant",
            content=assistant_msg.content,
        ),
    )


class TestCreateSessionAndSendMessages:
    """Test flujo basico: crear sesion + enviar mensajes."""

    @pytest.mark.asyncio
    async def test_create_session_v2_persists_session_for_next_request(self, db_session: AsyncSession):
        """POST /sessions debe dejar la sesión visible para el siguiente request."""
        user = _make_user()
        user.email = f"persist-session-{uuid4()}@test.cl"
        db_session.add(user)
        await db_session.flush()

        profile = _make_tourist_profile(user.id)
        db_session.add(profile)
        await db_session.flush()

        fake_processor = MagicMock()
        fake_processor.process_user_message = AsyncMock(side_effect=_fake_process_user_message)

        with patch(
            "app.services.ara_conversation_orchestrator.get_conversation_processor",
            return_value=fake_processor,
        ):
            response = await create_session_v2(
                db_session,
                user,
                AraSessionCreate(
                    initial_message="Quiero armar una ruta por Villarrica",
                    lat=-39.28,
                    lon=-71.95,
                    radius=5000,
                ),
            )

        VerificationSession = _sessionmaker_from(db_session)
        async with VerificationSession() as verification_db:
            persisted = await ara_repository.get_session(verification_db, response.session_id, user.id)

        assert persisted is not None
        assert persisted.initial_query == "Quiero armar una ruta por Villarrica"
        assert response.assistant_message is not None

    @pytest.mark.asyncio
    async def test_create_session_v2_processes_initial_message_without_lazy_loading_messages(
        self,
        db_session: AsyncSession,
    ):
        """La primera respuesta no debe intentar lazy-load de session.messages."""
        user = _make_user()
        user.email = f"initial-message-{uuid4()}@test.cl"
        db_session.add(user)
        await db_session.flush()

        profile = _make_tourist_profile(user.id)
        db_session.add(profile)
        await db_session.flush()

        mock_comprehension = ComprehensionResult(
            intenciones=["general"],
            intencion_principal="general",
            confianza=0.8,
            entidades=[],
            herramientas_necesarias=[],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        mock_tool_result = ToolExecutionResult(
            status="respond",
            response_text="Te ayudo a planificar tu viaje por La Araucania.",
        )

        with patch("app.services.ara_v2.conversation_processor.get_memory_service") as mock_ms, \
             patch("app.services.ara_v2.conversation_processor.get_comprensor") as mock_comp, \
             patch("app.services.ara_v2.conversation_processor.get_tool_orchestrator") as mock_orch, \
             patch("app.services.ara_v2.conversation_processor.get_response_generator") as mock_gen:

            mock_ms.return_value.retrieve_relevant_facts = AsyncMock(return_value=[])
            mock_ms.return_value.store_fact = AsyncMock()
            mock_ms.return_value.update_tourist_profile_embedding = AsyncMock(return_value=False)
            mock_comp.return_value.comprehend = AsyncMock(return_value=mock_comprehension)
            mock_orch.return_value.execute = AsyncMock(return_value=mock_tool_result)
            mock_gen.return_value.generate_response = AsyncMock(return_value={
                "text": "Te ayudo a planificar tu viaje por La Araucania.",
                "quick_replies": [],
            })

            response = await create_session_v2(
                db_session,
                user,
                AraSessionCreate(
                    initial_message="Quiero conocer Villarrica",
                    lat=-39.28,
                    lon=-71.95,
                    radius=5000,
                ),
            )

        assert response.assistant_message is not None
        assert response.assistant_message.content == "Te ayudo a planificar tu viaje por La Araucania."

        VerificationSession = _sessionmaker_from(db_session)
        async with VerificationSession() as verification_db:
            result = await verification_db.execute(
                select(AraMessage)
                .where(AraMessage.session_id == response.session_id)
                .order_by(AraMessage.created_at.asc())
            )
            persisted_messages = list(result.scalars().all())

        assert [message.role for message in persisted_messages] == ["user", "assistant"]
        assert persisted_messages[0].content == "Quiero conocer Villarrica"

    @pytest.mark.asyncio
    async def test_create_session_v2_uses_ui_dates_and_filters_redundant_questions(
        self,
        db_session: AsyncSession,
    ):
        """Fechas seleccionadas en UI predominan y Ara no debe volver a pedirlas."""
        user = _make_user()
        user.email = f"ui-dates-{uuid4()}@test.cl"
        db_session.add(user)
        await db_session.flush()

        profile = _make_tourist_profile(user.id)
        db_session.add(profile)
        await db_session.flush()

        mock_comprehension = ComprehensionResult(
            intenciones=["search_pois"],
            intencion_principal="search_pois",
            confianza=0.8,
            entidades=[ExtractedEntity(tipo="destino", valor="Pucón", confianza=0.9)],
            herramientas_necesarias=["search_pois"],
            preguntas_pendientes=["¿Qué fechas tienes en mente?", "¿A qué destino quieres ir?"],
            actualizaciones_memoria=[],
        )
        mock_tool_result = ToolExecutionResult(status="respond", response_text="Ya tengo las fechas para Pucón.")

        with patch("app.services.ara_v2.conversation_processor.get_memory_service") as mock_ms, \
             patch("app.services.ara_v2.conversation_processor.get_comprensor") as mock_comp, \
             patch("app.services.ara_v2.conversation_processor.get_tool_orchestrator") as mock_orch, \
             patch("app.services.ara_v2.conversation_processor.get_response_generator") as mock_gen:

            mock_ms.return_value.retrieve_relevant_facts = AsyncMock(return_value=[])
            mock_ms.return_value.store_fact = AsyncMock()
            mock_ms.return_value.update_tourist_profile_embedding = AsyncMock(return_value=False)
            mock_comp.return_value.comprehend = AsyncMock(return_value=mock_comprehension)
            mock_orch.return_value.execute = AsyncMock(return_value=mock_tool_result)
            mock_gen.return_value.generate_response = AsyncMock(return_value={
                "text": "Ya tengo las fechas para Pucón.",
                "quick_replies": [],
            })

            response = await create_session_v2(
                db_session,
                user,
                AraSessionCreate(
                    initial_message="Hola Ara, quiero organizar un viaje de tres días a Pucón",
                    lat=-39.28,
                    lon=-71.95,
                    radius=5000,
                    start_date=date(2026, 5, 25),
                    end_date=date(2026, 5, 27),
                ),
            )

        assert response.start_date == date(2026, 5, 25)
        assert response.end_date == date(2026, 5, 27)

        comprehend_kwargs = mock_comp.return_value.comprehend.call_args.kwargs
        assert comprehend_kwargs["trip_draft"]["start_date"] == "2026-05-25"
        assert comprehend_kwargs["trip_draft"]["end_date"] == "2026-05-27"

        orchestrator_comprehension = mock_orch.return_value.execute.call_args.kwargs["comprehension"]
        assert orchestrator_comprehension.preguntas_pendientes == []

    @pytest.mark.asyncio
    async def test_handle_message_v2_persists_messages_for_next_request(self, db_session: AsyncSession):
        """POST /messages debe commitear mensajes del usuario y asistente."""
        user = _make_user()
        user.email = f"persist-messages-{uuid4()}@test.cl"
        db_session.add(user)
        await db_session.flush()

        profile = _make_tourist_profile(user.id)
        db_session.add(profile)
        await db_session.flush()

        fake_processor = MagicMock()
        fake_processor.process_user_message = AsyncMock(side_effect=_fake_process_user_message)

        with patch(
            "app.services.ara_conversation_orchestrator.get_conversation_processor",
            return_value=fake_processor,
        ):
            session_response = await create_session_v2(
                db_session,
                user,
                AraSessionCreate(initial_message="Quiero viajar a Pucón", lat=-39.28, lon=-71.95),
            )

        fake_processor = MagicMock()
        fake_processor.process_user_message = AsyncMock(side_effect=_fake_process_user_message)

        with patch(
            "app.services.ara_conversation_orchestrator.get_conversation_processor",
            return_value=fake_processor,
        ):
            await handle_message_v2(
                db_session,
                user,
                session_response.session_id,
                AraMessageCreate(message="Me gustan las termas"),
            )

        VerificationSession = _sessionmaker_from(db_session)
        async with VerificationSession() as verification_db:
            result = await verification_db.execute(
                select(AraMessage)
                .where(AraMessage.session_id == session_response.session_id)
                .order_by(AraMessage.created_at.asc())
            )
            persisted_messages = list(result.scalars().all())

        assert [message.role for message in persisted_messages] == ["user", "assistant", "user", "assistant"]
        assert persisted_messages[2].content == "Me gustan las termas"
        assert persisted_messages[3].content == "Te ayudo con esa ruta."

    @pytest.mark.asyncio
    async def test_create_session_and_send_messages(self, db_session: AsyncSession):
        """POST /sessions -> POST /messages (3 veces) -> AraSessionResponse."""
        processor = ConversationProcessor()
        user = _make_user()
        db_session.add(user)
        await db_session.flush()

        profile = _make_tourist_profile(user.id)
        db_session.add(profile)
        await db_session.flush()

        session = _make_session(tourist_id=user.id)
        db_session.add(session)
        await db_session.flush()

        mock_comprehension = ComprehensionResult(
            intenciones=["search_pois"],
            intencion_principal="search_pois",
            confianza=0.8,
            entidades=[ExtractedEntity(tipo="destino", valor="Villarrica", confianza=0.9)],
            herramientas_necesarias=["search_pois"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        mock_tool_result = ToolExecutionResult(
            status="search",
            candidate_pois=[{"id": str(uuid4()), "name": "Volcan Villarrica"}],
        )

        with patch("app.services.ara_v2.conversation_processor.get_memory_service") as mock_ms, \
             patch("app.services.ara_v2.conversation_processor.get_comprensor") as mock_comp, \
             patch("app.services.ara_v2.conversation_processor.get_tool_orchestrator") as mock_orch, \
             patch("app.services.ara_v2.conversation_processor.get_response_generator") as mock_gen:

            mock_ms.return_value.retrieve_relevant_facts = AsyncMock(return_value=[])
            mock_ms.return_value.store_fact = AsyncMock()
            mock_ms.return_value.update_tourist_profile_embedding = AsyncMock(return_value=False)
            mock_comp.return_value.comprehend = AsyncMock(return_value=mock_comprehension)
            mock_orch.return_value.execute = AsyncMock(return_value=mock_tool_result)
            mock_gen.return_value.generate_response = AsyncMock(return_value={
                "text": "Encontre opciones en Villarrica.",
                "quick_replies": [],
            })

            for msg in ["Quiero ir a Villarrica", "Busco algo tranquilo", "Mostrame opciones"]:
                result = await processor.process_user_message(
                    db_session, session, user, msg
                )
                assert isinstance(result, AraSessionResponse)
                assert result.session_id == session.id
                assert result.assistant_message is not None
                assert result.assistant_message.content is not None


class TestGenerateItineraryFromSession:
    """Test flujo de generacion de itinerario."""

    @pytest.mark.asyncio
    async def test_generate_itinerary_from_session(self, db_session: AsyncSession):
        """POST /messages ("Hacelo todo") -> itinerario generado."""
        processor = ConversationProcessor()
        user = _make_user()
        db_session.add(user)
        await db_session.flush()

        profile = _make_tourist_profile(user.id)
        db_session.add(profile)
        await db_session.flush()

        session = _make_session(tourist_id=user.id)
        session.messages = []
        db_session.add(session)
        await db_session.flush()

        mock_comprehension = ComprehensionResult(
            intenciones=["build_itinerary"],
            intencion_principal="build_itinerary",
            confianza=0.9,
            entidades=[],
            herramientas_necesarias=["build_itinerary"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        mock_itinerary = ItineraryResponse(
            id=uuid4(),
            tourist_id=user.id,
            title="Test Itinerary",
            start_date=date.today(),
            end_date=date.today(),
            status="draft",
            steps=[],
        )

        mock_tool_result = ToolExecutionResult(
            status="generate",
            itinerary=mock_itinerary,
            candidate_pois=[{"id": str(uuid4()), "name": "POI"}],
        )

        with patch("app.services.ara_v2.conversation_processor.get_memory_service") as mock_ms, \
             patch("app.services.ara_v2.conversation_processor.get_comprensor") as mock_comp, \
             patch("app.services.ara_v2.conversation_processor.get_tool_orchestrator") as mock_orch, \
             patch("app.services.ara_v2.conversation_processor.get_response_generator") as mock_gen:

            mock_ms.return_value.retrieve_relevant_facts = AsyncMock(return_value=[])
            mock_ms.return_value.store_fact = AsyncMock()
            mock_ms.return_value.update_tourist_profile_embedding = AsyncMock(return_value=False)
            mock_comp.return_value.comprehend = AsyncMock(return_value=mock_comprehension)
            mock_orch.return_value.execute = AsyncMock(return_value=mock_tool_result)
            mock_gen.return_value.generate_response = AsyncMock(return_value={
                "text": "Tu itinerario esta listo.",
                "quick_replies": [],
            })

            result = await processor.process_user_message(
                db_session, session, user, "Hacelo todo"
            )

            assert isinstance(result, AraSessionResponse)
            assert result.status == session.status


class TestSearchPoisFlow:
    """Test flujo de busqueda de POIs."""

    @pytest.mark.asyncio
    async def test_search_pois_flow(self, db_session: AsyncSession):
        """POST /messages ("Quiero ir a Villarrica") -> candidate_pois no vacio."""
        processor = ConversationProcessor()
        user = _make_user()
        db_session.add(user)
        await db_session.flush()

        profile = _make_tourist_profile(user.id)
        db_session.add(profile)
        await db_session.flush()

        session = _make_session(tourist_id=user.id)
        db_session.add(session)
        await db_session.flush()

        mock_comprehension = ComprehensionResult(
            intenciones=["search_pois"],
            intencion_principal="search_pois",
            confianza=0.8,
            entidades=[ExtractedEntity(tipo="destino", valor="Villarrica", confianza=0.9)],
            herramientas_necesarias=["search_pois"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        mock_tool_result = ToolExecutionResult(
            status="search",
            candidate_pois=[
                {"id": str(uuid4()), "name": "Volcan Villarrica"},
                {"id": str(uuid4()), "name": "Termas"},
            ],
        )

        with patch("app.services.ara_v2.conversation_processor.get_memory_service") as mock_ms, \
             patch("app.services.ara_v2.conversation_processor.get_comprensor") as mock_comp, \
             patch("app.services.ara_v2.conversation_processor.get_tool_orchestrator") as mock_orch, \
             patch("app.services.ara_v2.conversation_processor.get_response_generator") as mock_gen:

            mock_ms.return_value.retrieve_relevant_facts = AsyncMock(return_value=[])
            mock_ms.return_value.store_fact = AsyncMock()
            mock_ms.return_value.update_tourist_profile_embedding = AsyncMock(return_value=False)
            mock_comp.return_value.comprehend = AsyncMock(return_value=mock_comprehension)
            mock_orch.return_value.execute = AsyncMock(return_value=mock_tool_result)
            mock_gen.return_value.generate_response = AsyncMock(return_value={
                "text": "Encontre 2 opciones en Villarrica.",
                "quick_replies": [],
            })

            result = await processor.process_user_message(
                db_session, session, user, "Quiero ir a Villarrica"
            )

            assert result.candidate_pois is not None


class TestAnswerQuestionFlow:
    """Test flujo de respuesta a preguntas."""

    @pytest.mark.asyncio
    async def test_answer_question_flow(self, db_session: AsyncSession):
        """POST /messages ("Es dificil el Salto del Lago?") -> response_text no vacio."""
        processor = ConversationProcessor()
        user = _make_user()
        db_session.add(user)
        await db_session.flush()

        profile = _make_tourist_profile(user.id)
        db_session.add(profile)
        await db_session.flush()

        session = _make_session(tourist_id=user.id)
        db_session.add(session)
        await db_session.flush()

        mock_comprehension = ComprehensionResult(
            intenciones=["answer_question"],
            intencion_principal="answer_question",
            confianza=0.8,
            entidades=[ExtractedEntity(tipo="poi", valor="Salto del Lago", confianza=0.9)],
            herramientas_necesarias=["answer_question"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        mock_tool_result = ToolExecutionResult(
            status="respond",
            response_text="El Salto del Lago tiene dificultad media.",
        )

        with patch("app.services.ara_v2.conversation_processor.get_memory_service") as mock_ms, \
             patch("app.services.ara_v2.conversation_processor.get_comprensor") as mock_comp, \
             patch("app.services.ara_v2.conversation_processor.get_tool_orchestrator") as mock_orch, \
             patch("app.services.ara_v2.conversation_processor.get_response_generator") as mock_gen:

            mock_ms.return_value.retrieve_relevant_facts = AsyncMock(return_value=[])
            mock_ms.return_value.store_fact = AsyncMock()
            mock_ms.return_value.update_tourist_profile_embedding = AsyncMock(return_value=False)
            mock_comp.return_value.comprehend = AsyncMock(return_value=mock_comprehension)
            mock_orch.return_value.execute = AsyncMock(return_value=mock_tool_result)
            mock_gen.return_value.generate_response = AsyncMock(return_value={
                "text": "El Salto del Lago tiene dificultad media.",
                "quick_replies": [],
            })

            result = await processor.process_user_message(
                db_session, session, user, "Es dificil el Salto del Lago?"
            )

            assert result.assistant_message is not None
            assert "dificultad" in result.assistant_message.content.lower() or "salto" in result.assistant_message.content.lower()


class TestMemoryPersistsAcrossTurns:
    """Test que la memoria persiste entre turnos."""

    @pytest.mark.asyncio
    async def test_memory_persists_across_turns(self, db_session: AsyncSession):
        """Turno 1: 'Soy vegetariano' -> Turno 2: hecho recuperado."""
        user = _make_user()
        db_session.add(user)
        await db_session.flush()

        profile = _make_tourist_profile(user.id)
        db_session.add(profile)
        await db_session.flush()

        tourist_id = user.id

        with patch("app.services.ara_v2.memory_service.OpenAIEmbeddingService") as mock_embedding:
            mock_embed = AsyncMock(return_value=[0.1] * 1536)
            mock_embedding.return_value.get_embedding = mock_embed

            from app.services.ara_v2.memory_service import MemoryService

            ms = MemoryService(mock_embedding.return_value)

            await ms.store_fact(
                db=db_session,
                tourist_id=tourist_id,
                session_id=None,
                hecho="dieta vegetariana",
                categoria="restriccion",
                confianza=0.9,
            )

            facts = await ms.retrieve_relevant_facts(
                db_session, tourist_id, "quiero comer algo sin carne", top_k=5
            )

            assert len(facts) >= 1
            assert any("vegetarian" in f["hecho"].lower() for f in facts)


class TestQuickRepliesContextual:
    """Test que quick replies son contextuales."""

    @pytest.mark.asyncio
    async def test_quick_replies_contextual(self, db_session: AsyncSession):
        """POST /messages ("Hotel o cabana?") -> quick_replies con 2 items."""
        processor = ConversationProcessor()
        user = _make_user()
        db_session.add(user)
        await db_session.flush()

        profile = _make_tourist_profile(user.id)
        db_session.add(profile)
        await db_session.flush()

        session = _make_session(tourist_id=user.id)
        db_session.add(session)
        await db_session.flush()

        from app.schemas.ara import AraQuickReply
        from app.schemas.ara_comprehension import QuickReplySuggestion

        mock_comprehension = ComprehensionResult(
            intenciones=["general"],
            intencion_principal="general",
            confianza=0.5,
            entidades=[],
            herramientas_necesarias=[],
            preguntas_pendientes=["Hotel o cabana?"],
            actualizaciones_memoria=[],
            sugerir_quick_replies=[
                QuickReplySuggestion(label="Hotel", value="hotel", type="selection"),
                QuickReplySuggestion(label="Cabana", value="cabana", type="selection"),
            ],
        )

        mock_tool_result = ToolExecutionResult(
            status="clarify",
            response_text="Hotel o cabana?",
        )

        with patch("app.services.ara_v2.conversation_processor.get_memory_service") as mock_ms, \
             patch("app.services.ara_v2.conversation_processor.get_comprensor") as mock_comp, \
             patch("app.services.ara_v2.conversation_processor.get_tool_orchestrator") as mock_orch, \
             patch("app.services.ara_v2.conversation_processor.get_response_generator") as mock_gen:

            mock_ms.return_value.retrieve_relevant_facts = AsyncMock(return_value=[])
            mock_ms.return_value.store_fact = AsyncMock()
            mock_ms.return_value.update_tourist_profile_embedding = AsyncMock(return_value=False)
            mock_comp.return_value.comprehend = AsyncMock(return_value=mock_comprehension)
            mock_orch.return_value.execute = AsyncMock(return_value=mock_tool_result)
            mock_gen.return_value.generate_response = AsyncMock(return_value={
                "text": "Hotel o cabana?",
                "quick_replies": [
                    AraQuickReply(id="qr_0", label="Hotel", value="hotel", type="selection"),
                    AraQuickReply(id="qr_1", label="Cabana", value="cabana", type="selection"),
                ],
            })

            result = await processor.process_user_message(
                db_session, session, user, "Hotel o cabana?"
            )

            assert len(result.quick_replies) == 2
            assert result.quick_replies[0].label == "Hotel"
            assert result.quick_replies[1].label == "Cabana"


class TestReplacementFlow:
    """Test flujo de reemplazo de paso."""

    @pytest.mark.asyncio
    async def test_replacement_flow(self, db_session: AsyncSession):
        """POST /messages con metadata de reemplazo -> step reemplazado."""
        processor = ConversationProcessor()
        user = _make_user()
        db_session.add(user)
        await db_session.flush()

        profile = _make_tourist_profile(user.id)
        db_session.add(profile)
        await db_session.flush()

        session = _make_session(tourist_id=user.id)
        session.preferences_data = {
            "replacement_context": {
                "itinerary_id": str(uuid4()),
                "step_id": str(uuid4()),
            }
        }
        db_session.add(session)
        await db_session.flush()

        mock_comprehension = ComprehensionResult(
            intenciones=["suggest_replacement"],
            intencion_principal="suggest_replacement",
            confianza=0.8,
            entidades=[],
            herramientas_necesarias=["suggest_replacement"],
            preguntas_pendientes=[],
            actualizaciones_memoria=[],
        )

        mock_tool_result = ToolExecutionResult(
            status="replace",
            candidate_pois=[
                {"id": str(uuid4()), "name": "Alternativa 1"},
                {"id": str(uuid4()), "name": "Alternativa 2"},
            ],
        )

        with patch("app.services.ara_v2.conversation_processor.get_memory_service") as mock_ms, \
             patch("app.services.ara_v2.conversation_processor.get_comprensor") as mock_comp, \
             patch("app.services.ara_v2.conversation_processor.get_tool_orchestrator") as mock_orch, \
             patch("app.services.ara_v2.conversation_processor.get_response_generator") as mock_gen:

            mock_ms.return_value.retrieve_relevant_facts = AsyncMock(return_value=[])
            mock_ms.return_value.store_fact = AsyncMock()
            mock_ms.return_value.update_tourist_profile_embedding = AsyncMock(return_value=False)
            mock_comp.return_value.comprehend = AsyncMock(return_value=mock_comprehension)
            mock_orch.return_value.execute = AsyncMock(return_value=mock_tool_result)
            mock_gen.return_value.generate_response = AsyncMock(return_value={
                "text": "Aca tenes opciones para reemplazar.",
                "quick_replies": [],
            })

            result = await processor.process_user_message(
                db_session, session, user, "Cambia este paso"
            )

            assert isinstance(result, AraSessionResponse)


class TestStreamingGeneration:
    """Test que el endpoint de streaming existe y tiene la estructura correcta."""

    def test_streaming_endpoint_structure(self):
        """Verificar que el endpoint SSE esta definido."""
        from app.api.v1.endpoints.ara import router
        routes = [r.path for r in router.routes]
        assert any("stream" in r for r in routes), "SSE streaming endpoint should exist"
