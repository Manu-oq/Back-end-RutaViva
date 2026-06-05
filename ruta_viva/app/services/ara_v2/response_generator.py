from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.models.ara_session import AraSession
from app.schemas.ara import AraQuickReply
from app.schemas.ara_comprehension import ComprehensionResult, QuickReplySuggestion, ToolExecutionResult
from app.services.ara_v2.slot_state import are_all_slots_filled, is_slot_filled
from app.services.ara_v2.utils import get_gpt_mini_client

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Eres Ara, una guia turistica conversacional de La Araucania, Chile.
REGLAS DE RESPUESTA:
1. Responde en espanol neutro latinoamericano.
2. NO usar emojis.
3. Ser conciso pero calido (2-4 oraciones maximo).
4. NO mencionar "POIs", "embeddings", "ranking", "modelo" ni logica interna.
5. Si muestras opciones, enumeralas claramente.
6. Si no tienes informacion, se honesto.
7. Mantene el tono que se indica en el contexto.
TONO:
{tono}
CONTEXTO DEL VIAJE:
Destino: {destino}
Fechas: {fechas}
Alojamiento: {alojamiento}
Preferencias: {preferencias}"""

_FALLBACKS = {
    "generate": "Tu itinerario esta listo. Puedes verlo en la app.",
    "search": "Encontre algunas opciones. Quieres que te las muestro?",
    "respond": "Buena pregunta. Te respondo con lo que tengo registrado.",
    "clarify": None,
    "replace": "Aqui tienes opciones para cambiar ese paso.",
    "error": "Algo salio mal. Quieres que lo intente de nuevo?",
}


class ResponseGenerator:
    """Genera respuestas naturales con GPT-4o-mini y fallbacks estructurados."""

    def __init__(self) -> None:
        self._client = get_gpt_mini_client()
        self._model = settings.openai_gpt_mini_model

    async def generate_response(
        self,
        comprehension: ComprehensionResult,
        tool_result: ToolExecutionResult,
        session: AraSession,
    ) -> dict[str, Any]:
        status = tool_result.status

        if status == "generate" and tool_result.itinerary:
            return await self._generate_itinerary_response(comprehension, tool_result, session)

        if status == "search" and tool_result.candidate_pois:
            return await self._generate_search_response(comprehension, tool_result, session)

        if status == "respond" and tool_result.response_text:
            quick_replies = self._build_quick_replies(tool_result.quick_replies)
            if not quick_replies:
                quick_replies = self._contextual_quick_replies(session)
            return {
                "text": tool_result.response_text,
                "quick_replies": quick_replies,
            }

        if status == "clarify":
            return self._generate_clarify_response(comprehension, tool_result, session)

        if status == "replace":
            return await self._generate_replace_response(comprehension, tool_result, session)

        if status == "step_replaced":
            metadata = None
            if tool_result.itinerary:
                metadata = {
                    "updated_itinerary": tool_result.itinerary.model_dump(mode="json"),
                    "itinerary_id": str(tool_result.itinerary.id),
                }
            return {
                "text": tool_result.response_text or "¡Listo! He reemplazado el lugar en tu itinerario.",
                "quick_replies": [],
                "metadata": metadata,
            }

        if status == "error":
            return {
                "text": self._get_fallback(tool_result),
                "quick_replies": [],
            }

        if status == "itinerary_pending":
            return {
                "text": "Estoy armando tu itinerario personalizado. Un momento...",
                "quick_replies": [],
            }

        return {
            "text": "Entendido. En que mas puedo ayudarte?",
            "quick_replies": [],
        }

    async def _generate_itinerary_response(
        self,
        comprehension: ComprehensionResult,
        tool_result: ToolExecutionResult,
        session: AraSession,
    ) -> dict[str, Any]:
        destino = self._extract_destino(comprehension, session)
        fechas = self._extract_fechas(session)

        prompt = (
            f"El usuario pidio un itinerario para {destino or 'un viaje'} de {fechas or 'varios dias'}. "
            f"El itinerario ya esta generado. Genera un mensaje natural y entusiasta confirmando que esta listo. "
            f"Menciona el destino si lo sabes. No menciones detalles tecnicos."
        )

        try:
            text = await self._call_gpt(prompt, comprehension.tono, session)
        except Exception:
            logger.exception("Failed to generate itinerary response, using fallback")
            text = self._get_fallback(tool_result)

        quick_replies = [
            AraQuickReply(id="qr_view", label="Ver itinerario", value="ver", type="navigation"),
        ]

        return {"text": text, "quick_replies": quick_replies}

    async def _generate_search_response(
        self,
        comprehension: ComprehensionResult,
        tool_result: ToolExecutionResult,
        session: AraSession,
    ) -> dict[str, Any]:
        empty_slots = self._get_empty_slots(session)

        if empty_slots and not self._user_specified_category(comprehension):
            slot = empty_slots[0]
            return self._generate_empty_slot_prompt(slot, comprehension, session)

        pois = tool_result.candidate_pois or []
        destino = self._extract_destino(comprehension, session)
        categorias = [e.valor for e in comprehension.entidades if e.tipo == "categoria"]
        categoria_str = categorias[0] if categorias else None

        if not pois:
            place_name = destino or "la zona"
            return {
                "text": f"No encontré lugares cerca de {place_name}. ¿Querés probar con otra zona?",
                "quick_replies": [],
            }

        poi_names = [self._poi_name(p) for p in pois[:5]] if pois else []
        pois_text = ", ".join(poi_names) if poi_names else "varias opciones"

        if categoria_str and pois:
            prompt = (
                f"Encontre {len(pois)} opciones de {categoria_str} en {destino or 'la zona'}. "
                f"Las principales son: {pois_text}. "
                f"Genera un mensaje natural mencionando estas opciones de {categoria_str} y preguntando cual le interesa."
            )
        elif pois:
            prompt = (
                f"Encontre {len(pois)} opciones en {destino or 'la zona'}. "
                f"Las principales son: {pois_text}. "
                f"Genera un mensaje natural mencionando estas opciones por nombre y preguntando cual le interesa."
            )
        else:
            prompt = (
                f"No encontre opciones especificas en {destino or 'la zona'}. "
                f"Genera un mensaje amable sugiriendo que puede buscar con otros terminos o ampliar la busqueda."
            )

        try:
            text = await self._call_gpt(prompt, comprehension.tono, session)
        except Exception:
            logger.exception("Failed to generate search response, using fallback")
            if pois:
                text = f"Encontre {len(pois)} opciones: {pois_text}. Cual te interesa?"
            else:
                text = self._get_fallback(tool_result)

        quick_replies = []
        if len(pois) <= 4:
            for i, poi in enumerate(pois[:4]):
                quick_replies.append(
                    AraQuickReply(
                        id=f"qr_poi_{i}",
                        label=self._poi_name(poi)[:30],
                        value=str(self._poi_id(poi, i)),
                        type="selection",
                    )
                )

        result: dict[str, Any] = {"text": text, "quick_replies": quick_replies}
        if self._is_lodging_search(comprehension, pois):
            result["metadata"] = self._lodging_disclaimer_metadata()

        return result

    async def _generate_replace_response(
        self,
        comprehension: ComprehensionResult,
        tool_result: ToolExecutionResult,
        session: AraSession,
    ) -> dict[str, Any]:
        alternatives = tool_result.candidate_pois or []
        alt_names = [self._poi_name(a) for a in alternatives[:3]]
        alts_text = ", ".join(alt_names) if alt_names else "varias alternativas"

        prompt = (
            f"Aqui tienes opciones para reemplazar el paso actual: {alts_text}. "
            f"Genera un mensaje natural ofreciendo estas alternativas."
        )

        try:
            text = await self._call_gpt(prompt, comprehension.tono, session)
        except Exception:
            logger.exception("Failed to generate replace response, using fallback")
            text = self._get_fallback(tool_result)

        quick_replies = []
        for i, alt in enumerate(alternatives[:3]):
            quick_replies.append(
                AraQuickReply(
                    id=f"qr_alt_{i}",
                    label=self._poi_name(alt)[:30],
                    value=str(self._poi_id(alt, i)),
                    type="selection",
                )
            )

        return {"text": text, "quick_replies": quick_replies}

    @staticmethod
    def _poi_name(poi: Any) -> str:
        if isinstance(poi, dict):
            return poi.get("name", poi.get("nombre", "Lugar"))
        return getattr(poi, "name", getattr(poi, "nombre", "Lugar")) or "Lugar"

    @staticmethod
    def _poi_id(poi: Any, fallback: int) -> str | int:
        if isinstance(poi, dict):
            return poi.get("id", fallback)
        return getattr(poi, "id", fallback)

    @staticmethod
    def _is_slot_filled(slot: dict) -> bool:
        return is_slot_filled(slot)

    @staticmethod
    def _are_all_slots_filled(session: AraSession) -> bool:
        return are_all_slots_filled(session)

    @staticmethod
    def _generate_clarify_response(
        comprehension: ComprehensionResult,
        tool_result: ToolExecutionResult,
        session: AraSession,
    ) -> dict[str, Any]:
        text = tool_result.response_text or "Necesito un poco mas de informacion."
        quick_replies = ResponseGenerator._build_quick_replies(comprehension.sugerir_quick_replies)
        if not ResponseGenerator._are_all_slots_filled(session):
            quick_replies = [
                reply for reply in quick_replies
                if reply.type not in {"generate", "finalize"}
            ]
        return {"text": text, "quick_replies": quick_replies}

    async def _call_gpt(self, prompt: str, tono: str, session: AraSession) -> str:
        # Escape braces in user-derived values to prevent .format() crashes
        def _escape(s: str) -> str:
            return s.replace("{", "{{").replace("}", "}}")

        system_prompt = _SYSTEM_PROMPT.format(
            tono=tono or "neutro",
            destino=_escape(self._extract_destino_from_session(session) or "La Araucania"),
            fechas=_escape(self._extract_fechas(session) or "Por definir"),
            alojamiento=_escape(self._extract_alojamiento(session) or "Por definir"),
            preferencias=_escape(self._extract_preferencias(session) or "Sin preferencias especificadas"),
        )

        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=0.3,
            max_tokens=300,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or self._get_fallback_simple()

    @staticmethod
    def _build_quick_replies(suggestions: list[QuickReplySuggestion] | None) -> list[AraQuickReply]:
        if not suggestions:
            return []
        return [
            AraQuickReply(
                id=f"qr_{i}",
                label=s.label,
                value=s.value,
                type=s.type,
            )
            for i, s in enumerate(suggestions)
        ]

    @staticmethod
    def _contextual_quick_replies(session: AraSession) -> list[AraQuickReply]:
        replies = []
        replies.append(AraQuickReply(id="qr_search", label="Buscar más lugares", value="buscar_mas", type="action"))

        prefs = session.preferences_data or {}
        trip_draft = prefs.get("trip_draft") or {}
        slots = trip_draft.get("slots", [])

        empty_slots = [s for s in slots if isinstance(s, dict) and s.get("status") == "empty"]
        if empty_slots:
            slot = empty_slots[0]
            period = slot.get("period")
            if period:
                period_map = {"morning": "la mañana", "afternoon": "la tarde", "night": "la noche"}
                label = f"Llenar {period_map.get(period, period)}"
            else:
                label = "Llenar actividad pendiente"
            replies.append(AraQuickReply(id="qr_fill_slot", label=label, value="llenar_slot", type="action"))
        elif session.start_date and session.end_date:
            replies.append(AraQuickReply(id="qr_itinerary", label="Armar itinerario", value="generar_itinerario", type="generate"))
        else:
            replies.append(AraQuickReply(id="qr_dates", label="Definir fechas", value="definir_fechas", type="action"))

        lodging = trip_draft.get("lodging") or prefs.get("lodging")
        if not lodging:
            replies.append(AraQuickReply(id="qr_lodging", label="Buscar alojamiento", value="buscar_alojamiento", type="action"))

        return replies

    @staticmethod
    def _get_fallback(tool_result: ToolExecutionResult) -> str:
        if tool_result.status == "clarify" and tool_result.response_text:
            return tool_result.response_text
        return _FALLBACKS.get(tool_result.status, "Entendido. En qué más puedo ayudarte?")

    @staticmethod
    def _get_fallback_simple() -> str:
        return "Entendido. En qué más puedo ayudarte?"

    @staticmethod
    def _extract_destino(comprehension: ComprehensionResult, session: AraSession) -> str | None:
        destinos = [e.valor for e in comprehension.entidades if e.tipo == "destino"]
        return destinos[0] if destinos else None

    @staticmethod
    def _extract_destino_from_session(session: AraSession) -> str | None:
        return session.initial_query if session.initial_query else None

    @staticmethod
    def _extract_fechas(session: AraSession) -> str | None:
        if session.start_date and session.end_date:
            return f"{session.start_date} a {session.end_date}"
        return None

    @staticmethod
    def _extract_alojamiento(session: AraSession) -> str | None:
        prefs = session.preferences_data or {}
        lodging = prefs.get("lodging")
        if lodging:
            return lodging.get("name", lodging.get("nombre"))
        return None

    @staticmethod
    def _extract_preferencias(session: AraSession) -> str | None:
        prefs = session.preferences_data or {}
        trip_draft = prefs.get("trip_draft") or {}
        days = trip_draft.get("trip_days") or []
        if days:
            prefs_list = []
            for day in days:
                if day.get("food_preferences"):
                    prefs_list.append(f"comida: {', '.join(day['food_preferences'])}")
                if day.get("activity_preferences"):
                    prefs_list.append(f"actividades: {', '.join(day['activity_preferences'])}")
            return "; ".join(prefs_list) if prefs_list else None
        return None

    @staticmethod
    def _get_empty_slots(session: AraSession) -> list[dict]:
        preferences = dict(session.preferences_data or {})
        trip_draft = dict(preferences.get("trip_draft") or {})
        slots = trip_draft.get("slots", [])
        return [s for s in slots if isinstance(s, dict) and s.get("status") == "empty"]

    @staticmethod
    def _user_specified_category(comprehension: ComprehensionResult) -> bool:
        return any(e.tipo == "categoria" for e in comprehension.entidades)

    @staticmethod
    def _generate_empty_slot_prompt(
        slot: dict,
        comprehension: ComprehensionResult,
        session: AraSession,
    ) -> dict[str, Any]:
        slot_type = slot.get("type", "activity")
        period = slot.get("period")

        if slot_type == "meal":
            meal_map = {
                "breakfast": "desayuno", "lunch": "almuerzo",
                "once": "once", "dinner": "cena",
            }
            meal_name = meal_map.get(slot.get("meal_type", ""), "comida")
            text = f"¿Qué tipo de {meal_name} te gustaría? ¿Algo local, rápido, o con vista?"
            quick_replies = [
                AraQuickReply(id="qr_comida_local", label="Comida local", value="comida local", type="selection"),
                AraQuickReply(id="qr_rapido", label="Algo rápido", value="comida rapida", type="selection"),
                AraQuickReply(id="qr_vista", label="Con vista", value="comida con vista", type="selection"),
            ]
        elif period:
            period_map = {"morning": "la mañana", "afternoon": "la tarde", "night": "la noche"}
            period_name = period_map.get(period, "ese momento")
            text = f"¿Qué te gustaría hacer en {period_name}? ¿Prefieres naturaleza, cultura o gastronomía?"
            quick_replies = [
                AraQuickReply(id="qr_naturaleza", label="Naturaleza", value="naturaleza", type="selection"),
                AraQuickReply(id="qr_cultura", label="Cultura", value="cultura", type="selection"),
                AraQuickReply(id="qr_gastronomia", label="Gastronomía", value="gastronomia", type="selection"),
            ]
        else:
            text = "¿Qué tipo de actividad te gustaría hacer? ¿Naturaleza, cultura, gastronomía?"
            quick_replies = [
                AraQuickReply(id="qr_naturaleza", label="Naturaleza", value="naturaleza", type="selection"),
                AraQuickReply(id="qr_cultura", label="Cultura", value="cultura", type="selection"),
                AraQuickReply(id="qr_gastronomia", label="Gastronomía", value="gastronomia", type="selection"),
            ]

        return {"text": text, "quick_replies": quick_replies}

    @staticmethod
    def _is_lodging_search(comprehension: ComprehensionResult, pois: list) -> bool:
        categorias = [e.valor for e in comprehension.entidades if e.tipo == "categoria"]
        if any(c in ("alojamiento", "hotel", "cabaña", "hostal", "camping") for c in categorias):
            return True
        for poi in pois:
            name = ResponseGenerator._poi_name(poi).lower()
            if any(kw in name for kw in ("hotel", "hostal", "cabaña", "camping", "hostel", "albergue")):
                return True
        return False

    @staticmethod
    def _lodging_disclaimer_metadata() -> dict[str, Any] | None:
        from app.core.ara_messages import AraMessages
        return {"disclaimer_text": AraMessages.get("lodging_disclaimer")}

    @staticmethod
    def _append_lodging_disclaimer(text: str) -> str:
        from app.core.ara_messages import AraMessages
        disclaimer = AraMessages.get("lodging_disclaimer")
        return f"{text}\n\n{disclaimer}"


_response_generator: ResponseGenerator | None = None


def get_response_generator() -> ResponseGenerator:
    global _response_generator
    if _response_generator is None:
        _response_generator = ResponseGenerator()
    return _response_generator


def reset_response_generator() -> None:
    global _response_generator
    _response_generator = None
