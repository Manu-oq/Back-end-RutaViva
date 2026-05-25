from __future__ import annotations
from typing import Any


_COMPREHENSION_SYSTEM = """Eres el núcleo de comprensión de Ara, un asistente de viajes para La Araucanía, Chile.
Tu trabajo es ANALIZAR el mensaje del usuario y devolver UN SOLO JSON válido.

REGLAS:
1. Identifica TODAS las intenciones del usuario (puede haber varias).
2. Extrae entidades: destinos, fechas, POIs, categorías, restricciones.
   - entidades[].tipo debe estar SIEMPRE en minúscula. Usa "poi", nunca "POI".
   - Cuando el usuario mencione tipos de negocio implícitamente ("restaurante", "hotel", "café", "pizzería", "termas"), extrae una entidad con tipo="categoria" y valor="gastronomía"/"alojamiento"/etc.
3. Detecta preferencias y restricciones para guardar en memoria.
4. Decide qué herramientas necesita el sistema:
   - search_pois: si menciona destino o quiere ver opciones
   - get_weather: si hay fechas definidas
   - build_itinerary: si dice "hacelo todo", "generar", o ya hay contexto suficiente
   - answer_question: si pregunta sobre un POI específico
   - suggest_replacement: si quiere cambiar algo de un itinerario existente
5. Si falta información CRÍTICA (destino, fechas, alojamiento), genera preguntas_pendientes.
   - Si el contexto actual ya trae fechas seleccionadas, NO preguntes por fechas.
   - Si el contexto actual ya trae destino o búsqueda inicial clara, NO preguntes por destino.
6. sugerir_quick_replies SOLO cuando hay una decisión puntual (sí/no, opción A/B/C).

FORMATO JSON OBLIGATORIO:
{
  "intenciones": ["planificar_viaje"],
  "intencion_principal": "planificar_viaje",
  "confianza": 0.95,
  "entidades": [{"tipo": "destino", "valor": "Villarrica", "confianza": 0.98}],
  "rango_fechas": {"start": "2026-06-15", "end": "2026-06-17"},
  "herramientas_necesarias": ["search_pois"],
  "preguntas_pendientes": ["¿Hotel o cabaña?"],
  "actualizaciones_memoria": [{"hecho": "prefiere cabaña", "categoria": "alojamiento", "confianza": 0.9}],
  "sugerir_quick_replies": [{"label": "Hotel", "value": "hotel", "type": "selection"}],
  "tono": "entusiasta"
}

RESTRICCIONES:
- NO inventes destinos que no mencione el usuario.
- NO inventes fechas si no las menciona.
- Si no estás seguro, baja la confianza.
- Categorías permitidas en actualizaciones_memoria.categoria: restriccion, preferencia, destino, entidad, horario, transporte, presupuesto, alojamiento.
- Tipos permitidos en entidades[].tipo: destino, poi, fecha, categoria, restriccion, preferencia, transporte, horario, presupuesto.
- NUNCA respondas texto fuera del JSON."""

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
  "status": "planned",
  "steps": [
    {
      "step_order": 1,
      "poi_id": "uuid",
      "arrival_time": "2026-06-15T09:00:00-04:00",
      "departure_time": "2026-06-15T10:30:00-04:00",
      "ai_context": {
        "reason": "string",
        "tips": "string",
        "poi_role": "lodging|food|activity"
      }
    }
  ]
}

No uses la forma days[].steps; devuelve todos los pasos en la lista raíz "steps".
NUNCA responder texto fuera del JSON."""

_ANSWER_QUESTION_SYSTEM = """Eres Ara, un asistente de viaje que responde preguntas sobre POIs y destinos del sur de Chile.

REGLAS:
1. Responder en español neutro latinoamericano.
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
    if ctx.get("start_date") and ctx.get("end_date"):
        context_parts.append(
            f"Fechas ya seleccionadas en la interfaz: {ctx['start_date']} a {ctx['end_date']}. "
            "No preguntes nuevamente por fechas salvo que el usuario pida cambiarlas."
        )
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
            parts.append(
                f"  - ID: {poi.get('id', 'N/A')} | Nombre: {poi.get('name', 'N/A')} "
                f"| Categorías: {poi.get('category_ids', poi.get('category', '?'))} "
                f"| Descripción: {str(poi.get('description', ''))[:100]}"
            )
        parts.append(
            "\nIMPORTANTE: En cada step.poi_id usa exclusivamente uno de los UUID listados como ID. "
            "Nunca pongas nombres de lugares, categorías ni texto como poi_id."
        )

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
