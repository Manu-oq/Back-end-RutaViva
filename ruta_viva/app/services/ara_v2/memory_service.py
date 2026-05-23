from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation_memory import ConversationMemory
from app.services.embedding_service import OpenAIEmbeddingService


class MemoryService:
    """CRUD de memoria semántica con aislamiento estricto por tourist_id."""

    def __init__(self, embedding_service: OpenAIEmbeddingService):
        self._embedding_service = embedding_service

    async def store_fact(
        self,
        db: AsyncSession,
        tourist_id: UUID,
        session_id: UUID | None,
        hecho: str,
        categoria: str,
        confianza: float = 0.5,
        contexto: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
    ) -> ConversationMemory:
        """Genera embedding del hecho y lo inserta en DB."""
        embedding = await self._embedding_service.get_embedding(hecho)
        fact = ConversationMemory(
            tourist_id=tourist_id,
            session_id=session_id,
            hecho=hecho,
            categoria=categoria,
            confianza=confianza,
            embedding=embedding,
            contexto=contexto,
            expires_at=expires_at,
        )
        db.add(fact)
        await db.flush()
        return fact

    async def retrieve_relevant_facts(
        self,
        db: AsyncSession,
        tourist_id: UUID,
        query_text: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Busca hechos relevantes por similitud semántica, filtrado por tourist_id."""
        query_embedding = await self._embedding_service.get_embedding(query_text)
        stmt = (
            select(
                ConversationMemory.id,
                ConversationMemory.hecho,
                ConversationMemory.categoria,
                ConversationMemory.confianza,
                ConversationMemory.contexto,
                ConversationMemory.created_at,
                ConversationMemory.embedding.cosine_distance(query_embedding).label("distance"),
            )
            .where(ConversationMemory.tourist_id == tourist_id)
            .order_by(ConversationMemory.embedding.cosine_distance(query_embedding))
            .limit(top_k)
        )
        result = await db.execute(stmt)
        rows = result.all()
        return [
            {
                "id": row.id,
                "hecho": row.hecho,
                "categoria": row.categoria,
                "confianza": row.confianza,
                "contexto": row.contexto,
                "created_at": row.created_at,
                "distance": row.distance,
            }
            for row in rows
        ]

    async def get_user_profile_summary(self, db: AsyncSession, tourist_id: UUID) -> dict[str, Any]:
        """Agrupa hechos por categoría y devuelve un dict estructurado."""
        stmt = (
            select(
                ConversationMemory.categoria,
                ConversationMemory.hecho,
                ConversationMemory.confianza,
            )
            .where(ConversationMemory.tourist_id == tourist_id)
            .order_by(ConversationMemory.confianza.desc())
        )
        result = await db.execute(stmt)
        rows = result.all()

        summary: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            summary.setdefault(row.categoria, []).append({
                "hecho": row.hecho,
                "confianza": row.confianza,
            })
        return summary


_memory_service: MemoryService | None = None


def get_memory_service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService(OpenAIEmbeddingService())
    return _memory_service
