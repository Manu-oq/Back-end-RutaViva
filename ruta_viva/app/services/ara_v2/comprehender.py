from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.ara_comprehension import ComprehensionResult
from app.services.ara_v2.comprehension_fallback import fallback_comprehend
from app.services.ara_v2.prompt_manager import build_comprehension_prompt
from app.services.ara_v2.utils import get_gpt_mini_client

logger = logging.getLogger(__name__)

_VALID_ENTITY_TYPES = {
    "destino",
    "poi",
    "fecha",
    "categoria",
    "restriccion",
    "preferencia",
    "transporte",
    "horario",
    "presupuesto",
}
_VALID_MEMORY_CATEGORIES = {
    "restriccion",
    "preferencia",
    "destino",
    "entidad",
    "horario",
    "transporte",
    "presupuesto",
    "alojamiento",
}
_VALID_QUICK_REPLY_TYPES = {"refinement", "selection", "action", "navigation", "generate"}
_VALID_TONES = {"entusiasta", "neutro", "informativo", "empatico"}


class Comprensor:
    """GPT-4o-mini wrapper con JSON schema estricto y fallback a reglas simples."""

    def __init__(self) -> None:
        self._client = get_gpt_mini_client()
        self._model = settings.openai_gpt_mini_model

    async def comprehend(
        self,
        user_message: str,
        session_messages: list[dict[str, Any]] | None = None,
        relevant_facts: list[dict[str, Any]] | None = None,
        trip_draft: dict[str, Any] | None = None,
        candidate_pois_count: int = 0,
    ) -> ComprehensionResult:
        """Analiza el mensaje del usuario y devuelve un ComprehensionResult estructurado."""
        trip_draft = trip_draft or {}
        session_context: dict[str, Any] = {
            "initial_query": trip_draft.get("initial_query", ""),
            "turn_count": len(session_messages) if session_messages else 0,
            "current_day_focus": trip_draft.get("day_focus"),
            "lodging": trip_draft.get("lodging"),
            "start_date": trip_draft.get("start_date"),
            "end_date": trip_draft.get("end_date"),
            "relevant_facts": relevant_facts or [],
            "candidate_pois": [{"id": str(i)} for i in range(candidate_pois_count)] if candidate_pois_count > 0 else [],
        }

        system_prompt = build_comprehension_prompt(session_context)

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0,
                response_format={"type": "json_object"},
                timeout=settings.gpt_mini_timeout_seconds,
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from GPT-4o-mini")

            parsed = normalize_comprehension_payload(json.loads(content))
            result = ComprehensionResult.model_validate(parsed)
            logger.info(
                "Comprehension OK: intent=%s confidence=%.2f tools=%s",
                result.intencion_principal,
                result.confianza,
                result.herramientas_necesarias,
            )
            return result

        except (TimeoutError, json.JSONDecodeError, ValidationError, ValueError, Exception) as exc:
            logger.warning("GPT-4o-mini failed, using fallback: %s", exc)
            return fallback_comprehend(
                user_message,
                has_dates=bool(trip_draft.get("start_date") and trip_draft.get("end_date")),
                has_destination=bool(trip_draft.get("has_destination") or trip_draft.get("destination")),
            )


_comprensor: Comprensor | None = None


def get_comprensor() -> Comprensor:
    global _comprensor
    if _comprensor is None:
        _comprensor = Comprensor()
    return _comprensor


def reset_comprensor() -> None:
    global _comprensor
    _comprensor = None


def _normalize_enum(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_comprehension_payload(payload: Any) -> Any:
    """Normaliza pequeñas variaciones del LLM sin caer a fallback completo."""
    if not isinstance(payload, dict):
        return payload

    normalized = dict(payload)

    entities = []
    for raw_entity in normalized.get("entidades") or []:
        if not isinstance(raw_entity, dict):
            continue
        entity = dict(raw_entity)
        entity_type = _normalize_enum(entity.get("tipo"))
        if entity_type not in _VALID_ENTITY_TYPES:
            logger.warning("Dropping invalid comprehension entity type=%s", entity.get("tipo"))
            continue
        entity["tipo"] = entity_type
        entities.append(entity)
    normalized["entidades"] = entities

    memory_updates = []
    for raw_fact in normalized.get("actualizaciones_memoria") or []:
        if not isinstance(raw_fact, dict):
            continue
        fact = dict(raw_fact)
        category = _normalize_enum(fact.get("categoria"))
        if category not in _VALID_MEMORY_CATEGORIES:
            logger.warning("Dropping invalid memory category=%s", fact.get("categoria"))
            continue
        fact["categoria"] = category
        memory_updates.append(fact)
    normalized["actualizaciones_memoria"] = memory_updates

    quick_replies = normalized.get("sugerir_quick_replies")
    if isinstance(quick_replies, list):
        normalized_quick_replies = []
        for raw_reply in quick_replies:
            if not isinstance(raw_reply, dict):
                continue
            reply = dict(raw_reply)
            reply_type = _normalize_enum(reply.get("type") or "refinement")
            reply["type"] = reply_type if reply_type in _VALID_QUICK_REPLY_TYPES else "refinement"
            normalized_quick_replies.append(reply)
        normalized["sugerir_quick_replies"] = normalized_quick_replies

    tone = _normalize_enum(normalized.get("tono") or "neutro")
    normalized["tono"] = tone if tone in _VALID_TONES else "neutro"

    return normalized
