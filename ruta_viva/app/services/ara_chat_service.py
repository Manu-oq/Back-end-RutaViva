from __future__ import annotations

import json
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.core.config import settings
from app.schemas.ara import AraQuickReply
from app.schemas.itinerary import ItineraryResponse
from app.schemas.poi import POIResponse


class AraChatService:
    def __init__(self) -> None:
        self.client = (
            AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
            if settings.deepseek_api_key
            else None
        )
        self.model = "deepseek-chat"

    async def answer_free_question(
        self,
        *,
        user_message: str,
        topic: str,
        preferences: dict[str, Any],
        candidate_pois: list[POIResponse],
        active_itinerary: ItineraryResponse | None = None,
    ) -> dict[str, Any]:
        used_context = "active_itinerary" if active_itinerary is not None else ("candidate_pois" if candidate_pois else "general")
        fallback = self._fallback_answer(user_message, topic, candidate_pois, active_itinerary, used_context)

        if self.client is None:
            return fallback

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                temperature=0.2,
                response_format={"type": "json_object"},
                timeout=settings.ara_chat_timeout_seconds,
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "user_message": user_message,
                                "topic": topic,
                                "preferences": preferences,
                                "candidate_pois": [self._compact_poi(poi) for poi in candidate_pois[:8]],
                                "active_itinerary_steps": self._compact_itinerary(active_itinerary),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            )
            content = response.choices[0].message.content
            if not content:
                return fallback
            parsed = json.loads(content)
            return self._normalize_llm_answer(parsed, fallback, used_context, topic)
        except (json.JSONDecodeError, httpx.HTTPError, Exception):
            return fallback

    def _system_prompt(self) -> str:
        return """
Eres Ara, una guía turística conversacional de La Araucanía, Chile.
Responde la duda actual del usuario de forma breve, natural y útil.
No generes itinerarios completos ni JSON de itinerario.
No menciones "contexto", "POIs", "embedding", "ranking", "modelo" ni lógica interna.

Reglas anti-alucinación:
1. No afirmes baños, estacionamiento, accesibilidad, precios, tickets, horarios ni permisos si no aparecen explícitamente en los datos.
2. Usa evidence_level="confirmed" solo si el dato aparece explícitamente.
3. Usa evidence_level="inferred" si das orientación turística general sin afirmarla como dato del lugar.
4. Usa evidence_level="unknown" si no hay dato suficiente, pero ofrece una alternativa útil.
5. Si el usuario usa referencias como "primer lugar", "la pizza", "la cascada de la tarde", intenta resolverlas con active_itinerary_steps.
6. Si la referencia es ambigua, pregunta una aclaración breve.

Devuelve únicamente JSON válido:
{
  "answer": "respuesta al usuario",
  "quick_replies": [{"id": "string", "label": "string", "value": "string", "type": "refinement"}],
  "memory_patch": {"answered_questions": ["topic"]},
  "used_context": "active_itinerary | candidate_pois | general",
  "evidence_level": "confirmed | inferred | unknown"
}
""".strip()

    def _fallback_answer(
        self,
        user_message: str,
        topic: str,
        candidate_pois: list[POIResponse],
        active_itinerary: ItineraryResponse | None,
        used_context: str,
    ) -> dict[str, Any]:
        place_hint = self._place_hint(candidate_pois, active_itinerary)
        if topic == "difficulty":
            answer = (
                "Cuando hablo de dificultad me refiero al esfuerzo físico y logístico: pendiente, duración, tipo de camino, "
                "señalización y qué tan exigente puede ser llegar o recorrer el lugar. "
                f"{place_hint} Si quieres, puedo priorizar baja dificultad y traslados simples."
            )
            replies = [
                AraQuickReply(id="baja_dificultad", label="Baja dificultad", value="Prefiero baja dificultad"),
                AraQuickReply(id="poco_traslado", label="Poco traslado", value="Prefiero poco traslado"),
            ]
            evidence = "inferred"
        elif topic == "access":
            answer = (
                "No tengo confirmación exacta de acceso para todos los lugares. En atractivos naturales fuera del centro "
                "suele convenir vehículo o traslado coordinado; si prefieres, puedo priorizar lugares cercanos o urbanos."
            )
            replies = [
                AraQuickReply(id="priorizar_cercania", label="Más cercano", value="Prioriza lugares cercanos"),
                AraQuickReply(id="sin_auto", label="Sin vehículo", value="No tengo vehículo"),
                AraQuickReply(id="con_auto", label="Tengo vehículo", value="Tengo vehículo propio"),
            ]
            evidence = "inferred"
        elif topic in {"services", "price", "schedule"}:
            answer = (
                "No tengo ese dato confirmado en el registro para asegurarlo como hecho. "
                "Para evitar riesgos, puedo priorizar lugares urbanos, restaurantes o atractivos con mejor infraestructura registrada."
            )
            replies = [
                AraQuickReply(id="priorizar_servicios", label="Priorizar servicios", value="Prioriza lugares con servicios disponibles"),
                AraQuickReply(id="mas_urbano", label="Más urbano", value="Prefiero lugares urbanos o con mejor infraestructura"),
            ]
            evidence = "unknown"
        elif topic == "children":
            answer = (
                "Para ir con niños conviene priorizar baja dificultad, traslados cortos, horarios diurnos y lugares con servicios cercanos. "
                "Si un lugar no tiene reglas claras, es mejor tratarlo con criterio conservador."
            )
            replies = [
                AraQuickReply(id="apto_familia", label="Apto familia", value="Prefiero algo apto para familia"),
                AraQuickReply(id="baja_dificultad", label="Baja dificultad", value="Prefiero baja dificultad"),
            ]
            evidence = "inferred"
        elif topic == "weather":
            answer = (
                "Si hay lluvia o frío fuerte, conviene mover actividades outdoor a horarios más favorables y priorizar comida, cultura, "
                "termas o lugares protegidos. Puedo ajustar la ruta con ese criterio."
            )
            replies = [
                AraQuickReply(id="priorizar_indoor", label="Bajo techo", value="Prioriza actividades bajo techo si llueve"),
                AraQuickReply(id="ruta_flexible", label="Ruta flexible", value="Prefiero una ruta flexible por clima"),
            ]
            evidence = "inferred"
        else:
            answer = (
                "Buena pregunta. Puedo responderla usando lo que tengo registrado y, cuando no haya dato confirmado, "
                "te lo diré claramente para no inventar información."
            )
            replies = [
                AraQuickReply(id="ver_opciones", label="Ver opciones", value="Muéstrame opciones"),
                AraQuickReply(id="hazlo_todo_tu", label="Hazlo todo tú", value="Hazlo todo tú", type="generate"),
            ]
            evidence = "inferred"

        return {
            "answer": answer,
            "quick_replies": [reply.model_dump(mode="json") for reply in replies],
            "memory_patch": {
                "conversation_mode": "answering_question",
                "last_turn_type": "free_question",
                "last_question_topic": topic,
                "answered_questions": [topic],
            },
            "used_context": used_context,
            "evidence_level": evidence,
        }

    def _normalize_llm_answer(
        self,
        parsed: dict[str, Any],
        fallback: dict[str, Any],
        used_context: str,
        topic: str,
    ) -> dict[str, Any]:
        answer = parsed.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            return fallback

        quick_replies = parsed.get("quick_replies")
        if not isinstance(quick_replies, list):
            quick_replies = fallback["quick_replies"]

        evidence_level = parsed.get("evidence_level")
        if evidence_level not in {"confirmed", "inferred", "unknown"}:
            evidence_level = fallback["evidence_level"]

        memory_patch = parsed.get("memory_patch")
        if not isinstance(memory_patch, dict):
            memory_patch = {}
        memory_patch.setdefault("conversation_mode", "answering_question")
        memory_patch.setdefault("last_turn_type", "free_question")
        memory_patch.setdefault("last_question_topic", topic)
        memory_patch.setdefault("answered_questions", [topic])

        return {
            "answer": answer.strip(),
            "quick_replies": quick_replies[:4],
            "memory_patch": memory_patch,
            "used_context": parsed.get("used_context") or used_context,
            "evidence_level": evidence_level,
        }

    def _compact_poi(self, poi: POIResponse) -> dict[str, Any]:
        return {
            "id": str(poi.id),
            "name": poi.nombre,
            "description": poi.descripcion,
            "category_ids": poi.category_ids,
            "opening_hours_text": poi.opening_hours_text,
            "visit_rules": poi.visit_rules,
            "multimedia_urls": poi.multimedia_urls,
            "distance_meters": poi.distancia_metros,
        }

    def _compact_itinerary(self, itinerary: ItineraryResponse | None) -> list[dict[str, Any]]:
        if itinerary is None:
            return []
        return [
            {
                "step_order": step.step_order,
                "day_index": step.day_index,
                "day_label": step.day_label,
                "poi_id": str(step.poi_id),
                "poi_name": step.poi_nombre,
                "poi_description": step.poi_descripcion,
                "arrival_time": step.arrival_time.isoformat() if step.arrival_time else None,
                "departure_time": step.departure_time.isoformat() if step.departure_time else None,
                "ai_context": step.ai_context,
            }
            for step in itinerary.steps[:20]
        ]

    def _place_hint(self, candidate_pois: list[POIResponse], active_itinerary: ItineraryResponse | None) -> str:
        if active_itinerary is not None and active_itinerary.steps:
            first_step = active_itinerary.steps[0]
            if first_step.poi_nombre:
                return f"En tu itinerario aparece {first_step.poi_nombre} como referencia."
        if candidate_pois:
            names = ", ".join(poi.nombre for poi in candidate_pois[:2])
            return f"En la zona aparecen referencias como {names}."
        return ""


_ara_chat_service: AraChatService | None = None


def get_ara_chat_service() -> AraChatService:
    global _ara_chat_service
    if _ara_chat_service is None:
        _ara_chat_service = AraChatService()
    return _ara_chat_service
