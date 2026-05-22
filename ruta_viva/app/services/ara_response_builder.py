from __future__ import annotations

import json
from typing import Any
from uuid import UUID

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
            ("sumar_comida", "Sumar comida", "Agrega una pausa para comer", "comida"),
            ("sumar_naturaleza", "Sumar naturaleza", "Agrega naturaleza al viaje", "naturaleza"),
            ("poco_traslado", "Poco traslado", "Prefiero poco traslado", "poco_traslado"),
            ("algo_tranquilo", "Algo tranquilo", "Prefiero algo tranquilo", "tranquilo"),
        ]
    elif primary_intent == "gastronomia" and "gastronomia" in completed_dimensions:
        options = [
            ("sumar_naturaleza", "Sumar naturaleza", "Agrega naturaleza al viaje", "naturaleza"),
            ("sumar_cultura", "Sumar cultura", "Agrega cultura local al viaje", "cultura"),
            ("sumar_descanso", "Sumar descanso", "Agrega una actividad tranquila", "descanso"),
        ]
    elif primary_intent == "gastronomia" and specificity == "specific":
        options = [
            ("vista_lago", "Con vista", "Prefiero una opción con vista", "vista"),
            ("mas_cercano", "Más cercano", "Prioriza lo más cercano", "cercano"),
            ("ambiente_familiar", "Ambiente familiar", "Busco ambiente familiar", "familiar"),
            ("rapido_y_simple", "Rápido y simple", "Prefiero algo rápido", "rapido"),
        ]
    elif primary_intent == "gastronomia":
        options = [
            ("comida_local", "Comida local", "Quiero comida local", "comida_local"),
            ("pizza", "Pizza", "Quiero pizza", "pizza"),
            ("cafe", "Café", "Quiero un café", "cafe"),
            ("vista_lago", "Con vista", "Quiero algo con vista", "vista"),
        ]
    elif primary_intent == "naturaleza" and specificity == "specific":
        options = [
            ("mas_cercano", "Más cercano", "Prioriza lo más cercano", "cercano"),
            ("baja_dificultad", "Baja dificultad", "Prefiero baja dificultad", "baja_dificultad"),
            ("mejor_horario", "Mejor horario", "Prioriza el mejor horario", "mejor_horario"),
            ("combinar_comida", "Sumar comida", "Agrega una pausa para comer", "comida"),
        ]
    elif primary_intent == "naturaleza":
        options = [
            ("senderos", "Senderos", "Quiero senderos", "sendero"),
            ("miradores", "Miradores", "Quiero miradores", "mirador"),
            ("lagos", "Lagos", "Quiero visitar lagos", "lago"),
            ("aire_libre", "Aire libre", "Quiero actividades al aire libre", "aire_libre"),
        ]
    elif primary_intent == "cultura":
        options = [
            ("museos", "Museos", "Quiero museos", "museos"),
            ("mapuche", "Cultura mapuche", "Quiero cultura mapuche", "mapuche"),
            ("artesanias", "Artesanías", "Quiero artesanías", "artesanias"),
            ("historia", "Historia local", "Quiero historia local", "historia"),
        ]
    elif primary_intent == "descanso":
        options = [
            ("termas", "Termas", "Quiero termas", "termas"),
            ("tranquilo", "Algo tranquilo", "Busco algo tranquilo", "tranquilo"),
            ("naturaleza_suave", "Naturaleza suave", "Quiero naturaleza suave", "naturaleza_suave"),
            ("poco_traslado", "Poco traslado", "Prefiero poco traslado", "poco_traslado"),
        ]
    else:
        options = [
            ("naturaleza", "Naturaleza", "Quiero naturaleza", "naturaleza"),
            ("gastronomia", "Comida", "Quiero comida", "gastronomia"),
            ("cultura", "Cultura", "Quiero cultura", "cultura"),
            ("descanso", "Descanso", "Quiero algo tranquilo", "descanso"),
        ]

    if turn_count >= 2 and primary_intent not in {"gastronomia", "alojamiento"}:
        options = options + [
            ("ver_opciones", "Ver opciones", "Muéstrame opciones", "ver_opciones"),
            ("ajustar_cercania", "Más cercano", "Prioriza cercanía", "cercano"),
            ("ajustar_ritmo", "Más tranquilo", "Prefiero una ruta tranquila", "tranquilo"),
        ]

    replies = [
        AraQuickReply(id=reply_id, label=label, value=value)
        for reply_id, label, value, tag in options
        if tag not in tag_set and reply_id not in consumed_reply_ids
    ]
    replies.append(
        AraQuickReply(
            id="hazlo_todo_tu",
            label="Hazlo todo tú",
            value="Haz una ruta sorpresa equilibrada y completa con alojamiento, comidas y actividades",
            type="refinement",
        )
    )
    if should_offer_create_itinerary(preferences) and "crear_itinerario" not in consumed_reply_ids:
        replies.append(
            AraQuickReply(
                id="crear_itinerario",
                label="Crear itinerario",
                value="Crear itinerario con lo acordado",
                type="generate",
            )
        )
    return dedupe_quick_replies(replies)[:6]


def build_generate_request_message(preferences: dict[str, Any]) -> str:
    positive_preferences = preferences.get("positive_preferences") or preferences.get("tags") or []
    negative_constraints = preferences.get("negative_constraints") or []
    details: list[str] = []
    if positive_preferences:
        details.append("priorizaré " + ", ".join(positive_preferences[:3]))
    if negative_constraints:
        details.append("evitaré " + ", ".join(negative_constraints[:3]))
    suffix = f" Además, {', y '.join(details)}." if details else ""
    if preferences.get("surprise_route_requested"):
        return (
            "Listo, puedo armar una ruta sorpresa equilibrada con lo que ya conversamos. "
            "No la voy a limitar a una sola categoría: combinaré alojamiento, comidas, actividades, pausas "
            "y lugares cercanos según tus fechas y ubicación."
            f"{suffix}"
        )
    return (
        "Listo, puedo crear el itinerario con lo que ya acordamos. "
        "Usaré las fechas, ubicación, preferencias y lugares seleccionados para armar una ruta coherente y variada."
        f"{suffix}"
    )


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
        base = "Perfecto, puedo encargarme de equilibrar alojamiento, comidas y actividades"
        question = "Si quieres, puedo crear el itinerario con lo acordado o seguimos afinando algún detalle."
    elif primary_intent == "alojamiento":
        base = "Perfecto, buscaremos alojamiento como base del viaje"
        question = "Te dejo opciones visuales si hay alternativas; luego podemos sumar comidas y actividades cercanas."
    elif primary_intent == "gastronomia" and "gastronomia" in completed_dimensions:
        base = "Perfecto, dejamos la comida encaminada"
        question = "Ahora conviene equilibrar el viaje con naturaleza, cultura, descanso o alguna actividad distinta."
    elif primary_intent == "gastronomia" and specificity == "specific":
        base = "Perfecto, ya sé qué tipo de comida buscas"
        question = "Te dejo opciones en las tarjetas. Después podemos sumar actividades para que la ruta no quede centrada solo en comida."
    elif primary_intent == "gastronomia":
        base = "Perfecto, podemos buscar algo rico para comer"
        question = "¿Quieres comida local, pizza, café, vista o algo rápido?"
    elif primary_intent == "naturaleza" and specificity == "specific":
        base = "Perfecto, ya tengo una idea clara del panorama natural que buscas"
        question = "Puedo afinar por dificultad, horario, cercanía o combinarlo con una pausa para comer."
    elif primary_intent == "naturaleza":
        base = "Podemos armar una salida con naturaleza y buenos paisajes"
        question = "¿Te interesan más senderos, miradores, lagos o actividades suaves?"
    elif primary_intent == "cultura":
        base = "Podemos orientar el recorrido hacia cultura local, historia y patrimonio"
        question = "¿Quieres algo más histórico, mapuche, artesanal o urbano?"
    elif primary_intent == "descanso":
        base = "Puedo armar algo más relajado, con menos traslados y mejores pausas"
        question = "¿Quieres termas, naturaleza suave o una ruta tranquila con comida?"
    else:
        base = "Cuéntame qué tipo de experiencia te gustaría priorizar"
        question = "¿Qué tipo de experiencia quieres priorizar: naturaleza, comida, cultura o descanso?"

    if candidate_pois:
        base += ". Te dejo opciones visuales en las tarjetas"
    if tags:
        base += f". Tomaré en cuenta: {', '.join(tags)}"

    if preferences.get("auto_generate_requested"):
        return f"Perfecto, puedo encargarme de todo con una ruta equilibrada. {base}."

    return f"{base}. {question}"


def build_replacement_quick_replies(
    alternatives: list[POIResponse],
    step_id: UUID,
) -> list[AraQuickReply]:
    replies = [
        AraQuickReply(
            id=f"usar_poi_{poi.id}",
            label=f"Usar {poi.name[:28]}",
            value=f"usar poi {poi.id} para step {step_id}",
            type="replace_step",
        )
        for poi in alternatives[:3]
    ]
    replies.append(
        AraQuickReply(
            id="buscar_mas_alternativas",
            label="Buscar más alternativas",
            value="Busca más alternativas para esta parada",
            type="refinement",
        )
    )
    return dedupe_quick_replies(replies)


def build_replacement_message(
    current_poi_name: str,
    alternatives: list[POIResponse],
) -> str:
    if not alternatives:
        return (
            f"Entendí que quieres cambiar {current_poi_name}, pero todavía no encontré una alternativa sólida "
            "con el contexto disponible. Puedes decirme si prefieres algo más cercano, gastronómico, natural o tranquilo."
        )

    names = ", ".join(poi.name for poi in alternatives[:3])
    return (
        f"Entendí que quieres cambiar la parada {current_poi_name}. Encontré alternativas reales para reemplazarla: "
        f"{names}. Elige una opción o dime qué criterio priorizar: cercanía, tipo de experiencia, horario o ritmo del viaje."
    )


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
