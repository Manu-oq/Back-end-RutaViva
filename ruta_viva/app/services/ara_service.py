from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, timedelta
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
    "sopa",
    "sopas",
    "sopitas",
    "sopias",
    "carne",
    "carnes",
    "cazuela",
    "económico",
    "economico",
    "picada",
    "picadas",
)
SPECIFIC_FOOD_TERMS = (
    "pizza",
    "pizzería",
    "pizzeria",
    "café",
    "cafe",
    "sushi",
    "hamburguesa",
    "pastelería",
    "pasteleria",
    "mariscos",
    "marisco",
    "comida local",
    "sopa",
    "sopas",
    "sopias",
    "carne",
    "carnes",
    "cazuela",
)
FOOD_COMPLETION_TAGS = {"pizza", "cafe", "comida_local", "artesanal", "rapido"}
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
    "aire libre",
)
CULTURE_TERMS = ("museo", "cultura", "historia", "mapuche", "artesanía", "artesania", "feria")
REST_TERMS = ("descansar", "relajo", "relajar", "termas", "spa", "bienestar", "tranquilo", "tranquila")
ADVENTURE_TERMS = ("aventura", "rafting", "kayak", "canopy", "bicicleta", "mtb", "esquí", "esqui")
LODGING_TERMS = ("alojamiento", "hotel", "hostal", "hostel", "cabaña", "cabana", "dormir", "hospedaje", "camping")
GENERATE_TERMS = (
    "haz el itinerario",
    "hacer el itinerario",
    "crear itinerario",
    "crea itinerario",
    "crea el itinerario",
    "crear itinerario con lo acordado",
    "itinerario con lo acordado",
    "arma la ruta",
    "armame la ruta",
    "genera el itinerario",
    "generar itinerario",
    "genera la ruta",
    "generar la ruta",
    "haz la ruta",
    "planificalo",
    "listo genera",
    "con lo que ya te di",
    "hazlo con lo que tenemos",
    "con lo que tenemos",
    "con lo acordado",
)
SURPRISE_ROUTE_TERMS = (
    "hazlo todo",
    "hazlo tu",
    "hazlo tú",
    "ruta sorpresa",
    "ruta equilibrada",
    "haz una ruta sorpresa",
    "haz una ruta sorpresa equilibrada",
    "haz una ruta sorpresa equilibrada y completa",
    "haz una ruta sorpresa equilibrada y completa con alojamiento, comidas y actividades",
    "arma todo",
    "decide tu",
    "decide tú",
)
RESET_TERMS = (
    "olvida eso",
    "olvidemos eso",
    "nuevo plan",
    "nuevo viaje",
    "empecemos de nuevo",
    "partamos de nuevo",
    "cambiemos el plan",
    "cambiar totalmente",
    "otra cosa",
    "algo totalmente distinto",
)
SHOW_OPTIONS_TERMS = ("muestrame opciones", "muéstrame opciones", "ver opciones", "que opciones", "qué opciones")
REFINEMENT_TERMS = (
    "quiero",
    "prefiero",
    "busco",
    "me gustaria",
    "me gustaría",
    "ponle",
    "agregale",
    "agrégale",
    "prioriza",
    "dejalo",
    "déjalo",
    "hazlo mas",
    "hazlo más",
    "necesito una ruta",
    "me tinca",
    "vamos con",
    "sumar",
    "suma",
    "agrega",
    "agregar",
)
FREE_QUESTION_TERMS = (
    "auto",
    "vehiculo",
    "vehículo",
    "bici",
    "caminando",
    "caminar",
    "lejos",
    "distancia",
    "precio",
    "entrada",
    "ticket",
    "horario",
    "abierto",
    "cerrado",
    "clima",
    "lluvia",
    "frio",
    "frío",
    "calor",
    "niños",
    "ninos",
    "familia",
    "adulto mayor",
    "dificultad",
    "dificil",
    "difícil",
    "facil",
    "fácil",
    "peligroso",
    "seguro",
    "estacionamiento",
    "baño",
    "bano",
    "acceso",
    "camino",
    "ripio",
    "que significa",
    "qué significa",
    "a que te refieres",
    "a qué te refieres",
    "se puede",
    "conviene",
    "sirve",
)
TYPO_REPLACEMENTS = {
    "kiero": "quiero",
    "qiero": "quiero",
    "keremos": "queremos",
    "qeremos": "queremos",
    "gustaria": "me gustaria",
    "vehiculo": "vehiculo",
    "dificil": "dificil",
    "ninos": "ninos",
}

LOCATION_PATTERN = re.compile(r"\b(?:en|a|por|cerca de)\s+([A-ZÁÉÍÓÚÑ][\wáéíóúñÁÉÍÓÚÑ-]+(?:\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñÁÉÍÓÚÑ-]+)?)")
UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
ITINERARY_ID_PATTERN = re.compile(r"itinerary[_\s-]*id\s*[:=]?\s*(?P<id>[0-9a-fA-F-]{36})", re.IGNORECASE)
STEP_ID_PATTERN = re.compile(r"step[_\s-]*id\s*[:=]?\s*(?P<id>[0-9a-fA-F-]{36})", re.IGNORECASE)
USE_POI_PATTERN = re.compile(
    r"usar\s+poi\s+(?P<poi_id>[0-9a-fA-F-]{36})(?:\s+para\s+step\s+(?P<step_id>[0-9a-fA-F-]{36}))?",
    re.IGNORECASE,
)
SELECT_POI_PATTERN = re.compile(
    r"(?:seleccionar|elegir|usar|quiero ir a)\s+poi\s+(?P<poi_id>[0-9a-fA-F-]{36})",
    re.IGNORECASE,
)
WEEKDAY_NAMES = {
    0: "lunes",
    1: "martes",
    2: "miércoles",
    3: "jueves",
    4: "viernes",
    5: "sábado",
    6: "domingo",
}
WEEKDAY_ALIASES = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "miércoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}
DAY_ORDINAL_ALIASES = {
    "primer dia": 1,
    "primer día": 1,
    "dia 1": 1,
    "día 1": 1,
    "segundo dia": 2,
    "segundo día": 2,
    "dia 2": 2,
    "día 2": 2,
    "tercer dia": 3,
    "tercer día": 3,
    "dia 3": 3,
    "día 3": 3,
    "cuarto dia": 4,
    "cuarto día": 4,
    "dia 4": 4,
    "día 4": 4,
    "quinto dia": 5,
    "quinto día": 5,
    "dia 5": 5,
    "día 5": 5,
    "sexto dia": 6,
    "sexto día": 6,
    "dia 6": 6,
    "día 6": 6,
    "septimo dia": 7,
    "séptimo día": 7,
    "dia 7": 7,
    "día 7": 7,
}
KNOWN_DESTINATION_NAMES = (
    "pucon",
    "pucón",
    "villarrica",
    "lican ray",
    "licán ray",
    "caburgua",
    "curarrehue",
    "temuco",
    "melipeuco",
    "conguillio",
    "conguillío",
    "malalcahuello",
    "lonquimay",
    "angol",
    "santiago",
    "freire",
    "padre las casas",
    "nueva imperial",
    "carahue",
    "saavedra",
    "puerto saavedra",
    "teodoro schmidt",
    "toltén",
    "tolten",
    "gorbea",
    "pitrufquén",
    "pitrufquen",
    "loncoche",
    "lautaro",
    "perquenco",
    "galvarino",
    "cholchol",
    "vilcún",
    "vilcun",
    "cunco",
    "curacautín",
    "curacautin",
    "victoria",
    "traiguén",
    "traiguen",
    "lumaco",
    "purén",
    "puren",
    "renaico",
    "ercilla",
    "collipulli",
    "los sauces",
    "curarrehue",
    "araucania",
    "araucanía",
)


class AraConversationService:
    def normalize_message(self, message: str) -> str:
        normalized = message.lower().strip()
        normalized = "".join(
            character
            for character in unicodedata.normalize("NFD", normalized)
            if unicodedata.category(character) != "Mn"
        )
        normalized = re.sub(r"\s+", " ", normalized)
        for typo, replacement in TYPO_REPLACEMENTS.items():
            normalized = re.sub(rf"\b{re.escape(typo)}\b", replacement, normalized)
        return normalized

    def classify_turn(
        self,
        message: str,
        previous_intent: dict[str, Any] | None = None,
        previous_preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = self.normalize_message(message)

        if self.extract_replace_selection(message, previous_preferences) is not None:
            return {"turn_type": "replace_step", "topic": "replace_step", "confidence": "high_rule_based"}
        if self.extract_candidate_selection(message) is not None:
            return {"turn_type": "candidate_selection", "topic": "poi_selection", "confidence": "high_rule_based"}
        if self.extract_itinerary_step_context(message) is not None:
            return {"turn_type": "replace_step", "topic": "replace_step", "confidence": "high_rule_based"}
        if any(term in normalized for term in RESET_TERMS):
            return {"turn_type": "reset_or_new_trip", "topic": "new_trip", "confidence": "high_rule_based"}
        if any(term in normalized for term in GENERATE_TERMS):
            return {"turn_type": "generate_request", "topic": "generation", "confidence": "high_rule_based"}
        if any(term in normalized for term in SURPRISE_ROUTE_TERMS):
            return {"turn_type": "refinement", "topic": "surprise_route", "confidence": "high_rule_based"}
        if any(term in normalized for term in SHOW_OPTIONS_TERMS):
            return {"turn_type": "show_options", "topic": "options", "confidence": "high_rule_based"}

        topic = self._detect_question_topic(normalized)
        has_refinement = any(term in normalized for term in REFINEMENT_TERMS)
        has_negative_preference = any(term in normalized for term in ("no quiero", "ni me hables", "evita", "evitar", "no me gusta"))
        has_free_question = topic != "general" or normalized.startswith(("que ", "como ", "cuando ", "donde ", "por que "))

        # Los deseos explícitos ganan a las dudas logísticas, pero las negaciones
        # se procesan como refinement con restricciones negativas, no como
        # preferencia positiva.
        if has_refinement or has_negative_preference:
            return {"turn_type": "refinement", "topic": self._detect_refinement_topic(normalized), "confidence": "rule_based"}
        if has_free_question:
            return {"turn_type": "free_question", "topic": topic, "confidence": "rule_based"}

        if previous_preferences and previous_preferences.get("conversation_mode") == "post_generation":
            return {"turn_type": "free_question", "topic": "poi_detail", "confidence": "contextual_rule_based"}

        return {"turn_type": "general_chat", "topic": "general", "confidence": "low_rule_based"}

    def analyze_message(self, message: str, previous_intent: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized = self.normalize_message(message)
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

        specificity = "specific" if self._has_specific_niche(normalized) else "broad"
        if any(term in normalized for term in ("no sé", "no se", "no tengo claro", "algo", "recomiéndame", "recomiendame")):
            specificity = "broad"

        return {
            "intents": intents,
            "primary_intent": intents[0],
            "locations": locations,
            "specificity": specificity,
            "confidence": "rule_based",
        }

    def merge_preferences(
        self,
        message: str,
        previous_preferences: dict[str, Any] | None = None,
        turn_classification: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        preferences = dict(previous_preferences or {})
        normalized = self.normalize_message(message)
        tags = set(preferences.get("tags", []))
        positive_preferences = set(preferences.get("positive_preferences", []))
        negative_constraints = set(preferences.get("negative_constraints", []))
        consumed_reply_ids = set(preferences.get("consumed_reply_ids", []))
        last_added_tags: list[str] = []

        for constraint in self._extract_negative_constraints(normalized):
            negative_constraints.add(constraint)

        for preference in self._extract_positive_preferences(normalized):
            if not self._conflicts_with_negative_constraints(preference, negative_constraints):
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
            if keyword in normalized and tag not in tags and not self._is_keyword_negated(normalized, keyword):
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
        preferences["negative_constraints"] = self.compact_constraints(sorted(negative_constraints))
        preferences["last_added_tags"] = last_added_tags
        preferences["consumed_reply_ids"] = sorted(consumed_reply_ids)
        preferences["turn_count"] = int(preferences.get("turn_count", 0)) + 1
        preferences["route_ready_score"] = self._estimate_route_ready_score(preferences)
        if turn_classification:
            preferences["last_turn_type"] = turn_classification.get("turn_type")
            preferences["last_question_topic"] = turn_classification.get("topic")
            preferences["conversation_mode"] = self._conversation_mode_for_turn(turn_classification.get("turn_type"))
        return preferences

    def ensure_trip_draft(
        self,
        preferences: dict[str, Any],
        *,
        start_date: date,
        end_date: date,
        payload_lat: float | None = None,
        payload_lon: float | None = None,
    ) -> dict[str, Any]:
        updated = dict(preferences)
        existing = dict(updated.get("trip_draft") or {})
        existing["schema_version"] = 2
        trip_days = self._build_trip_days(start_date, end_date, existing.get("trip_days") or [])
        existing["trip_days"] = trip_days
        existing.setdefault("origin_zones", [])
        existing.setdefault("destination_zones", [])
        existing.setdefault(
            "search_center",
            {
                "lat": payload_lat,
                "lon": payload_lon,
                "source": "payload" if payload_lat is not None and payload_lon is not None else "unknown",
                "label": None,
            },
        )
        existing.setdefault(
            "user_current_location",
            {
                "lat": payload_lat,
                "lon": payload_lon,
                "source": "payload" if payload_lat is not None and payload_lon is not None else "unknown",
            },
        )
        existing.setdefault(
            "global_preferences",
            {
                "meal_preferences": [],
                "activity_preferences": [],
                "lodging_preferences": [],
            },
        )
        existing.setdefault("lodging_plan", [])
        existing.setdefault("meal_plan", [])
        existing.setdefault("activity_plan", [])
        existing.setdefault("selected_pois", [])
        existing.setdefault("weather_policy", {"default": "adapt_to_weather", "overrides": []})
        updated["trip_draft"] = existing
        return updated

    def update_trip_draft_from_message(
        self,
        message: str,
        preferences: dict[str, Any],
        intent: dict[str, Any],
        *,
        start_date: date,
        end_date: date,
        payload_lat: float | None = None,
        payload_lon: float | None = None,
    ) -> dict[str, Any]:
        updated = self.ensure_trip_draft(
            preferences,
            start_date=start_date,
            end_date=end_date,
            payload_lat=payload_lat,
            payload_lon=payload_lon,
        )
        draft = dict(updated["trip_draft"])
        normalized = self.normalize_message(message)

        route_locations = self.extract_route_locations(message)
        origin_zones = set(draft.get("origin_zones") or [])
        origin_zones.update(route_locations["origins"])
        draft["origin_zones"] = sorted(origin_zones)

        destination_zones = set(draft.get("destination_zones") or [])
        destination_zones.update(route_locations["destinations"])
        draft["destination_zones"] = sorted(destination_zones)

        day_index = self._detect_day_index(normalized, start_date, end_date)
        day_segments = self._extract_day_segments(normalized, start_date, end_date)
        meal_slot = self._detect_meal_slot(normalized)
        repeat_scope = self._detect_repeat_scope(normalized)
        primary_intent = str(intent.get("primary_intent") or "exploracion")
        draft = self._apply_base_areas_from_message(draft, normalized, start_date, end_date)

        if primary_intent == "gastronomia" or any(term in normalized for term in FOOD_TERMS + SPECIFIC_FOOD_TERMS):
            segments_with_food = [
                (segment_day_index, segment)
                for segment_day_index, segment in day_segments
                if any(term in segment for term in FOOD_TERMS + SPECIFIC_FOOD_TERMS)
            ]
            if segments_with_food:
                for segment_day_index, segment in segments_with_food:
                    segment_meal_slot = self._detect_meal_slot(segment)
                    entry = {
                        "value": self._extract_food_preference(segment),
                        "scope": "slot" if segment_meal_slot else "day",
                        "day_index": segment_day_index,
                        "meal_slot": segment_meal_slot,
                        "strength": "preference",
                        "locked": False,
                        "source": "message",
                    }
                    draft = self._add_preference_to_trip_draft(
                        draft,
                        entry,
                        day_index=segment_day_index,
                        bucket="meal_preferences",
                    )
                    draft = self._add_plan_entry(draft, "meal_plan", entry)
            else:
                preference_value = self._extract_food_preference(normalized)
                scope = self._scope_from_context(day_index=day_index, slot=meal_slot, repeat_scope=repeat_scope)
                entry = {
                    "value": preference_value,
                    "scope": scope,
                    "day_index": day_index,
                    "meal_slot": meal_slot,
                    "strength": "preference",
                    "locked": False,
                    "source": "message",
                }
                draft = self._add_preference_to_trip_draft(draft, entry, day_index=day_index, bucket="meal_preferences")
                draft = self._add_plan_entry(draft, "meal_plan", entry)

        if primary_intent in {"naturaleza", "cultura", "descanso", "aventura"} or any(
            term in normalized for term in NATURE_TERMS + CULTURE_TERMS + REST_TERMS + ADVENTURE_TERMS
        ):
            segments_with_activity = [
                (segment_day_index, segment)
                for segment_day_index, segment in day_segments
                if any(term in segment for term in NATURE_TERMS + CULTURE_TERMS + REST_TERMS + ADVENTURE_TERMS)
            ]
            if segments_with_activity:
                for segment_day_index, segment in segments_with_activity:
                    activity_slot = self._detect_activity_slot(segment)
                    entry = {
                        "value": self._extract_activity_preference(segment, primary_intent),
                        "scope": "slot" if activity_slot else "day",
                        "day_index": segment_day_index,
                        "slot": activity_slot,
                        "strength": "preference",
                        "locked": False,
                        "source": "message",
                    }
                    draft = self._add_preference_to_trip_draft(
                        draft,
                        entry,
                        day_index=segment_day_index,
                        bucket="activity_preferences",
                    )
                    draft = self._add_plan_entry(draft, "activity_plan", entry)
            else:
                activity_value = self._extract_activity_preference(normalized, primary_intent)
                activity_slot = self._detect_activity_slot(normalized)
                scope = self._scope_from_context(day_index=day_index, slot=activity_slot, repeat_scope=repeat_scope)
                entry = {
                    "value": activity_value,
                    "scope": scope,
                    "day_index": day_index,
                    "slot": activity_slot,
                    "strength": "preference",
                    "locked": False,
                    "source": "message",
                }
                draft = self._add_preference_to_trip_draft(draft, entry, day_index=day_index, bucket="activity_preferences")
                draft = self._add_plan_entry(draft, "activity_plan", entry)

        if primary_intent == "alojamiento" or any(term in normalized for term in LODGING_TERMS):
            lodging_value = self._extract_lodging_preference(normalized)
            lodging_scope = "day" if day_index else "entire_trip"
            entry = {
                "value": lodging_value,
                "scope": lodging_scope,
                "day_index": day_index,
                "from_day": day_index or 1,
                "to_day": day_index or len(draft.get("trip_days") or [1]),
                "base_area": self._first_destination_in_text(normalized),
                "strength": "preference",
                "locked": False,
                "source": "message",
            }
            draft = self._add_preference_to_trip_draft(draft, entry, day_index=day_index, bucket="lodging_preferences")
            draft = self._add_plan_entry(draft, "lodging_plan", entry)

        if self._has_weather_override(normalized):
            policy = dict(draft.get("weather_policy") or {"default": "adapt_to_weather", "overrides": []})
            overrides = list(policy.get("overrides") or [])
            override = {
                "activity": self._extract_activity_preference(normalized, primary_intent),
                "policy": "allow_bad_weather",
                "source": "message",
            }
            if override not in overrides:
                overrides.append(override)
            policy["overrides"] = overrides
            draft["weather_policy"] = policy

        updated["trip_draft"] = draft
        updated["route_ready_score"] = self._estimate_route_ready_score(updated)
        return updated

    def apply_search_center(
        self,
        preferences: dict[str, Any],
        *,
        lat: float | None,
        lon: float | None,
        source: str,
        label: str | None,
    ) -> dict[str, Any]:
        updated = dict(preferences)
        draft = dict(updated.get("trip_draft") or {})
        draft["search_center"] = {
            "lat": lat,
            "lon": lon,
            "source": source,
            "label": label,
        }
        if label:
            zones = set(draft.get("destination_zones") or [])
            for zone in label.split(" / "):
                if zone:
                    zones.add(zone)
            draft["destination_zones"] = sorted(zones)
        updated["trip_draft"] = draft
        return updated

    def reset_trip_preferences(self, message: str) -> dict[str, Any]:
        turn_classification = {"turn_type": "reset_or_new_trip", "topic": "new_trip"}
        preferences = self.merge_preferences(message, previous_preferences={}, turn_classification=turn_classification)
        preferences["conversation_mode"] = "exploring"
        preferences["active_itinerary_id"] = None
        preferences["active_itinerary_poi_ids"] = []
        preferences["candidate_poi_ids"] = []
        return preferences

    def apply_memory_patch(
        self,
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

    def detect_destination_zones(self, message: str) -> list[str]:
        normalized = self.normalize_message(message)
        found: list[str] = []
        for name in KNOWN_DESTINATION_NAMES:
            normalized_name = self.normalize_message(name)
            if re.search(rf"\b{re.escape(normalized_name)}\b", normalized):
                display_name = self._destination_display_name(normalized_name)
                if display_name not in found:
                    found.append(display_name)
        return found

    def extract_route_locations(self, message: str) -> dict[str, list[str]]:
        normalized = self.normalize_message(message)
        all_zones = self.detect_destination_zones(message)
        origins: list[str] = []
        destinations: list[str] = []

        for zone in all_zones:
            zone_key = self.normalize_message(zone)
            if self._zone_has_origin_marker(normalized, zone_key):
                origins.append(zone)
            if self._zone_has_destination_marker(normalized, zone_key):
                destinations.append(zone)

        # Si hay zonas mencionadas pero ninguna tiene marcador explícito, en una
        # app turística conviene tratarlas como destino del viaje y no como GPS.
        if not destinations:
            destinations = [zone for zone in all_zones if zone not in origins]
        else:
            destinations = sorted(set(destinations) | {zone for zone in all_zones if zone not in origins})

        # Si el usuario dice "desde Santiago a Villarrica", Santiago no debe
        # contaminar destination_zones aunque sea reconocido en el futuro.
        destinations = [zone for zone in destinations if zone not in origins]
        return {"origins": origins, "destinations": destinations}

    def _zone_has_origin_marker(self, normalized: str, zone_key: str) -> bool:
        patterns = (
            rf"\bdesde\s+{re.escape(zone_key)}\b",
            rf"\bde\s+{re.escape(zone_key)}\s+(?:a|hacia|para)\b",
            rf"\bsalgo\s+(?:desde|de)\s+{re.escape(zone_key)}\b",
            rf"\bparto\s+(?:desde|de)\s+{re.escape(zone_key)}\b",
            rf"\bvengo\s+(?:desde|de)\s+{re.escape(zone_key)}\b",
            rf"\bestoy\s+en\s+{re.escape(zone_key)}\b",
        )
        return any(re.search(pattern, normalized) for pattern in patterns)

    def _zone_has_destination_marker(self, normalized: str, zone_key: str) -> bool:
        patterns = (
            rf"\b(?:a|hacia|para)\s+{re.escape(zone_key)}\b",
            rf"\b(?:ir|viajar|visitar|llegar|quedarme|quedarnos)\s+(?:a|en|por)\s+{re.escape(zone_key)}\b",
            rf"\b(?:zona de|cerca de|en)\s+{re.escape(zone_key)}\b",
        )
        return any(re.search(pattern, normalized) for pattern in patterns)

    def _first_destination_in_text(self, normalized: str) -> str | None:
        for name in KNOWN_DESTINATION_NAMES:
            normalized_name = self.normalize_message(name)
            if re.search(rf"\b{re.escape(normalized_name)}\b", normalized):
                return self._destination_display_name(normalized_name)
        return None

    def _destination_display_name(self, normalized_name: str) -> str:
        display_names = {
            "pucon": "Pucón",
            "villarrica": "Villarrica",
            "lican ray": "Lican Ray",
            "caburgua": "Caburgua",
            "curarrehue": "Curarrehue",
            "temuco": "Temuco",
            "melipeuco": "Melipeuco",
            "conguillio": "Parque Nacional Conguillío",
            "malalcahuello": "Malalcahuello",
            "lonquimay": "Lonquimay",
            "angol": "Angol",
            "santiago": "Santiago",
            "freire": "Freire",
            "padre las casas": "Padre Las Casas",
            "nueva imperial": "Nueva Imperial",
            "carahue": "Carahue",
            "saavedra": "Saavedra",
            "puerto saavedra": "Puerto Saavedra",
            "teodoro schmidt": "Teodoro Schmidt",
            "tolten": "Toltén",
            "gorbea": "Gorbea",
            "pitrufquen": "Pitrufquén",
            "loncoche": "Loncoche",
            "lautaro": "Lautaro",
            "perquenco": "Perquenco",
            "galvarino": "Galvarino",
            "cholchol": "Cholchol",
            "vilcun": "Vilcún",
            "cunco": "Cunco",
            "curacautin": "Curacautín",
            "victoria": "Victoria",
            "traiguen": "Traiguén",
            "lumaco": "Lumaco",
            "puren": "Purén",
            "renaico": "Renaico",
            "ercilla": "Ercilla",
            "collipulli": "Collipulli",
            "los sauces": "Los Sauces",
            "araucania": "Región de La Araucanía",
        }
        return display_names.get(normalized_name, normalized_name.title())

    def _build_trip_days(
        self,
        start_date: date,
        end_date: date,
        existing_days: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        existing_by_date = {
            str(day.get("day_date")): day
            for day in existing_days
            if isinstance(day, dict) and day.get("day_date")
        }
        days: list[dict[str, Any]] = []
        current = start_date
        index = 1
        while current <= end_date:
            day_key = current.isoformat()
            existing = dict(existing_by_date.get(day_key) or {})
            existing["day_index"] = index
            existing["day_date"] = day_key
            existing["day_label"] = f"{WEEKDAY_NAMES[current.weekday()].capitalize()} {current.day:02d}"
            existing.setdefault("base_area", None)
            existing.setdefault("lodging", None)
            existing.setdefault("meal_preferences", [])
            existing.setdefault("activity_preferences", [])
            days.append(existing)
            current += timedelta(days=1)
            index += 1
        return days

    def _detect_day_index(self, normalized: str, start_date: date, end_date: date) -> int | None:
        for alias, index in DAY_ORDINAL_ALIASES.items():
            if alias in normalized and 1 <= index <= ((end_date - start_date).days + 1):
                return index

        for weekday_name, weekday_index in WEEKDAY_ALIASES.items():
            if weekday_name not in normalized:
                continue
            current = start_date
            while current <= end_date:
                if current.weekday() == weekday_index:
                    return (current - start_date).days + 1
                current += timedelta(days=1)
        return None

    def _extract_day_segments(self, normalized: str, start_date: date, end_date: date) -> list[tuple[int, str]]:
        matches: list[tuple[int, int]] = []
        trip_length = (end_date - start_date).days + 1

        for alias, index in DAY_ORDINAL_ALIASES.items():
            normalized_alias = self.normalize_message(alias)
            if not 1 <= index <= trip_length:
                continue
            for match in re.finditer(rf"\b{re.escape(normalized_alias)}\b", normalized):
                matches.append((match.start(), index))

        for weekday_name, weekday_index in WEEKDAY_ALIASES.items():
            normalized_weekday = self.normalize_message(weekday_name)
            current = start_date
            while current <= end_date:
                if current.weekday() == weekday_index:
                    day_index = (current - start_date).days + 1
                    for match in re.finditer(rf"\b{re.escape(normalized_weekday)}\b", normalized):
                        matches.append((match.start(), day_index))
                    break
                current += timedelta(days=1)

        deduped: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for position, day_index in sorted(matches):
            key = (position, day_index)
            if key not in seen:
                seen.add(key)
                deduped.append(key)

        segments: list[tuple[int, str]] = []
        for offset, (position, day_index) in enumerate(deduped):
            next_position = deduped[offset + 1][0] if offset + 1 < len(deduped) else len(normalized)
            segments.append((day_index, normalized[position:next_position]))
        return segments

    def _detect_meal_slot(self, normalized: str) -> str | None:
        if any(term in normalized for term in ("desayuno", "desayunar", "mañana", "manana")):
            return "breakfast"
        if any(term in normalized for term in ("almuerzo", "almorzar", "mediodia", "medio dia", "mediodía")):
            return "lunch"
        if any(term in normalized for term in ("once", "tarde")):
            return "once"
        if any(term in normalized for term in ("cena", "cenar", "noche")):
            return "dinner"
        return None

    def _detect_activity_slot(self, normalized: str) -> str | None:
        if any(term in normalized for term in ("mañana", "manana", "temprano")):
            return "morning"
        if "tarde" in normalized:
            return "afternoon"
        if "noche" in normalized:
            return "night"
        return None

    def _detect_repeat_scope(self, normalized: str) -> str | None:
        if any(term in normalized for term in ("todos los dias", "todos los días", "cada dia", "cada día")):
            return "all_days"
        if any(term in normalized for term in ("todas las noches", "cada noche", "todas las cenas")):
            return "all_days"
        return None

    def _scope_from_context(
        self,
        *,
        day_index: int | None,
        slot: str | None,
        repeat_scope: str | None,
    ) -> str:
        if repeat_scope:
            return repeat_scope
        if day_index is not None and slot:
            return "slot"
        if day_index is not None:
            return "day"
        return "unspecified"

    def _apply_base_areas_from_message(
        self,
        draft: dict[str, Any],
        normalized: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        updated = dict(draft)
        trip_days = list(updated.get("trip_days") or [])
        day_segments = self._extract_day_segments(normalized, start_date, end_date)

        for day_index, segment in day_segments:
            segment_zones = self.extract_route_locations(segment)["destinations"]
            if not segment_zones:
                continue
            for day in trip_days:
                if int(day.get("day_index") or 0) == day_index:
                    day["base_area"] = segment_zones[0]
                    break

        updated["trip_days"] = trip_days
        return updated

    def _extract_food_preference(self, normalized: str) -> str:
        has_soup = any(term in normalized for term in ("sopa", "sopas", "sopias", "cazuela"))
        has_meat = any(term in normalized for term in ("carne", "carnes", "asado", "parrilla"))
        if has_soup and has_meat:
            return "sopas/cazuelas o carnes"

        food_options = (
            ("pizza", ("pizza", "pizzeria", "pizzería")),
            ("mariscos", ("marisco", "mariscos", "pescado", "ceviche")),
            ("sopas/cazuelas", ("sopa", "sopas", "sopias", "cazuela")),
            ("carnes", ("carne", "carnes", "asado", "parrilla")),
            ("café", ("cafe", "café", "cafeteria", "cafetería")),
            ("sushi", ("sushi",)),
            ("hamburguesa", ("hamburguesa",)),
            ("comida local", ("comida local", "local", "típica", "tipica")),
        )
        for value, terms in food_options:
            if any(term in normalized for term in terms):
                return value
        return "gastronomía"

    def _extract_activity_preference(self, normalized: str, fallback: str) -> str:
        activity_options = (
            ("playa", ("playa",)),
            ("sendero", ("sendero", "trekking", "caminar")),
            ("mirador", ("mirador", "vista")),
            ("lago", ("lago",)),
            ("volcán", ("volcan", "volcán")),
            ("termas", ("terma", "termas")),
            ("cultura", ("museo", "mapuche", "cultura", "artesania", "artesanía")),
            ("tranquilo", ("tranquilo", "tranquila", "relajo", "descanso")),
        )
        for value, terms in activity_options:
            if any(term in normalized for term in terms):
                return value
        return fallback or "actividad"

    def _extract_lodging_preference(self, normalized: str) -> str:
        lodging_options = (
            ("hostel", ("hostel", "hostal")),
            ("hotel", ("hotel",)),
            ("cabaña", ("cabaña", "cabana")),
            ("camping", ("camping",)),
            ("hospedaje", ("hospedaje", "alojamiento", "dormir")),
        )
        for value, terms in lodging_options:
            if any(term in normalized for term in terms):
                return value
        return "alojamiento"

    def _add_preference_to_trip_draft(
        self,
        draft: dict[str, Any],
        entry: dict[str, Any],
        *,
        day_index: int | None,
        bucket: str,
    ) -> dict[str, Any]:
        updated = dict(draft)
        if day_index is not None:
            trip_days = list(updated.get("trip_days") or [])
            for day in trip_days:
                if int(day.get("day_index") or 0) == day_index:
                    values = list(day.get(bucket) or [])
                    if not self._contains_structured_entry(values, entry):
                        values.append(entry)
                    day[bucket] = values
                    if bucket == "lodging_preferences" and day.get("lodging") is None:
                        day["lodging"] = {"preference": entry["value"], "poi_id": None, "source": "message"}
                    break
            updated["trip_days"] = trip_days
            return updated

        global_preferences = dict(
            updated.get("global_preferences")
            or {"meal_preferences": [], "activity_preferences": [], "lodging_preferences": []}
        )
        values = list(global_preferences.get(bucket) or [])
        if not self._contains_structured_entry(values, entry):
            values.append(entry)
        global_preferences[bucket] = values
        updated["global_preferences"] = global_preferences
        return updated

    def _add_plan_entry(
        self,
        draft: dict[str, Any],
        plan_key: str,
        entry: dict[str, Any],
    ) -> dict[str, Any]:
        updated = dict(draft)
        values = list(updated.get(plan_key) or [])
        if not self._contains_structured_entry(values, entry):
            values.append(entry)
        updated[plan_key] = values
        return updated

    def _contains_structured_entry(self, values: list[dict[str, Any]], entry: dict[str, Any]) -> bool:
        entry_key = json.dumps(entry, sort_keys=True, ensure_ascii=False)
        return any(json.dumps(value, sort_keys=True, ensure_ascii=False) == entry_key for value in values)

    def _has_weather_override(self, normalized: str) -> bool:
        has_bad_weather = any(term in normalized for term in ("llueva", "lloviendo", "lluvia", "mal clima", "mal tiempo"))
        has_override = any(term in normalized for term in ("aunque", "igual", "de todas formas", "no importa"))
        return has_bad_weather and has_override

    def _poi_role_from_categories(self, category_ids: set[int]) -> str:
        if 2 in category_ids:
            return "meal"
        if 4 in category_ids:
            return "lodging"
        if category_ids & {1, 6, 7, 8, 9, 10, 12}:
            return "activity"
        if category_ids & {5, 11, 15}:
            return "activity"
        return "unknown"

    def compact_constraints(self, constraints: list[str], limit: int = 5) -> list[str]:
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

    def extract_itinerary_step_context(self, message: str) -> dict[str, UUID] | None:
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

    def extract_replace_selection(self, message: str, preferences: dict[str, Any] | None = None) -> dict[str, UUID] | None:
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

    def extract_candidate_selection(self, message: str) -> UUID | None:
        match = SELECT_POI_PATTERN.search(message)
        if not match:
            return None
        return UUID(match.group("poi_id"))

    def build_replacement_quick_replies(
        self,
        alternatives: list[POIResponse],
        step_id: UUID,
    ) -> list[AraQuickReply]:
        replies = [
            AraQuickReply(
                id=f"usar_poi_{poi.id}",
                label=f"Usar {poi.nombre[:28]}",
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
        return self._dedupe_quick_replies(replies)

    def build_replacement_message(
        self,
        current_poi_name: str,
        alternatives: list[POIResponse],
    ) -> str:
        if not alternatives:
            return (
                f"Entendí que quieres cambiar {current_poi_name}, pero todavía no encontré una alternativa sólida "
                "con el contexto disponible. Puedes decirme si prefieres algo más cercano, gastronómico, natural o tranquilo."
            )

        names = ", ".join(poi.nombre for poi in alternatives[:3])
        return (
            f"Entendí que quieres cambiar la parada {current_poi_name}. Encontré alternativas reales para reemplazarla: "
            f"{names}. Elige una opción o dime qué criterio priorizar: cercanía, tipo de experiencia, horario o ritmo del viaje."
        )

    def build_quick_replies(self, intent: dict[str, Any], preferences: dict[str, Any]) -> list[AraQuickReply]:
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
        if self._should_offer_create_itinerary(preferences) and "crear_itinerario" not in consumed_reply_ids:
            replies.append(
                AraQuickReply(
                    id="crear_itinerario",
                    label="Crear itinerario",
                    value="Crear itinerario con lo acordado",
                    type="generate",
                )
            )
        return self._dedupe_quick_replies(replies)[:6]

    def build_generate_request_message(self, preferences: dict[str, Any]) -> str:
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
        self,
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

    def mark_selected_poi(
        self,
        preferences: dict[str, Any],
        poi: POIResponse,
    ) -> dict[str, Any]:
        updated = dict(preferences)
        selected_poi_ids = {str(value) for value in updated.get("selected_poi_ids", [])}
        selected_poi_ids.add(str(poi.id))
        updated["selected_poi_ids"] = sorted(selected_poi_ids)
        updated["last_selected_poi_id"] = str(poi.id)
        updated["last_selected_poi_name"] = poi.nombre

        completed_dimensions = set(updated.get("completed_dimensions", []))
        category_ids = set(poi.category_ids or [])
        if 2 in category_ids:
            completed_dimensions.add("gastronomia")
        if 4 in category_ids:
            completed_dimensions.add("alojamiento")
        if category_ids & {1, 6, 7, 8, 9, 10, 12}:
            completed_dimensions.add("naturaleza")
        if category_ids & {5, 11, 15}:
            completed_dimensions.add("cultura")
        updated["completed_dimensions"] = sorted(completed_dimensions)

        draft = dict(updated.get("trip_draft") or {})
        draft.setdefault("selected_pois", [])
        role = self._poi_role_from_categories(category_ids)
        scope = "entire_trip" if role == "lodging" else "unspecified"
        selected_entry = {
            "poi_id": str(poi.id),
            "name": poi.nombre,
            "role": role,
            "scope": scope,
            "day_index": None,
            "meal_slot": None,
            "slot": None,
            "locked": False,
            "source": "candidate_selection",
        }
        selected_values = list(draft.get("selected_pois") or [])
        if not any(str(value.get("poi_id")) == str(poi.id) for value in selected_values if isinstance(value, dict)):
            selected_values.append(selected_entry)
        draft["selected_pois"] = selected_values

        if role == "lodging":
            lodging_entry = {
                "poi_id": str(poi.id),
                "name": poi.nombre,
                "value": poi.nombre,
                "scope": "entire_trip",
                "from_day": 1,
                "to_day": len(draft.get("trip_days") or [1]),
                "base_area": None,
                "locked": False,
                "source": "candidate_selection",
            }
            draft = self._add_plan_entry(draft, "lodging_plan", lodging_entry)
            trip_days = list(draft.get("trip_days") or [])
            for day in trip_days:
                if day.get("lodging") is None:
                    day["lodging"] = {
                        "poi_id": str(poi.id),
                        "name": poi.nombre,
                        "scope": "entire_trip",
                        "source": "candidate_selection",
                    }
            draft["trip_days"] = trip_days
        elif role == "meal":
            draft = self._add_plan_entry(
                draft,
                "meal_plan",
                {
                    "poi_id": str(poi.id),
                    "name": poi.nombre,
                    "value": poi.nombre,
                    "scope": "unspecified",
                    "day_index": None,
                    "meal_slot": None,
                    "locked": False,
                    "source": "candidate_selection",
                },
            )
        elif role == "activity":
            draft = self._add_plan_entry(
                draft,
                "activity_plan",
                {
                    "poi_id": str(poi.id),
                    "name": poi.nombre,
                    "value": poi.nombre,
                    "scope": "unspecified",
                    "day_index": None,
                    "slot": None,
                    "locked": False,
                    "source": "candidate_selection",
                },
            )

        updated["trip_draft"] = draft
        updated["route_ready_score"] = self._estimate_route_ready_score(updated)
        return updated

    def compact_candidate_pois(
        self,
        pois: list[POIResponse],
        *,
        replacement_step_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        return [
            self._compact_candidate_poi(poi, replacement_step_id=replacement_step_id)
            for poi in pois[:8]
        ]

    def _compact_candidate_poi(
        self,
        poi: POIResponse,
        *,
        replacement_step_id: UUID | None = None,
    ) -> dict[str, Any]:
        payload = {
            "id": str(poi.id),
            "nombre": poi.nombre,
            "descripcion": poi.descripcion,
            "category_ids": poi.category_ids,
            "latitude": poi.latitude,
            "longitude": poi.longitude,
            "multimedia_urls": poi.multimedia_urls,
            "distancia_metros": poi.distancia_metros,
            "opening_hours_text": poi.opening_hours_text,
            "visit_rules": poi.visit_rules,
        }
        if replacement_step_id is not None:
            payload["action_value"] = f"usar poi {poi.id} para step {replacement_step_id}"
        else:
            payload["action_value"] = f"seleccionar poi {poi.id}"
        return payload

    def build_refined_query(
        self,
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
            f"Restricciones negativas activas: {self.compact_constraints(safe_preferences.get('negative_constraints', []))}\n"
            f"Tags acumulados: {safe_preferences.get('tags', [])}\n"
            f"Dimensiones completadas: {safe_preferences.get('completed_dimensions', [])}"
        )

    def _has_specific_niche(self, normalized_message: str) -> bool:
        return any(term in normalized_message for term in SPECIFIC_FOOD_TERMS) or any(
            term in normalized_message for term in ("sendero", "mirador", "lago", "terma", "volcán", "volcan", "museo")
        )

    def _detect_question_topic(self, normalized: str) -> str:
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

    def _detect_refinement_topic(self, normalized: str) -> str:
        if any(term in normalized for term in ("nino", "familia")):
            return "children"
        if any(term in normalized for term in ("cerca", "lejos", "traslado")):
            return "access"
        if any(term in normalized for term in ("dificultad", "caminar", "flojo", "tranquilo")):
            return "difficulty"
        return "preferences"

    def _extract_negative_constraints(self, normalized: str) -> list[str]:
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

    def _extract_positive_preferences(self, normalized: str) -> list[str]:
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

    def _conflicts_with_negative_constraints(self, preference: str, constraints: set[str]) -> bool:
        conflicts = {
            "baja_dificultad": {"alta_dificultad"},
            "poco_traslado": {"mucho_traslado"},
        }
        return bool(conflicts.get(preference, set()) & constraints)

    def _is_keyword_negated(self, normalized: str, keyword: str) -> bool:
        pattern = rf"\b(?:no quiero|ni me hables de|evita|evitar|sin)\b[\w\s]{{0,30}}\b{re.escape(keyword)}\b"
        return re.search(pattern, normalized) is not None

    def _conversation_mode_for_turn(self, turn_type: object) -> str:
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

    def _estimate_route_ready_score(self, preferences: dict[str, Any]) -> float:
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

    def _should_offer_create_itinerary(self, preferences: dict[str, Any]) -> bool:
        if preferences.get("auto_generate_requested"):
            return True
        if preferences.get("surprise_route_requested"):
            return True
        if float(preferences.get("route_ready_score") or 0) >= 0.45:
            return True
        if preferences.get("selected_poi_ids"):
            return True
        return bool(preferences.get("completed_dimensions") and int(preferences.get("turn_count", 0)) >= 1)

    def _dedupe_quick_replies(self, replies: list[AraQuickReply]) -> list[AraQuickReply]:
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


_ara_conversation_service: AraConversationService | None = None


def get_ara_conversation_service() -> AraConversationService:
    global _ara_conversation_service
    if _ara_conversation_service is None:
        _ara_conversation_service = AraConversationService()
    return _ara_conversation_service
