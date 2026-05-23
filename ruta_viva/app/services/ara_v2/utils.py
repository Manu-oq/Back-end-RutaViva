from __future__ import annotations

from openai import AsyncOpenAI

from app.core.config import settings

_gpt_mini_client: AsyncOpenAI | None = None


def get_gpt_mini_client() -> AsyncOpenAI:
    """Devuelve un cliente AsyncOpenAI configurado para GPT-4o-mini.
    
    Reutiliza settings.openai_api_key existente.
    Raises ValueError si no hay API key configurada.
    """
    global _gpt_mini_client
    if _gpt_mini_client is None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for GPT-4o-mini.")
        _gpt_mini_client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.gpt_mini_timeout_seconds,
        )
    return _gpt_mini_client


def reset_gpt_mini_client() -> None:
    """Resetea el singleton. Útil para tests."""
    global _gpt_mini_client
    _gpt_mini_client = None
