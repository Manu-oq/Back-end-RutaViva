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

            parsed = json.loads(content)
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
            return fallback_comprehend(user_message)


_comprensor: Comprensor | None = None


def get_comprensor() -> Comprensor:
    global _comprensor
    if _comprensor is None:
        _comprensor = Comprensor()
    return _comprensor


def reset_comprensor() -> None:
    global _comprensor
    _comprensor = None
