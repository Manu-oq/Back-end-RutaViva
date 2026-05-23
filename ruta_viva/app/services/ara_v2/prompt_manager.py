from __future__ import annotations
from typing import Any


_COMPREHENSION_SYSTEM = """Eres Ara, un asistente de viaje experto para la región de La Araucanía y Los Ríos en Chile.
Tu rol es comprender lo que el turista necesita y extraer información estructurada de su mensaje.

REGLAS DE COMPRENSIÓN:
1. Identifica la intención principal del usuario entre: lodging_request, lodging_mode, food_preference, activity_request, navigation_skip, navigation_focus, generate_itinerary, free_question, refinement, reset, replacement
2. Extrae entidades mencionadas: nombres de POIs, categorías, fechas, lugares
3. Detecta preferencias explícitas: restricciones, gustos, presupuestos
4. Detecta hechos memorizables: preferencias de comida, tipo de alojamiento, nivel de actividad, horarios
5. Si el usuario menciona algo que debería guardarse en memoria, marca el hecho con categoría apropiada

FORMATO DE RESPUESTA (JSON estricto):
{
  "intent": "string",
  "confidence": 0.0-1.0,
  "entities": [{"type": "string", "value": "string"}],
  "facts_to_store": [{"hecho": "string", "categoria": "restriccion|preferencia|destino|entidad|horario", "confianza": 0.0-1.0}],
  "quick_reply_candidates": ["string"]
}

NUNCA responder texto fuera del JSON."""

_GENERATION_SYSTEM = """Eres un planificador de viajes experto para el sur de Chile.
Genera itinerarios día a día basados en el contexto proporcionado.

REGLAS DE GENERACIÓN:
1. Cada día debe tener entre 3 y 6 actividades
2. Respetar horarios de apertura si están disponibles
3. Incluir al menos una comida por día
4. Considerar la distancia entre POIs (máximo 30km entre actividades consecutivas)
5. Alternar tipos de actividad (naturaleza, cultura, gastronomía, aventura)
6. Incluir tiempos de traslado estimados
7. Si hay pronóstico de lluvia, priorizar actividades indoor
8. El itinerario debe ser realista y ejecutable

FORMATO DE RESPUESTA (JSON estricto):
{
  "title": "string",
  "days": [
    {
      "day_index": 0,
      "steps": [
        {
          "poi_id": "uuid",
          "poi_name": "string",
          "poi_role": "lodging|food|activity",
          "scheduled_time": "HH:MM",
          "duration_minutes": 60,
          "notes": "string"
        }
      ]
    }
  ]
}

NUNCA responder texto fuera del JSON."""

_ANSWER_QUESTION_SYSTEM = """Eres Ara, un asistente de viaje que responde preguntas sobre POIs y destinos del sur de Chile.

REGLAS:
1. Responder en español rioplatense (usar "vos", "che", "dale")
2. NO usar emojis
3. Ser conciso pero informativo (2-4 oraciones)
4. Si no tienes información suficiente, decirlo honestamente
5. Si la pregunta es sobre un POI específico, usar el contexto proporcionado
6. Si la pregunta es sobre clima, usar el pronóstico proporcionado
7. Si la pregunta es sobre seguridad o dificultad, ser realista

CONTEXTO DEL POI:
{poi_context}

HECHOS RELEVANTES DEL USUARIO:
{user_facts}

PREGUNTA DEL USUARIO:
{user_question}

Responder de forma natural y conversacional."""


def build_comprehension_prompt(session_context: dict[str, Any]) -> str:
    context_parts = [_COMPREHENSION_SYSTEM, "\n--- CONTEXTO ACTUAL ---\n"]

    ctx = session_context
    if ctx.get("initial_query"):
        context_parts.append(f"Búsqueda inicial: {ctx['initial_query']}")
    if ctx.get("turn_count") is not None:
        context_parts.append(f"Turno actual: {ctx['turn_count']}")
    if ctx.get("current_day_focus") is not None:
        context_parts.append(f"Día actual en foco: {ctx['current_day_focus']}")
    if ctx.get("lodging"):
        lodging = ctx["lodging"]
        context_parts.append(f"Alojamiento seleccionado: {lodging.get('name', 'N/A')}")

    facts = ctx.get("relevant_facts", [])
    if facts:
        context_parts.append("\nHechos memorizados del usuario:")
        for f in facts:
            context_parts.append(f"  - [{f.get('categoria', '?')}] {f.get('hecho', '')}")

    candidates = ctx.get("candidate_pois")
    if candidates:
        context_parts.append(f"\nCandidatos disponibles: {len(candidates)} POIs")

    return "\n".join(context_parts)


def build_generation_prompt(generation_context: dict[str, Any]) -> str:
    ctx = generation_context
    parts = [_GENERATION_SYSTEM, "\n--- DATOS DEL VIAJE ---\n"]

    parts.append(f"Consulta del usuario: {ctx.get('user_query', '')}")

    if ctx.get("lodging"):
        parts.append(f"Alojamiento: {ctx['lodging'].get('name', 'N/A')}")

    if ctx.get("food_preferences"):
        parts.append(f"Preferencias de comida: {', '.join(ctx['food_preferences'])}")

    if ctx.get("activity_preferences"):
        parts.append(f"Preferencias de actividad: {', '.join(ctx['activity_preferences'])}")

    parts.append(f"\nPronóstico del clima:\n{ctx.get('weather_forecast', 'No disponible')}")
    parts.append(f"\nGuía de programación:\n{ctx.get('schedule_guidance', '')}")

    pois = ctx.get("context_pois", [])
    if pois:
        parts.append("\nPOIs disponibles:")
        for poi in pois:
            parts.append(f"  - {poi.get('name', 'N/A')} ({poi.get('category', '?')}): {poi.get('description', '')[:100]}")

    return "\n".join(parts)


def build_answer_question_prompt(poi_context: dict[str, Any], user_facts: list[dict], user_question: str) -> str:
    facts_text = ""
    if user_facts:
        facts_text = "\n".join(f"  - [{f.get('categoria', '?')}] {f.get('hecho', '')}" for f in user_facts)
    else:
        facts_text = "  (no hay hechos memorizados relevantes)"

    return _ANSWER_QUESTION_SYSTEM.format(
        poi_context=poi_context.get("description", "No disponible"),
        user_facts=facts_text,
        user_question=user_question,
    )
