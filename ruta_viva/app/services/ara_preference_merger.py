from __future__ import annotations

import re
from typing import Any

from app.core.ara_constants import (
    CULTURE_TERMS,
    FOOD_COMPLETION_TAGS,
    GENERATE_TERMS,
    LODGING_TERMS,
    NATURE_TERMS,
    SPECIFIC_FOOD_TERMS,
    SURPRISE_ROUTE_TERMS,
)
from app.services.ara_message_normalizer import normalize_message


def _extract_negative_constraints(normalized: str) -> list[str]:
    constraints: list[str] = []
    negative_markers = ("no quiero", "no kiero", "ni me hables", "evita", "evitar", "sin ", "no me gusta", "no tanto")
    has_negative = any(marker in normalized for marker in negative_markers)
    if has_negative and any(term in normalized for term in ("caminar", "caminata", "trekking", "sendero largo")):
        constraints.extend(["caminata_larga", "alta_exigencia_fisica"])
    if has_negative and any(term in normalized for term in ("alta dificultad", "dificil", "exigente", "pesado")):
        constraints.append("alta_dificultad")
    if has_negative and any(term in normalized for term in ("lejos", "traslado", "mucho camino")):
        constraints.append("mucho_traslado")
    if has_negative and any(term in normalized for term in ("comida chatarra", "rapida", "fast food")):
        constraints.append("comida_chatarra")
    if has_negative and any(term in normalized for term in ("efectivo", "solo efectivo")):
        constraints.append("solo_efectivo")
    return constraints


def _extract_positive_preferences(normalized: str) -> list[str]:
    preferences: list[str] = []
    if any(term in normalized for term in ("baja dificultad", "facil", "flojo", "suave")):
        preferences.append("baja_dificultad")
    if any(term in normalized for term in ("tranquilo", "relajado", "relajo")):
        preferences.append("tranquilo")
    if any(term in normalized for term in ("cerca", "cercano", "poco traslado")):
        preferences.append("poco_traslado")
    if any(term in normalized for term in ("ninos", "familia", "familiar")):
        preferences.append("apto_familia")
    if any(term in normalized for term in ("vista", "mirador")):
        preferences.append("buenas_vistas")
    return preferences


def _conflicts_with_negative_constraints(preference: str, constraints: set[str]) -> bool:
    conflicts = {
        "baja_dificultad": {"alta_dificultad"},
        "poco_traslado": {"mucho_traslado"},
    }
    return bool(conflicts.get(preference, set()) & constraints)


def _is_keyword_negated(normalized: str, keyword: str) -> bool:
    pattern = rf"\b(?:no quiero|ni me hables de|evita|evitar|sin)\b[\w\s]{{0,30}}\b{re.escape(keyword)}\b"
    return re.search(pattern, normalized) is not None


def compact_constraints(constraints: list[str], limit: int = 5) -> list[str]:
    priority = {
        "alta_dificultad": 0,
        "alta_exigencia_fisica": 1,
        "caminata_larga": 2,
        "mucho_traslado": 3,
        "sin_servicios_confirmados": 4,
        "comida_chatarra": 5,
        "solo_efectivo": 6,
    }
    deduped = sorted(set(constraints), key=lambda item: (priority.get(item, 99), item))
    return deduped[:limit]


def _conversation_mode_for_turn(turn_type: object) -> str:
    if turn_type == "free_question":
        return "answering_question"
    if turn_type == "generate_request":
        return "ready_to_generate"
    if turn_type == "reset_or_new_trip":
        return "exploring"
    if turn_type == "candidate_selection":
        return "refining"
    if turn_type in {"refinement", "show_options"}:
        return "refining"
    return "exploring"


def _estimate_route_ready_score(preferences: dict[str, Any]) -> float:
    score = 0.2
    score += min(len(preferences.get("positive_preferences", [])) * 0.12, 0.36)
    score += min(len(preferences.get("tags", [])) * 0.08, 0.24)
    score += min(int(preferences.get("turn_count", 0)) * 0.06, 0.18)
    score += min(len(preferences.get("completed_dimensions", [])) * 0.08, 0.24)
    score += min(len(preferences.get("selected_poi_ids", [])) * 0.1, 0.2)
    if preferences.get("show_options_requested"):
        score += 0.08
    if preferences.get("surprise_route_requested"):
        score += 0.18
    if preferences.get("auto_generate_requested"):
        score = 1.0
    return round(min(score, 1.0), 2)


def merge_preferences(
    message: str,
    previous_preferences: dict[str, Any] | None = None,
    turn_classification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preferences = dict(previous_preferences or {})
    normalized = normalize_message(message)
    tags = set(preferences.get("tags", []))
    positive_preferences = set(preferences.get("positive_preferences", []))
    negative_constraints = set(preferences.get("negative_constraints", []))
    consumed_reply_ids = set(preferences.get("consumed_reply_ids", []))
    last_added_tags: list[str] = []

    for constraint in _extract_negative_constraints(normalized):
        negative_constraints.add(constraint)

    for preference in _extract_positive_preferences(normalized):
        if not _conflicts_with_negative_constraints(preference, negative_constraints):
            positive_preferences.add(preference)

    keyword_to_tag = {
        "pizza": "pizza",
        "pizzería": "pizza",
        "pizzeria": "pizza",
        "artesanal": "artesanal",
        "vista": "vista",
        "lago": "lago",
        "familiar": "familiar",
        "familia": "familiar",
        "rápido": "rapido",
        "rapido": "rapido",
        "cercano": "cercano",
        "cerca": "cercano",
        "reseñas": "buenas_resenas",
        "opiniones": "buenas_resenas",
        "tranquilo": "tranquilo",
        "turístico": "turistico",
        "turistico": "turistico",
        "sendero": "sendero",
        "mirador": "mirador",
        "terma": "termas",
        "mapuche": "mapuche",
    }
    for keyword, tag in keyword_to_tag.items():
        if keyword in normalized and tag not in tags and not _is_keyword_negated(normalized, keyword):
            tags.add(tag)
            last_added_tags.append(tag)

    is_surprise_route = any(term in normalized for term in SURPRISE_ROUTE_TERMS)
    is_generate_request = any(term in normalized for term in GENERATE_TERMS)

    if is_surprise_route:
        preferences["surprise_route_requested"] = True
        preferences["route_balance_mode"] = "surprise_balanced"
        positive_preferences.add("ruta_balanceada")
        consumed_reply_ids.add("hazlo_todo_tu")
    if is_generate_request:
        preferences["auto_generate_requested"] = True
        consumed_reply_ids.add("crear_itinerario")
    if "muéstrame opciones" in normalized or "muestrame opciones" in normalized or "ver opciones" in normalized:
        preferences["show_options_requested"] = True
        consumed_reply_ids.add("ver_opciones")

    for match in re.finditer(r"\b(?:prefiero|quiero|busco|usar)\s+([\wáéíóúñ]+)", normalized):
        consumed_reply_ids.add(match.group(1))

    completed_dimensions = set(preferences.get("completed_dimensions", []))
    is_candidate_selection = (
        turn_classification is not None and turn_classification.get("turn_type") == "candidate_selection"
    )
    if is_candidate_selection:
        if tags & FOOD_COMPLETION_TAGS or any(term in normalized for term in SPECIFIC_FOOD_TERMS):
            completed_dimensions.add("gastronomia")
        if any(term in normalized for term in LODGING_TERMS):
            completed_dimensions.add("alojamiento")
        if any(term in normalized for term in NATURE_TERMS):
            completed_dimensions.add("naturaleza")
        if any(term in normalized for term in CULTURE_TERMS):
            completed_dimensions.add("cultura")

    preferences["tags"] = sorted(tags)
    preferences["completed_dimensions"] = sorted(completed_dimensions)
    preferences["positive_preferences"] = sorted(positive_preferences)
    preferences["negative_constraints"] = compact_constraints(sorted(negative_constraints))
    preferences["last_added_tags"] = last_added_tags
    preferences["consumed_reply_ids"] = sorted(consumed_reply_ids)
    preferences["turn_count"] = int(preferences.get("turn_count", 0)) + 1
    preferences["route_ready_score"] = _estimate_route_ready_score(preferences)
    if turn_classification:
        preferences["last_turn_type"] = turn_classification.get("turn_type")
        preferences["last_question_topic"] = turn_classification.get("topic")
        preferences["conversation_mode"] = _conversation_mode_for_turn(turn_classification.get("turn_type"))
    return preferences


def apply_memory_patch(
    preferences: dict[str, Any],
    memory_patch: dict[str, Any] | None,
) -> dict[str, Any]:
    updated = dict(preferences)
    for key, value in (memory_patch or {}).items():
        if key == "answered_questions":
            existing = set(updated.get("answered_questions", []))
            existing.update(str(item) for item in value if item)
            updated[key] = sorted(existing)
        else:
            updated[key] = value
    return updated


def reset_trip_preferences(message: str) -> dict[str, Any]:
    turn_classification = {"turn_type": "reset_or_new_trip", "topic": "new_trip"}
    preferences = merge_preferences(message, previous_preferences={}, turn_classification=turn_classification)
    preferences["conversation_mode"] = "exploring"
    preferences["active_itinerary_id"] = None
    preferences["active_itinerary_poi_ids"] = []
    preferences["candidate_poi_ids"] = []
    return preferences
