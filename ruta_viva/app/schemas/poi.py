from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class POIBase(BaseModel):
    nombre: str
    descripcion: str
    tipo_acceso: str
    telefono_publico: str | None = None
    email_publico: str | None = None
    multimedia_urls: dict[str, Any] | None = None
    category_ids: list[int] = Field(default_factory=list)


class POICreate(POIBase):
    latitude: float
    longitude: float


class POIResponse(POIBase):
    id: UUID
    latitude: float
    longitude: float
    distancia_metros: float | None = None

    model_config = ConfigDict(from_attributes=True)
