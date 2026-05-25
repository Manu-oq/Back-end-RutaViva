from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.core.config import settings
from app.core.llm_retry import with_retry
from app.schemas.itinerary import GeneratedItinerary
from app.schemas.poi import POIResponse
from app.services.ara_v2.prompt_manager import build_generation_prompt


class ItineraryGenerator:
    def __init__(self) -> None:
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required to generate itineraries.")

        self.client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
        self.model = "deepseek-chat"

    async def generate_itinerary(
        self,
        user_query: str,
        context_pois: list[POIResponse],
        weather_forecast: str,
        schedule_guidance: str,
        stream_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict:
        context_payload = [poi.model_dump(mode="json") for poi in context_pois]

        system_prompt = build_generation_prompt({
            "user_query": user_query,
            "context_pois": context_payload,
            "weather_forecast": weather_forecast,
            "schedule_guidance": schedule_guidance,
        })

        user_prompt = "Generá el itinerario en formato JSON."

        kwargs = dict(
            model=self.model,
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=settings.deepseek_timeout_seconds,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        if stream_callback is not None:
            kwargs["stream"] = True
            stream = await with_retry(
                lambda: self.client.chat.completions.create(**kwargs),
                max_retries=1,
                base_delay=2.0,
                operation_name="itinerary_generation",
            )
            content = ""
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    content += token
                    await stream_callback(token)
        else:
            response = await with_retry(
                lambda: self.client.chat.completions.create(**kwargs),
                max_retries=1,
                base_delay=2.0,
                operation_name="itinerary_generation",
            )
            content = response.choices[0].message.content

        if not content:
            raise RuntimeError("DeepSeek returned an empty itinerary response.")

        parsed = _normalize_itinerary_payload(json.loads(content), context_pois=context_pois)
        try:
            validated = GeneratedItinerary.model_validate(parsed)
        except ValidationError as exc:
            raise ValueError("Ara no pudo asociar algunos lugares generados con lugares reales de la base de datos.") from exc
        return validated.model_dump(mode="python")


_itinerary_generator: ItineraryGenerator | None = None


def _normalize_itinerary_payload(payload: dict, context_pois: list[POIResponse] | None = None) -> dict:
    """Acepta la forma legacy days[].steps y la transforma al schema actual."""
    if not isinstance(payload, dict):
        return payload

    current_steps = payload.get("steps")
    if current_steps:
        normalized = dict(payload)
        normalized["steps"] = _normalize_step_poi_ids(list(current_steps), context_pois)
        return normalized

    days = payload.get("days")
    if not isinstance(days, list):
        return payload

    flattened: list[dict] = []
    step_order = 1
    for day_position, day in enumerate(days):
        if not isinstance(day, dict):
            continue
        raw_day_index = day.get("day_index", day_position)
        day_steps = day.get("steps")
        if not isinstance(day_steps, list):
            continue
        for step in day_steps:
            if not isinstance(step, dict) or not step.get("poi_id"):
                continue
            ai_context = dict(step.get("ai_context") or {})
            for source_key, target_key in (
                ("poi_name", "poi_name"),
                ("poi_role", "poi_role"),
                ("scheduled_time", "scheduled_time"),
                ("duration_minutes", "duration_minutes"),
                ("notes", "notes"),
            ):
                if source_key in step and source_key not in ai_context:
                    ai_context[target_key] = step[source_key]
            ai_context.setdefault("day_index", raw_day_index)
            ai_context.setdefault("day_position", day_position)
            flattened.append(
                {
                    "step_order": int(step.get("step_order") or step_order),
                    "poi_id": step.get("poi_id") or step.get("poi_name") or step.get("name") or step.get("title"),
                    "arrival_time": step.get("arrival_time"),
                    "departure_time": step.get("departure_time"),
                    "ai_context": ai_context,
                }
            )
            step_order += 1

    normalized = dict(payload)
    normalized["steps"] = _normalize_step_poi_ids(flattened, context_pois)
    normalized.pop("days", None)
    normalized.setdefault("status", "planned")
    return normalized


def _normalize_text(value: str) -> str:
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents.lower()).strip()


def _is_uuid(value: Any) -> bool:
    try:
        UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


def _normalize_step_poi_ids(steps: list[dict], context_pois: list[POIResponse] | None) -> list[dict]:
    if not context_pois:
        return steps

    by_name = {_normalize_text(poi.name): str(poi.id) for poi in context_pois if getattr(poi, "name", None)}
    normalized_steps = []
    for raw_step in steps:
        if not isinstance(raw_step, dict):
            continue
        step = dict(raw_step)
        raw_poi_id = step.get("poi_id")
        if _is_uuid(raw_poi_id):
            normalized_steps.append(step)
            continue

        candidate_name = raw_poi_id or step.get("poi_name") or step.get("name") or step.get("title")
        normalized_name = _normalize_text(str(candidate_name or ""))
        matched_id = by_name.get(normalized_name)
        if matched_id is None and normalized_name:
            for poi_name, poi_id in by_name.items():
                if normalized_name in poi_name or poi_name in normalized_name:
                    matched_id = poi_id
                    break

        if matched_id is not None:
            ai_context = dict(step.get("ai_context") or {})
            ai_context.setdefault("original_poi_name", str(candidate_name))
            step["ai_context"] = ai_context
            step["poi_id"] = matched_id

        normalized_steps.append(step)

    return normalized_steps


def get_itinerary_generator() -> ItineraryGenerator:
    global _itinerary_generator

    if _itinerary_generator is None:
        _itinerary_generator = ItineraryGenerator()

    return _itinerary_generator
