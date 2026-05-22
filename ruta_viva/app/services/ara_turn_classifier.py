from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI

from app.core.ara_constants import (
    ADVENTURE_TERMS,
    CULTURE_TERMS,
    FOOD_TERMS,
    GENERATE_TERMS,
    ITINERARY_ID_PATTERN,
    LOCATION_PATTERN,
    LODGING_TERMS,
    NATURE_TERMS,
    REFINEMENT_TERMS,
    RESET_TERMS,
    REST_TERMS,
    SELECT_POI_PATTERN,
    SHOW_OPTIONS_TERMS,
    SPECIFIC_FOOD_TERMS,
    STEP_ID_PATTERN,
    SURPRISE_ROUTE_TERMS,
    USE_POI_PATTERN,
    UUID_PATTERN,
)
from app.core.config import settings
from app.services.ara_message_normalizer import normalize_message

logger = logging.getLogger(__name__)

_CLASSIFICATION_PROMPT = (
    "Eres un clasificador de intenciones para un asistente de viajes turisticos en La Araucania, Chile.\n"
    "Debes clasificar el mensaje del usuario en UNO de los siguientes tipos de turno:\n"
    "\n"
    "1. replace_step: El usuario quiere reemplazar un paso especifico de un itinerario existente.\n"
    "   Ejemplos: \"cambia la visita al museo por otra cosa\", \"reemplaza el restaurante por uno mas economico\", \"pon otro lugar en vez del lago\"\n"
    "\n"
    "2. candidate_selection: El usuario selecciona una de las opciones que se le mostraron.\n"
    "   Ejemplos: \"quiero la opcion 2\", \"me gusta el primero\", \"ese\", \"el de la playa\", \"prefiero el restaurant\"\n"
    "\n"
    "3. reset_or_new_trip: El usuario quiere empezar de cero o planear un viaje completamente nuevo.\n"
    "   Ejemplos: \"olvidalo todo\", \"empecemos de nuevo\", \"mejor hagamos otro plan\", \"partamos de cero\"\n"
    "\n"
    "4. generate_request: El usuario pide explicitamente generar o crear el itinerario.\n"
    "   Ejemplos: \"genera el itinerario\", \"crea la ruta\", \"arma el viaje\", \"dame el plan completo\"\n"
    "\n"
    "5. free_question: El usuario hace una pregunta sobre un destino, actividad o servicio.\n"
    "   Ejemplos: \"que clima hara?\", \"es dificil el sendero?\", \"cuanto cuesta la entrada?\", \"donde queda?\"\n"
    "\n"
    "6. replacement_request: El usuario proporciona instrucciones explicitas para reemplazar un paso.\n"
    "   Ejemplos: \"reemplaza el paso de la manana por algo mejor\", \"cambia el tercer dia\"\n"
    "\n"
    "7. refinement: El usuario ajusta preferencias, restricciones o detalles de lo que busca.\n"
    "   Ejemplos: \"quiero algo mas tranquilo\", \"prefiero comida italiana\", \"busco algo para ninos\", \"nada de caminatas largas\"\n"
    "\n"
    "8. general_chat: Conversacion general o amable que no calza en los tipos anteriores.\n"
    "   Ejemplos: \"hola\", \"gracias\", \"que tal\", \"oye y tu que recomiendas?\"\n"
    "\n"
    "Ademas extrae la siguiente informacion adicional del mensaje:\n"
    "- primary_intent: La intencion principal (meal, activity, lodging, info, nature, culture, general)\n"
    "- specificity: Que tan especifica es la solicitud (vague, specific, explicit)\n"
    "- locations: Lista de lugares o destinos mencionados (arreglo vacio si no hay)\n"
    "- niche_term_used: Si el usuario uso un termino especifico o de nicho como \"sendero\", \"mirador\", \"pizza\", \"sushi\" (true/false)\n"
    "- topic: Subtema o contexto especifico del turno\n"
    "\n"
    "Responde SOLO con JSON valido en este formato exacto, sin texto adicional:\n"
    "{\n"
    '  "turn_type": "replace_step",\n'
    '  "topic": "replace_step",\n'
    '  "primary_intent": "general",\n'
    '  "specificity": "vague",\n'
    '  "locations": [],\n'
    '  "niche_term_used": false\n'
    "}"
)


def get_classifier_llm_client() -> AsyncOpenAI | None:
    if not settings.deepseek_api_key:
        logger.info("No DEEPSEEK_API_KEY configured — LLM classifier disabled")
        return None
    return AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )


def _build_classification_messages(
    message: str,
    normalized: str,
    session_context: dict | None = None,
) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": _CLASSIFICATION_PROMPT}]

    context_lines: list[str] = []
    if session_context and session_context.get("previous_messages"):
        for msg in session_context["previous_messages"][-6:]:
            role_label = "Usuario" if msg["role"] == "user" else "Asistente"
            context_lines.append(f"{role_label}: {msg['content']}")

    user_content = f"Mensaje del usuario: {message}"
    if context_lines:
        user_content = (
            f"Contexto de la conversacion (ultimos turnos):\n"
            f"{chr(10).join(context_lines)}\n\n"
            f"{user_content}"
        )

    messages.append({"role": "user", "content": user_content})
    return messages


async def classify_turn_llm(
    message: str,
    normalized: str,
    session_context: dict | None = None,
    llm_client: AsyncOpenAI | None = None,
) -> dict | None:
    if llm_client is None:
        return None

    try:
        response = await llm_client.chat.completions.create(
            model="deepseek-chat",
            temperature=0,
            max_tokens=200,
            timeout=5,
            messages=_build_classification_messages(message, normalized, session_context),
        )
        content = response.choices[0].message.content
        if not content:
            logger.warning("LLM classifier returned empty content")
            return None

        content = content.strip()
        if content.startswith("``"):
            content = content.split("\n", 1)[-1]
            fence = "``" + "`" if content.endswith("``" + "`") else "```"
            content = content.rsplit(fence, 1)[0].strip()

        result = json.loads(content)
        result["confidence"] = "llm_based"
        logger.info("LLM classification: turn_type=%s topic=%s primary_intent=%s", result.get("turn_type"), result.get("topic"), result.get("primary_intent"))
        return result
    except Exception as exc:
        logger.warning("LLM classifier failed: %s", exc)
        return None


def extract_itinerary_step_context(message: str) -> dict[str, UUID] | None:
    itinerary_match = ITINERARY_ID_PATTERN.search(message)
    step_match = STEP_ID_PATTERN.search(message)
    if itinerary_match and step_match:
        return {
            "itinerary_id": UUID(itinerary_match.group("id")),
            "step_id": UUID(step_match.group("id")),
        }

    uuids = [UUID(value) for value in UUID_PATTERN.findall(message)]
    if "cambiar" in message.lower() and len(uuids) >= 2:
        return {"itinerary_id": uuids[0], "step_id": uuids[1]}
    return None


def extract_replace_selection(message: str, preferences: dict[str, Any] | None = None) -> dict[str, UUID] | None:
    match = USE_POI_PATTERN.search(message)
    if not match:
        return None

    step_id_value = match.group("step_id")
    if step_id_value is None and preferences:
        replacement_context = preferences.get("replacement_context") or {}
        step_id_value = replacement_context.get("step_id")

    if step_id_value is None:
        return None

    return {
        "poi_id": UUID(match.group("poi_id")),
        "step_id": UUID(step_id_value),
    }


def extract_candidate_selection(message: str) -> UUID | None:
    match = SELECT_POI_PATTERN.search(message)
    if not match:
        return None
    return UUID(match.group("poi_id"))


def _has_specific_niche(normalized_message: str) -> bool:
    return any(term in normalized_message for term in SPECIFIC_FOOD_TERMS) or any(
        term in normalized_message for term in ("sendero", "mirador", "lago", "terma", "volcán", "volcan", "museo")
    )


def _detect_question_topic(normalized: str) -> str:
    if any(term in normalized for term in ("dificultad", "dificil", "facil", "peligroso", "seguro", "camino", "ripio")):
        return "difficulty"
    if any(term in normalized for term in ("auto", "vehiculo", "bici", "caminando", "acceso", "estacionamiento", "lejos", "distancia")):
        return "access"
    if any(term in normalized for term in ("precio", "entrada", "ticket", "pagar", "costo")):
        return "price"
    if any(term in normalized for term in ("horario", "abierto", "cerrado", "hora")):
        return "schedule"
    if any(term in normalized for term in ("clima", "lluvia", "frio", "calor", "viento")):
        return "weather"
    if any(term in normalized for term in ("ninos", "familia", "adulto mayor", "guagua")):
        return "children"
    if any(term in normalized for term in ("bano", "baño", "servicio", "sombra", "accesibilidad", "silla de ruedas")):
        return "services"
    if any(term in normalized for term in ("primer", "segund", "tercer", "pizza", "cascada", "parada", "lugar")):
        return "poi_detail"
    if any(term in normalized for term in ("que significa", "a que te refieres", "se puede", "conviene", "sirve")):
        return "general"
    return "general"


def _detect_refinement_topic(normalized: str) -> str:
    if any(term in normalized for term in ("nino", "familia")):
        return "children"
    if any(term in normalized for term in ("cerca", "lejos", "traslado")):
        return "access"
    if any(term in normalized for term in ("dificultad", "caminar", "flojo", "tranquilo")):
        return "difficulty"
    return "preferences"


async def classify_turn(
    message: str,
    previous_intent: dict[str, Any] | None = None,
    previous_preferences: dict[str, Any] | None = None,
    llm_client: AsyncOpenAI | None = None,
    session_context: dict | None = None,
) -> dict[str, Any]:
    normalized = normalize_message(message)

    llm_result = await classify_turn_llm(message, normalized, session_context, llm_client)
    if llm_result is not None:
        return {
            "turn_type": llm_result.get("turn_type", "general_chat"),
            "topic": llm_result.get("topic", "general"),
            "confidence": "llm_based",
        }

    logger.info("Rule-based classify_turn fallback for: %.80r", message)

    if extract_replace_selection(message, previous_preferences) is not None:
        return {"turn_type": "replace_step", "topic": "replace_step", "confidence": "high_rule_based"}
    if extract_candidate_selection(message) is not None:
        return {"turn_type": "candidate_selection", "topic": "poi_selection", "confidence": "high_rule_based"}
    if extract_itinerary_step_context(message) is not None:
        return {"turn_type": "replace_step", "topic": "replace_step", "confidence": "high_rule_based"}
    if any(term in normalized for term in RESET_TERMS):
        return {"turn_type": "reset_or_new_trip", "topic": "new_trip", "confidence": "high_rule_based"}
    if any(term in normalized for term in GENERATE_TERMS):
        return {"turn_type": "generate_request", "topic": "generation", "confidence": "high_rule_based"}
    if any(term in normalized for term in SURPRISE_ROUTE_TERMS):
        return {"turn_type": "refinement", "topic": "surprise_route", "confidence": "high_rule_based"}
    if any(term in normalized for term in SHOW_OPTIONS_TERMS):
        return {"turn_type": "show_options", "topic": "options", "confidence": "high_rule_based"}

    topic = _detect_question_topic(normalized)
    has_refinement = any(term in normalized for term in REFINEMENT_TERMS)
    has_negative_preference = any(term in normalized for term in ("no quiero", "ni me hables", "evita", "evitar", "no me gusta"))
    has_free_question = topic != "general" or normalized.startswith(("que ", "como ", "cuando ", "donde ", "por que "))

    if has_refinement or has_negative_preference:
        return {"turn_type": "refinement", "topic": _detect_refinement_topic(normalized), "confidence": "rule_based"}
    if has_free_question:
        return {"turn_type": "free_question", "topic": topic, "confidence": "rule_based"}

    if previous_preferences and previous_preferences.get("conversation_mode") == "post_generation":
        return {"turn_type": "free_question", "topic": "poi_detail", "confidence": "contextual_rule_based"}

    return {"turn_type": "general_chat", "topic": "general", "confidence": "low_rule_based"}


async def analyze_intent(
    message: str,
    previous_intent: dict[str, Any] | None = None,
    llm_client: AsyncOpenAI | None = None,
    session_context: dict | None = None,
) -> dict[str, Any]:
    normalized = normalize_message(message)

    llm_result = await classify_turn_llm(message, normalized, session_context, llm_client)
    if llm_result is not None:
        llm_primary = llm_result.get("primary_intent", "general")
        llm_specificity = llm_result.get("specificity", "vague")
        llm_locations = llm_result.get("locations", [])
        return {
            "intents": [llm_primary],
            "primary_intent": llm_primary,
            "locations": llm_locations,
            "specificity": llm_specificity,
            "confidence": "llm_based",
        }

    logger.info("Rule-based analyze_intent fallback for: %.80r", message)

    intents: list[str] = []
    if any(term in normalized for term in FOOD_TERMS):
        intents.append("gastronomia")
    if any(term in normalized for term in NATURE_TERMS):
        intents.append("naturaleza")
    if any(term in normalized for term in CULTURE_TERMS):
        intents.append("cultura")
    if any(term in normalized for term in REST_TERMS):
        intents.append("descanso")
    if any(term in normalized for term in ADVENTURE_TERMS):
        intents.append("aventura")
    if any(term in normalized for term in LODGING_TERMS):
        intents.append("alojamiento")

    if not intents and previous_intent:
        intents = list(previous_intent.get("intents", []))
    if not intents:
        intents = ["exploracion"]

    locations = list(previous_intent.get("locations", [])) if previous_intent else []
    location_match = LOCATION_PATTERN.search(message)
    if location_match:
        location = location_match.group(1).strip()
        if location not in locations:
            locations.append(location)

    specificity = "specific" if _has_specific_niche(normalized) else "broad"
    if any(term in normalized for term in ("no sé", "no se", "no tengo claro", "algo", "recomiéndame", "recomiendame")):
        specificity = "broad"

    return {
        "intents": intents,
        "primary_intent": intents[0],
        "locations": locations,
        "specificity": specificity,
        "confidence": "rule_based",
    }
