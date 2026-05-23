from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.schemas.itinerary import ItineraryResponse


class MemoryFact(BaseModel):
    hecho: str = Field(..., description="Hecho memorizable extraído del mensaje")
    categoria: str = Field(..., pattern="^(restriccion|preferencia|destino|entidad|horario|transporte|presupuesto)$")
    confianza: float = Field(..., ge=0.0, le=1.0)


class QuickReplySuggestion(BaseModel):
    label: str = Field(..., description="Texto visible para el usuario")
    value: str = Field(..., description="Valor interno cuando el usuario toca")
    type: str = Field(default="refinement", pattern="^(refinement|selection|action|navigation|generate)$")


class ExtractedEntity(BaseModel):
    tipo: str = Field(..., pattern="^(destino|poi|fecha|categoria|restriccion|preferencia|transporte|horario|presupuesto)$")
    valor: str
    confianza: float = Field(default=0.8, ge=0.0, le=1.0)


class DateRange(BaseModel):
    start: str | None = Field(None, description="Fecha inicio en ISO format")
    end: str | None = Field(None, description="Fecha fin en ISO format")


class ComprehensionResult(BaseModel):
    intenciones: list[str] = Field(
        default_factory=list,
        description="Lista de intenciones detectadas. Ej: ['planificar_viaje', 'definir_alojamiento']"
    )
    intencion_principal: str = Field(
        default="general",
        description="Intención dominante si hay múltiples"
    )
    confianza: float = Field(..., ge=0.0, le=1.0, description="Confianza global de la comprensión")
    entidades: list[ExtractedEntity] = Field(default_factory=list)
    rango_fechas: DateRange | None = None
    herramientas_necesarias: list[str] = Field(
        default_factory=list,
        description="Tools a ejecutar: search_pois, get_weather, build_itinerary, answer_question, suggest_replacement"
    )
    preguntas_pendientes: list[str] = Field(default_factory=list)
    actualizaciones_memoria: list[MemoryFact] = Field(default_factory=list)
    sugerir_quick_replies: list[QuickReplySuggestion] | None = None
    tono: str = Field(default="neutro", pattern="^(entusiasta|neutro|informativo|empatico)$")


class ToolExecutionResult(BaseModel):
    status: str = Field(..., pattern="^(respond|generate|search|clarify|replace|error)$")
    response_text: str | None = None
    quick_replies: list[QuickReplySuggestion] | None = None
    candidate_pois: list[dict] | None = None
    weather_forecast: str | None = None
    itinerary: Optional["ItineraryResponse"] = None
    context_payload: dict | None = None
    error: str | None = None
