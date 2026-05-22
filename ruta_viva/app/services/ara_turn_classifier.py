from __future__ import annotations

import re
from typing import Any
from uuid import UUID

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
from app.services.ara_message_normalizer import normalize_message


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


def classify_turn(
    message: str,
    previous_intent: dict[str, Any] | None = None,
    previous_preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_message(message)

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


def analyze_intent(message: str, previous_intent: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_message(message)
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
