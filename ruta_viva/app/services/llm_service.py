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

    async def generate_itinerary(
        self,
        user_query: str,
        context_pois: list[POIResponse],
        weather_forecast: str,
        schedule_guidance: str,
    ) -> dict:
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
7. Se te proporcionará el pronóstico del clima para los días del viaje.
8. Debes priorizar actividades bajo techo o más protegidas en momentos de lluvia, viento fuerte o frío intenso.
9. Debes dejar las actividades al aire libre para momentos despejados o con clima más favorable.
10. En ai_context.reason menciona brevemente por qué el clima influyó en la decisión cuando sea relevante.
11. Se te proporcionarán reglas de visita por POI cuando existan: opening_hours_text y visit_rules.
12. No uses oficinas, CONAF o centros de información como parada turística principal salvo que el usuario lo pida explícitamente.
13. No inventes horarios. Si no hay horario conocido, aplica criterio conservador y explica la recomendación.
14. Si visit_rules.requires_daylight=true, programa ese POI con luz de día y evita tarde/noche salvo que exista regla conocida que lo permita.
15. Si visit_rules.night_suitable=true, puedes usar ese POI en tarde/noche si encaja con la intención del usuario.
16. Evita baches grandes sin explicación; usa bloques de mañana, almuerzo, tarde y noche opcional según la guía de horarios.
17. Para itinerarios generados debes incluir arrival_time y departure_time en cada paso; usa null solo si hay una razón fuerte.
""".strip()

        user_prompt = (
            f"Consulta del usuario:\n{user_query}\n\n"
            f"Pronóstico del clima para el viaje:\n{weather_forecast}\n\n"
            f"Guía de horarios y slots:\n{schedule_guidance}\n\n"
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
