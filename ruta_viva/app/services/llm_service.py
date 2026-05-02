from __future__ import annotations

import json

from openai import AsyncOpenAI

from app.core.config import settings
from app.schemas.itinerary import GeneratedItinerary
from app.schemas.poi import POIResponse


class ItineraryGenerator:
    def __init__(self) -> None:
        if not settings.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY is required to generate itineraries.")

        self.client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
        self.model = "deepseek-chat"

    async def generate_itinerary(self, user_query: str, context_pois: list[POIResponse]) -> dict:
        context_payload = [poi.model_dump(mode="json") for poi in context_pois]

        system_prompt = """
Eres un experto en turismo de La Araucanía, Chile.
Tu tarea es construir itinerarios turísticos realistas y útiles usando EXCLUSIVAMENTE los POIs entregados en el contexto.

Reglas obligatorias:
1. No inventes lugares, IDs, coordenadas ni actividades fuera del contexto.
2. Solo puedes usar poi_id que aparezcan en el contexto.
3. Devuelve únicamente JSON válido, sin markdown ni texto extra.
4. El JSON debe tener esta estructura exacta:
{
  "title": "string",
  "status": "planned",
  "steps": [
    {
      "step_order": 1,
      "poi_id": "uuid",
      "arrival_time": "ISO-8601 o null",
      "departure_time": "ISO-8601 o null",
      "ai_context": {
        "reason": "por qué este lugar aporta al itinerario",
        "tips": "consejos breves para el usuario",
        "recommended_duration": "duración sugerida en texto"
      }
    }
  ]
}
5. Si hay pocos lugares buenos, devuelve menos pasos en vez de inventar.
6. El itinerario debe ser coherente con la intención del usuario y con un recorrido turístico por La Araucanía.
""".strip()

        user_prompt = (
            f"Consulta del usuario:\n{user_query}\n\n"
            f"POIs de contexto (usa solo estos lugares):\n{json.dumps(context_payload, ensure_ascii=False)}"
        )

        response = await self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
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
