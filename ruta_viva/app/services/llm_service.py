from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from openai import AsyncOpenAI

from app.core.config import settings
from app.core.llm_retry import with_retry
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
        stream_callback: Callable[[str], Awaitable[None]] | None = None,
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
11. Se te proporcionarán reglas de visita por POI cuando existan: opening_hours_text y visit_rules. ANTES de asignar un POI a un slot horario, VERIFICÁ su opening_hours_text para asegurarte de que esté abierto en ese momento. Si abre a las 13:00, no lo pongas a las 09:00.
12. No uses oficinas, CONAF o centros de información como parada turística principal salvo que el usuario lo pida explícitamente.
13. No inventes horarios. Si no hay horario conocido, aplica criterio conservador y explica la recomendación.
14. Si visit_rules.requires_daylight=true, programa ese POI con luz de día y evita tarde/noche salvo que exista regla conocida que lo permita.
15. Si visit_rules.night_suitable=true, puedes usar ese POI en tarde/noche si encaja con la intención del usuario.
16. Evita baches grandes sin explicación; usa bloques de mañana, almuerzo, tarde y noche opcional según la guía de horarios.
17. Para itinerarios generados debes incluir arrival_time y departure_time en cada paso; usa null solo si hay una razón fuerte.
18. No uses hoteles, hostales, cabañas ni alojamientos como parada turística de tránsito, descanso, visita o recomendación de medio día salvo que el usuario haya pedido explícitamente alojamiento/check-in.
19. Si el usuario sí pidió alojamiento, usa como máximo un alojamiento por día y solo al inicio o al final del día. Nunca hagas "hostel-hopping" ni cambies de alojamiento como actividad turística.
20. No escribas consejos que manden al usuario a pedir recomendaciones a recepción, CONAF, anfitriones, personal del hotel o terceros. La app debe entregar la recomendación; no delegues la guía.
21. En ai_context.tips no uses frases como "consulta su menú", "pregunta por recomendaciones cercanas", "pide información", "consulta en recepción" o equivalentes. Da consejos accionables propios: reserva, lleva agua, verifica clima, calcula traslado, respeta horarios.
22. El tono dentro de reason y tips debe sonar como guía turístico humano, no como metalenguaje técnico. No menciones "contexto", "POIs de contexto", "datos entregados", "ranking", "embedding" ni "modelo". No uses frases algorítmicas como "para mantener variedad", "evitar repetir el mismo lugar", "como alternativa a", "para equilibrar la ruta", "para variar", "no saturar", "romper con la misma categoría". Describí el valor turístico real del lugar: su paisaje, ambiente, historia o lo que lo hace especial.
23. Las fechas oficiales del viaje son las que aparecen explícitamente en la guía de horarios. Si la consulta del usuario menciona otras fechas en lenguaje natural, ignóralas y respeta la guía de horarios.
24. arrival_time y departure_time deben quedar SIEMPRE dentro del rango oficial del viaje y en horario de Chile continental.
25. Devuelve arrival_time y departure_time en ISO-8601 con zona horaria America/Santiago, usando offset -03:00 o -04:00 según corresponda. No uses "Z" ni UTC.
26. Para viajes de varios días, reparte actividades en cada fecha oficial. No dejes días vacíos salvo que el usuario pida descanso/traslado; si lo haces, explica esa pausa en ai_context.reason de una parada cercana.
27. No repitas el mismo poi_id en más de un día salvo que el usuario pida explícitamente repetirlo.
28. Evita repetir exactamente la misma secuencia de categorías y horarios en días distintos. Un viaje multi-día debe sentirse variado, no como una plantilla copiada.
29. Si usas gastronomía en varios días, prefiere lugares distintos y estilos distintos. No recomiendes la misma pizzería o la misma comida todos los días salvo petición explícita.
30. Varía la densidad diaria: no uses siempre la misma cantidad de pasos por día. Día 1 puede ser más liviano, días intermedios más completos y último día más flexible.
31. No uses cementerios, vertederos, zonas industriales, terminales de buses puros, hospitales, farmacias, bancos, baños, combustible, policía u otros servicios logísticos como panoramas turísticos familiares. Solo podrían aparecer si el usuario los pidió explícitamente por razones patrimoniales, transporte o necesidad práctica.
32. Si el contexto disponible es pobre, devuelve menos pasos útiles o explica una limitación dentro de ai_context.reason; no rellenes repitiendo los mismos POIs.
33. Si la consulta incluye un "Borrador estructurado del viaje", úsalo como fuente principal para destino, alcance por día, comidas, alojamiento, POIs seleccionados y política climática.
34. Las preferencias con scope=unspecified son preferencias generales: ubícalas una vez donde mejor calcen, no las repitas todos los días salvo que scope=all_days o el usuario lo pida.
35. Las preferencias con scope=day o slot deben respetarse en ese día/slot si existe un POI compatible. El alojamiento con scope=entire_trip funciona como base del viaje, no como actividad turística.
36. Si weather_policy.overrides contiene allow_bad_weather para una actividad, puedes mantener esa actividad aunque el pronóstico no sea ideal, explicando la decisión de forma honesta.
37. Usa lodging_plan, meal_plan y activity_plan para distinguir planes estructurados por noche/día/slot; selected_pois con locked=false son preferencias flexibles que debes ubicar donde tengan más sentido.
38. Si el borrador del viaje indica destination_scope.strict=true, respeta estrictamente ese destino y no reemplaces una comuna menos turística por Pucón, Villarrica, Temuco u otra zona más conocida. Los lugares poco conocidos son válidos si calzan con la intención del usuario. Si el pool local es pequeño, genera menos pasos útiles o explica la limitación; no rellenes con destinos externos.
""".strip()

        user_prompt = (
            f"Consulta del usuario:\n{user_query}\n\n"
            f"Pronóstico del clima para el viaje:\n{weather_forecast}\n\n"
            f"Guía de horarios y slots:\n{schedule_guidance}\n\n"
            f"POIs de contexto (usa solo estos lugares):\n{json.dumps(context_payload, ensure_ascii=False)}"
        )

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
