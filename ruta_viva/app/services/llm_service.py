from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from openai import AsyncOpenAI

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

        parsed = json.loads(content)
        validated = GeneratedItinerary.model_validate(parsed)
        return validated.model_dump(mode="python")


_itinerary_generator: ItineraryGenerator | None = None


def get_itinerary_generator() -> ItineraryGenerator:
    global _itinerary_generator

    if _itinerary_generator is None:
        _itinerary_generator = ItineraryGenerator()

    return _itinerary_generator
