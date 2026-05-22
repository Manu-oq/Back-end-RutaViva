from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.core.ara_messages import AraMessages
from app.schemas.ara import AraQuickReply
from app.schemas.poi import POIResponse
from app.services.ara_preference_merger import compact_constraints


def dedupe_quick_replies(replies: list[AraQuickReply]) -> list[AraQuickReply]:
    seen_ids: set[str] = set()
    seen_labels: set[str] = set()
    deduped: list[AraQuickReply] = []
    for reply in replies:
        label_key = reply.label.strip().lower()
        if reply.id in seen_ids or label_key in seen_labels:
            continue
        seen_ids.add(reply.id)
        seen_labels.add(label_key)
        deduped.append(reply)
    return deduped


def should_offer_create_itinerary(preferences: dict[str, Any]) -> bool:
    if preferences.get("auto_generate_requested"):
        return True
    if preferences.get("surprise_route_requested"):
        return True
    if float(preferences.get("route_ready_score") or 0) >= 0.45:
        return True
    if preferences.get("selected_poi_ids"):
        return True
    return bool(preferences.get("completed_dimensions") and int(preferences.get("turn_count", 0)) >= 1)


def build_quick_replies(intent: dict[str, Any], preferences: dict[str, Any]) -> list[AraQuickReply]:
    primary_intent = intent.get("primary_intent", "exploracion")
    specificity = intent.get("specificity", "broad")
    tag_set = set(preferences.get("tags", []))
    completed_dimensions = set(preferences.get("completed_dimensions", []))
    consumed_reply_ids = set(preferences.get("consumed_reply_ids", []))
    turn_count = int(preferences.get("turn_count", 0))

    if primary_intent == "alojamiento":
        options = [
            ("sumar_comida", AraMessages.get("reply_sumar_comida_label"), AraMessages.get("reply_sumar_comida_value"), "comida"),
            ("sumar_naturaleza", AraMessages.get("reply_sumar_naturaleza_label"), AraMessages.get("reply_sumar_naturaleza_value"), "naturaleza"),
            ("poco_traslado", AraMessages.get("reply_poco_traslado_label"), AraMessages.get("reply_poco_traslado_value"), "poco_traslado"),
            ("algo_tranquilo", AraMessages.get("reply_algo_tranquilo_label"), AraMessages.get("reply_algo_tranquilo_value"), "tranquilo"),
        ]
    elif primary_intent == "gastronomia" and "gastronomia" in completed_dimensions:
        options = [
            ("sumar_naturaleza", AraMessages.get("reply_sumar_naturaleza_label"), AraMessages.get("reply_sumar_naturaleza_value"), "naturaleza"),
            ("sumar_cultura", AraMessages.get("reply_sumar_cultura_label"), AraMessages.get("reply_sumar_cultura_value"), "cultura"),
            ("sumar_descanso", AraMessages.get("reply_sumar_descanso_label"), AraMessages.get("reply_sumar_descanso_value"), "descanso"),
        ]
    elif primary_intent == "gastronomia" and specificity == "specific":
        options = [
            ("vista_lago", AraMessages.get("reply_vista_lago_label"), AraMessages.get("reply_vista_lago_value"), "vista"),
            ("mas_cercano", AraMessages.get("reply_mas_cercano_label"), AraMessages.get("reply_mas_cercano_value"), "cercano"),
            ("ambiente_familiar", AraMessages.get("reply_ambiente_familiar_label"), AraMessages.get("reply_ambiente_familiar_value"), "familiar"),
            ("rapido_y_simple", AraMessages.get("reply_rapido_y_simple_label"), AraMessages.get("reply_rapido_y_simple_value"), "rapido"),
        ]
    elif primary_intent == "gastronomia":
        options = [
            ("comida_local", AraMessages.get("reply_comida_local_label"), AraMessages.get("reply_comida_local_value"), "comida_local"),
            ("pizza", AraMessages.get("reply_pizza_label"), AraMessages.get("reply_pizza_value"), "pizza"),
            ("cafe", AraMessages.get("reply_cafe_label"), AraMessages.get("reply_cafe_value"), "cafe"),
            ("vista_lago", AraMessages.get("reply_vista_lago_label"), AraMessages.get("reply_vista_lago_broad_value"), "vista"),
        ]
    elif primary_intent == "naturaleza" and specificity == "specific":
        options = [
            ("mas_cercano", AraMessages.get("reply_mas_cercano_label"), AraMessages.get("reply_mas_cercano_value"), "cercano"),
            ("baja_dificultad", AraMessages.get("reply_baja_dificultad_label"), AraMessages.get("reply_baja_dificultad_value"), "baja_dificultad"),
            ("mejor_horario", AraMessages.get("reply_mejor_horario_label"), AraMessages.get("reply_mejor_horario_value"), "mejor_horario"),
            ("combinar_comida", AraMessages.get("reply_combinar_comida_label"), AraMessages.get("reply_combinar_comida_value"), "comida"),
        ]
    elif primary_intent == "naturaleza":
        options = [
            ("senderos", AraMessages.get("reply_senderos_label"), AraMessages.get("reply_senderos_value"), "sendero"),
            ("miradores", AraMessages.get("reply_miradores_label"), AraMessages.get("reply_miradores_value"), "mirador"),
            ("lagos", AraMessages.get("reply_lagos_label"), AraMessages.get("reply_lagos_value"), "lago"),
            ("aire_libre", AraMessages.get("reply_aire_libre_label"), AraMessages.get("reply_aire_libre_value"), "aire_libre"),
        ]
    elif primary_intent == "cultura":
        options = [
            ("museos", AraMessages.get("reply_museos_label"), AraMessages.get("reply_museos_value"), "museos"),
            ("mapuche", AraMessages.get("reply_mapuche_label"), AraMessages.get("reply_mapuche_value"), "mapuche"),
            ("artesanias", AraMessages.get("reply_artesanias_label"), AraMessages.get("reply_artesanias_value"), "artesanias"),
            ("historia", AraMessages.get("reply_historia_label"), AraMessages.get("reply_historia_value"), "historia"),
        ]
    elif primary_intent == "descanso":
        options = [
            ("termas", AraMessages.get("reply_termas_label"), AraMessages.get("reply_termas_value"), "termas"),
            ("tranquilo", AraMessages.get("reply_tranquilo_label"), AraMessages.get("reply_tranquilo_value"), "tranquilo"),
            ("naturaleza_suave", AraMessages.get("reply_naturaleza_suave_label"), AraMessages.get("reply_naturaleza_suave_value"), "naturaleza_suave"),
            ("poco_traslado", AraMessages.get("reply_poco_traslado_label"), AraMessages.get("reply_poco_traslado_value"), "poco_traslado"),
        ]
    else:
        options = [
            ("naturaleza", AraMessages.get("reply_naturaleza_label"), AraMessages.get("reply_naturaleza_value"), "naturaleza"),
            ("gastronomia", AraMessages.get("reply_gastronomia_label"), AraMessages.get("reply_gastronomia_value"), "gastronomia"),
            ("cultura", AraMessages.get("reply_cultura_label"), AraMessages.get("reply_cultura_value"), "cultura"),
            ("descanso", AraMessages.get("reply_descanso_label"), AraMessages.get("reply_descanso_value"), "descanso"),
        ]

    if turn_count >= 2 and primary_intent not in {"gastronomia", "alojamiento"}:
        options = options + [
            ("ver_opciones", AraMessages.get("reply_ver_opciones_label"), AraMessages.get("reply_ver_opciones_value"), "ver_opciones"),
            ("ajustar_cercania", AraMessages.get("reply_ajustar_cercania_label"), AraMessages.get("reply_ajustar_cercania_value"), "cercano"),
            ("ajustar_ritmo", AraMessages.get("reply_ajustar_ritmo_label"), AraMessages.get("reply_ajustar_ritmo_value"), "tranquilo"),
        ]

    replies = [
        AraQuickReply(id=reply_id, label=label, value=value)
        for reply_id, label, value, tag in options
        if tag not in tag_set and reply_id not in consumed_reply_ids
    ]
    replies.append(
        AraQuickReply(
            id="hazlo_todo_tu",
            label=AraMessages.get("reply_hazlo_todo_tu_label"),
            value=AraMessages.get("reply_hazlo_todo_tu_value"),
            type="refinement",
        )
    )
    if should_offer_create_itinerary(preferences) and "crear_itinerario" not in consumed_reply_ids:
        replies.append(
            AraQuickReply(
                id="crear_itinerario",
                label=AraMessages.get("reply_crear_itinerario_label"),
                value=AraMessages.get("reply_crear_itinerario_value"),
                type="generate",
            )
        )
    return dedupe_quick_replies(replies)[:6]


def build_generate_request_message(preferences: dict[str, Any]) -> str:
    positive_preferences = preferences.get("positive_preferences") or preferences.get("tags") or []
    negative_constraints = preferences.get("negative_constraints") or []
    details: list[str] = []
    if positive_preferences:
        details.append(AraMessages.get("generate_detail_positive_prefix") + ", ".join(positive_preferences[:3]))
    if negative_constraints:
        details.append(AraMessages.get("generate_detail_negative_prefix") + ", ".join(negative_constraints[:3]))
    suffix = ""
    if details:
        suffix = AraMessages.get("generate_detail_prefix", details=AraMessages.get("generate_detail_joiner").join(details))
    if preferences.get("surprise_route_requested"):
        return AraMessages.get("generate_surprise") + suffix
    return AraMessages.get("generate_normal") + suffix


def build_assistant_message(
    intent: dict[str, Any],
    preferences: dict[str, Any],
    candidate_pois: list[POIResponse],
    *,
    is_first_turn: bool,
) -> str:
    primary_intent = intent.get("primary_intent", "exploracion")
    specificity = intent.get("specificity", "broad")
    tags = preferences.get("tags", [])
    completed_dimensions = set(preferences.get("completed_dimensions", []))

    if preferences.get("surprise_route_requested"):
        base = AraMessages.get("assistant_surprise_base")
        question = AraMessages.get("assistant_surprise_question")
    elif primary_intent == "alojamiento":
        base = AraMessages.get("assistant_alojamiento_base")
        question = AraMessages.get("assistant_alojamiento_question")
    elif primary_intent == "gastronomia" and "gastronomia" in completed_dimensions:
        base = AraMessages.get("assistant_gastronomia_completed_base")
        question = AraMessages.get("assistant_gastronomia_completed_question")
    elif primary_intent == "gastronomia" and specificity == "specific":
        base = AraMessages.get("assistant_gastronomia_specific_base")
        question = AraMessages.get("assistant_gastronomia_specific_question")
    elif primary_intent == "gastronomia":
        base = AraMessages.get("assistant_gastronomia_base")
        question = AraMessages.get("assistant_gastronomia_question")
    elif primary_intent == "naturaleza" and specificity == "specific":
        base = AraMessages.get("assistant_naturaleza_specific_base")
        question = AraMessages.get("assistant_naturaleza_specific_question")
    elif primary_intent == "naturaleza":
        base = AraMessages.get("assistant_naturaleza_base")
        question = AraMessages.get("assistant_naturaleza_question")
    elif primary_intent == "cultura":
        base = AraMessages.get("assistant_cultura_base")
        question = AraMessages.get("assistant_cultura_question")
    elif primary_intent == "descanso":
        base = AraMessages.get("assistant_descanso_base")
        question = AraMessages.get("assistant_descanso_question")
    else:
        base = AraMessages.get("assistant_exploracion_base")
        question = AraMessages.get("assistant_exploracion_question")

    if candidate_pois:
        base += AraMessages.get("assistant_poi_suffix")
    if tags:
        base += AraMessages.get("assistant_tags_suffix", tags=", ".join(tags))

    if preferences.get("auto_generate_requested"):
        return AraMessages.get("assistant_auto_generate_prefix", base=base)

    return f"{base}. {question}"


def build_replacement_quick_replies(
    alternatives: list[POIResponse],
    step_id: UUID,
) -> list[AraQuickReply]:
    replies = [
        AraQuickReply(
            id=f"usar_poi_{poi.id}",
            label=AraMessages.get("reply_usar_poi_prefix") + poi.name[:28],
            value=f"usar poi {poi.id} para step {step_id}",
            type="replace_step",
        )
        for poi in alternatives[:3]
    ]
    replies.append(
        AraQuickReply(
            id="buscar_mas_alternativas",
            label=AraMessages.get("reply_buscar_mas_alternativas_label"),
            value=AraMessages.get("reply_buscar_mas_alternativas_value"),
            type="refinement",
        )
    )
    return dedupe_quick_replies(replies)


def build_replacement_message(
    current_poi_name: str,
    alternatives: list[POIResponse],
) -> str:
    if not alternatives:
        return AraMessages.get("replacement_no_alternatives", poi_name=current_poi_name)

    names = ", ".join(poi.name for poi in alternatives[:3])
    return AraMessages.get("replacement_with_alternatives", poi_name=current_poi_name, names=names)


def compact_candidate_poi(
    poi: POIResponse,
    *,
    replacement_step_id: UUID | None = None,
) -> dict[str, Any]:
    payload = {
        "id": str(poi.id),
        "name": poi.name,
        "description": poi.description,
        "category_ids": poi.category_ids,
        "latitude": poi.latitude,
        "longitude": poi.longitude,
        "multimedia_urls": poi.multimedia_urls,
        "distance_meters": poi.distance_meters,
        "opening_hours_text": poi.opening_hours_text,
        "visit_rules": poi.visit_rules,
    }
    if replacement_step_id is not None:
        payload["action_value"] = f"usar poi {poi.id} para step {replacement_step_id}"
    else:
        payload["action_value"] = f"seleccionar poi {poi.id}"
    return payload


def compact_candidate_pois(
    pois: list[POIResponse],
    *,
    replacement_step_id: UUID | None = None,
) -> list[dict[str, Any]]:
    return [
        compact_candidate_poi(poi, replacement_step_id=replacement_step_id)
        for poi in pois[:8]
    ]


def build_refined_query(
    initial_query: str,
    messages: list[str],
    intent: dict[str, Any] | None,
    preferences: dict[str, Any] | None,
) -> str:
    safe_preferences = preferences or {}
    trip_draft = safe_preferences.get("trip_draft") or {}
    return (
        f"Intención inicial: {initial_query}\n"
        f"Mensajes de refinamiento: {' | '.join(messages[-8:])}\n"
        f"Intención detectada: {intent or {}}\n"
        "Borrador estructurado del viaje (fuente principal para alcance por día, destino, alojamiento, comidas y clima):\n"
        f"{json.dumps(trip_draft, ensure_ascii=False, sort_keys=True)}\n"
        "Regla de destino explícito: si trip_draft.destination_scope.strict=true, el usuario eligió un destino concreto "
        "y debes respetarlo aunque existan zonas turísticas más populares cerca. No sustituyas Freire, Cunco, Curacautín "
        "u otra comuna por Pucón/Villarrica/Temuco salvo que el usuario haya pedido ampliar la búsqueda. Si hay pocos "
        "lugares disponibles, usa menos paradas útiles o explica la limitación; no inventes ni rellenes con comunas no pedidas.\n"
        "Reglas de alcance: preferencias con scope=unspecified se ubican automáticamente en el mejor día/slot; "
        "scope=day o slot se respeta en ese día; scope=all_days solo se repite si el usuario lo pidió explícitamente; "
        "scope=entire_trip aplica como base del viaje. Usa lodging_plan, meal_plan y activity_plan como planes estructurados; "
        "selected_pois.locked=false significa que el POI está elegido como preferencia flexible y puedes ubicarlo en el mejor momento. "
        "weather_policy.overrides con allow_bad_weather permiten outdoor aunque haya lluvia si el usuario lo pidió.\n"
        "Si surprise_route_requested=true o route_balance_mode=surprise_balanced, crea una ruta balanceada desde cero: "
        "no uses solo la última categoría conversada; combina naturaleza, cultura, gastronomía y descanso según disponibilidad.\n"
        f"Preferencias positivas detectadas: {safe_preferences.get('positive_preferences', [])}\n"
        f"Restricciones negativas activas: {compact_constraints(safe_preferences.get('negative_constraints', []))}\n"
        f"Tags acumulados: {safe_preferences.get('tags', [])}\n"
        f"Dimensiones completadas: {safe_preferences.get('completed_dimensions', [])}"
    )
