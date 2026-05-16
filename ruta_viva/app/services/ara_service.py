from __future__ import annotations

import re
from datetime import date
from typing import Any
from uuid import UUID

from app.schemas.ara import AraQuickReply
from app.schemas.poi import POIResponse

FOOD_TERMS = (
    "comer",
    "comida",
    "restaurant",
    "restaurante",
    "pizza",
    "pizzería",
    "pizzeria",
    "café",
    "cafe",
    "gastronomía",
    "gastronomia",
    "almorzar",
    "cenar",
)
NATURE_TERMS = (
    "naturaleza",
    "sendero",
    "trekking",
    "mirador",
    "lago",
    "volcán",
    "volcan",
    "playa",
    "parque",
    "cascada",
    "terma",
    "outdoor",
)
CULTURE_TERMS = ("museo", "cultura", "historia", "mapuche", "artesanía", "artesania", "feria")
REST_TERMS = ("descansar", "relajo", "relajar", "termas", "spa", "bienestar", "tranquilo", "tranquila")
ADVENTURE_TERMS = ("aventura", "rafting", "kayak", "canopy", "bicicleta", "mtb", "esquí", "esqui")
LODGING_TERMS = ("alojamiento", "hotel", "hostal", "cabaña", "cabana", "dormir")

LOCATION_PATTERN = re.compile(r"\b(?:en|a|por|cerca de)\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñÁÉÍÓÚÑ-]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñÁÉÍÓÚÑ-]+)?)")


class AraConversationService:
    def analyze_message(self, message: str, previous_intent: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized = message.lower()
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

        location_match = LOCATION_PATTERN.search(message)
        locations = list(previous_intent.get("locations", [])) if previous_intent else []
        if location_match:
            location = location_match.group(1).strip()
            if location not in locations:
                locations.append(location)

        return {
            "intents": intents,
            "primary_intent": intents[0],
            "locations": locations,
            "confidence": "rule_based",
        }

    def merge_preferences(
        self,
        message: str,
        previous_preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        preferences = dict(previous_preferences or {})
        normalized = message.lower()
        tags = set(preferences.get("tags", []))

        keyword_to_tag = {
            "pizza": "pizza",
            "artesanal": "artesanal",
            "vista": "vista",
            "lago": "lago",
            "familiar": "familiar",
            "rápido": "rapido",
            "rapido": "rapido",
            "tranquilo": "tranquilo",
            "turístico": "turistico",
            "turistico": "turistico",
            "sendero": "sendero",
            "mirador": "mirador",
            "terma": "termas",
            "mapuche": "mapuche",
        }
        for keyword, tag in keyword_to_tag.items():
            if keyword in normalized:
                tags.add(tag)

        if "hazlo todo" in normalized or "hazlo tú" in normalized or "hazlo tu" in normalized:
            preferences["auto_generate_requested"] = True

        preferences["tags"] = sorted(tags)
        return preferences

    def build_quick_replies(self, intent: dict[str, Any], preferences: dict[str, Any]) -> list[AraQuickReply]:
        primary_intent = intent.get("primary_intent", "exploracion")
        tag_set = set(preferences.get("tags", []))

        if primary_intent == "gastronomia":
            options = [
                ("pizza_artesanal", "Pizza artesanal", "Prefiero pizza artesanal"),
                ("vista_lago", "Vista al lago", "Quiero algo con vista al lago"),
                ("ambiente_familiar", "Ambiente familiar", "Busco ambiente familiar"),
                ("algo_rapido", "Algo rápido", "Prefiero algo rápido"),
            ]
        elif primary_intent == "naturaleza":
            options = [
                ("senderos", "Senderos", "Quiero senderos"),
                ("miradores", "Miradores", "Quiero miradores"),
                ("lagos", "Lagos", "Quiero visitar lagos"),
                ("aire_libre", "Aire libre", "Quiero actividades al aire libre"),
            ]
        elif primary_intent == "cultura":
            options = [
                ("museos", "Museos", "Quiero museos"),
                ("mapuche", "Cultura mapuche", "Quiero cultura mapuche"),
                ("artesanias", "Artesanías", "Quiero artesanías"),
                ("historia", "Historia local", "Quiero historia local"),
            ]
        elif primary_intent == "descanso":
            options = [
                ("termas", "Termas", "Quiero termas"),
                ("tranquilo", "Algo tranquilo", "Busco algo tranquilo"),
                ("naturaleza_suave", "Naturaleza suave", "Quiero naturaleza suave"),
                ("poco_traslado", "Poco traslado", "Prefiero poco traslado"),
            ]
        else:
            options = [
                ("naturaleza", "Naturaleza", "Quiero naturaleza"),
                ("gastronomia", "Gastronomía", "Quiero gastronomía"),
                ("cultura", "Cultura", "Quiero cultura"),
                ("relajo", "Relajo", "Quiero algo tranquilo"),
            ]

        replies = [
            AraQuickReply(id=reply_id, label=label, value=value)
            for reply_id, label, value in options
            if reply_id not in tag_set
        ]
        replies.append(
            AraQuickReply(
                id="hazlo_todo_tu",
                label="Hazlo todo tú",
                value="Hazlo todo tú",
                type="generate",
            )
        )
        return replies[:5]

    def build_assistant_message(
        self,
        intent: dict[str, Any],
        preferences: dict[str, Any],
        candidate_pois: list[POIResponse],
        *,
        is_first_turn: bool,
    ) -> str:
        primary_intent = intent.get("primary_intent", "exploracion")
        tags = preferences.get("tags", [])
        poi_names = [poi.nombre for poi in candidate_pois[:3]]

        if primary_intent == "gastronomia":
            base = "Encontré opciones relacionadas con comida y panoramas cercanos"
            question = "¿Prefieres algo más tranquilo, turístico, familiar o rápido?"
        elif primary_intent == "naturaleza":
            base = "Detecté que buscas naturaleza y puedo priorizar experiencias al aire libre"
            question = "¿Te interesan más senderos, miradores, lagos o actividades suaves?"
        elif primary_intent == "cultura":
            base = "Puedo orientar el recorrido hacia cultura local, historia y experiencias patrimoniales"
            question = "¿Quieres algo más histórico, mapuche, artesanal o urbano?"
        elif primary_intent == "descanso":
            base = "Puedo armar algo más relajado, con menos traslados y mejores pausas"
            question = "¿Quieres termas, naturaleza suave o una ruta tranquila con comida?"
        else:
            base = "Ya empecé a entender tu intención de viaje"
            question = "¿Qué tipo de experiencia quieres priorizar: naturaleza, comida, cultura o descanso?"

        if poi_names:
            base += f". Algunas opciones que aparecen en el contexto son: {', '.join(poi_names)}"
        if tags:
            base += f". También tomaré en cuenta: {', '.join(tags)}"

        if preferences.get("auto_generate_requested"):
            return f"Perfecto, puedo encargarme de todo con lo que ya me dijiste. {base}. Generaré una ruta optimizada."

        prefix = "Perfecto. " if not is_first_turn else ""
        return f"{prefix}{base}. {question}"

    def compact_candidate_pois(self, pois: list[POIResponse]) -> list[dict[str, Any]]:
        return [
            {
                "id": str(poi.id),
                "nombre": poi.nombre,
                "category_ids": poi.category_ids,
                "distancia_metros": poi.distancia_metros,
            }
            for poi in pois[:8]
        ]

    def build_refined_query(
        self,
        initial_query: str,
        messages: list[str],
        intent: dict[str, Any] | None,
        preferences: dict[str, Any] | None,
    ) -> str:
        return (
            f"Intención inicial: {initial_query}\n"
            f"Mensajes de refinamiento: {' | '.join(messages[-8:])}\n"
            f"Intención detectada: {intent or {}}\n"
            f"Preferencias detectadas: {preferences or {}}"
        )


_ara_conversation_service: AraConversationService | None = None


def get_ara_conversation_service() -> AraConversationService:
    global _ara_conversation_service
    if _ara_conversation_service is None:
        _ara_conversation_service = AraConversationService()
    return _ara_conversation_service
