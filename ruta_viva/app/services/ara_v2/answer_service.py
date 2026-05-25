from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ara_session import AraSession
from app.repositories.poi_repository import POIRepository
from app.schemas.ara_comprehension import ComprehensionResult
from app.services.ara_v2.utils import get_gpt_mini_client

logger = logging.getLogger(__name__)

poi_repository = POIRepository()


class AnswerService:
    """Responde preguntas puntuales sobre POIs usando SOLO la descripcion del POI."""

    def __init__(self) -> None:
        self._client = get_gpt_mini_client()
        self._model = settings.openai_gpt_mini_model

    async def answer(
        self,
        db: AsyncSession,
        comprehension: ComprehensionResult,
        session: AraSession,
        current_user_message: str | None = None,
    ) -> dict[str, Any]:
        user_question = current_user_message or self._extract_question(comprehension, session)
        poi_name = self._extract_poi_name(comprehension, user_question)

        if not poi_name:
            return {
                "text": "No tengo informacion sobre ese lugar especifico en mi base de datos.",
                "evidence_level": "unknown",
            }

        pois = await poi_repository.search_by_name(db, poi_name, limit=1)
        if not pois:
            return {
                "text": f"No encontre informacion sobre {poi_name} en mi base de datos.",
                "evidence_level": "unknown",
            }

        poi = pois[0]

        visit_rules_text = json.dumps(poi.visit_rules) if poi.visit_rules else "No disponible"

        system_prompt = (
            f"Eres Ara. Responde esta pregunta usando SOLO la informacion proporcionada.\n"
            f"NO inventes datos. Si la informacion no esta en la descripcion, di 'No tengo ese dato confirmado'.\n\n"
            f"INFORMACION DEL LUGAR:\n"
            f"Nombre: {poi.name}\n"
            f"Descripcion: {poi.description or 'No disponible'}\n"
            f"Reglas de visita: {visit_rules_text}\n"
            f"Horarios: {poi.opening_hours_text or 'No disponible'}\n\n"
            f"PREGUNTA DEL USUARIO: {user_question}\n\n"
            f"Responde en 2-4 oraciones. Si no tienes el dato, se honesto."
        )

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                temperature=0,
                messages=[{"role": "system", "content": system_prompt}],
                timeout=5,
            )
            text = response.choices[0].message.content or "No tengo ese dato confirmado."
        except Exception:
            logger.warning("Answer service GPT call failed, returning raw description")
            text = poi.description or "No tengo informacion disponible."

        evidence_level = "confirmed" if poi.description and len(poi.description) > 50 else "unknown"

        return {
            "text": text,
            "evidence_level": evidence_level,
            "poi_id": str(poi.id),
        }

    def _extract_question(self, comprehension: ComprehensionResult, session: AraSession) -> str:
        """Extrae la pregunta del contexto."""
        messages = session.__dict__.get("messages") or []
        if messages:
            for msg in reversed(messages):
                if msg.role == "user":
                    return msg.content
        return "Que sabes de este lugar?"

    def _extract_poi_name(
        self, comprehension: ComprehensionResult, user_question: str
    ) -> str | None:
        """Busca entidad tipo 'poi' o usa heuristica simple."""
        pois = [e.valor for e in comprehension.entidades if e.tipo == "poi"]
        if pois:
            return pois[0]

        for pattern in (
            r"(?:qué|que)\s+es\s+(.+?)(?:\?|$)",
            r"(?:qué|que)\s+sabes\s+de\s+(.+?)(?:\?|$)",
            r"cu[eé]ntame\s+(?:sobre|de)\s+(.+?)(?:\?|$)",
            r"vale\s+la\s+pena\s+(.+?)(?:\?|$)",
        ):
            match = re.search(pattern, user_question.strip(), flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" .¿?¡!")

        words = user_question.split()
        for w in words:
            if w[0:1].isupper() and len(w) > 3:
                return w
        return None


_answer_service: AnswerService | None = None


def get_answer_service() -> AnswerService:
    global _answer_service
    if _answer_service is None:
        _answer_service = AnswerService()
    return _answer_service


def reset_answer_service() -> None:
    global _answer_service
    _answer_service = None
