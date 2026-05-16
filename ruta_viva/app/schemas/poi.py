from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class POIBase(BaseModel):
    nombre: str
    descripcion: str
    tipo_acceso: str
    telefono_publico: str | None = None
    email_publico: str | None = None
    multimedia_urls: dict[str, Any] | list[Any] | None = None
    opening_hours_text: str | None = None
    visit_rules: dict[str, Any] | None = None
    category_ids: list[int] = Field(default_factory=list)


class POICreate(POIBase):
    latitude: float
    longitude: float


class POIUpdate(BaseModel):
    nombre: str | None = None
    descripcion: str | None = None
    tipo_acceso: str | None = None
    telefono_publico: str | None = None
    email_publico: str | None = None
    opening_hours_text: str | None = None
    visit_rules: dict[str, Any] | None = None
    category_ids: list[int] | None = None
    latitude: float | None = None
    longitude: float | None = None


class POIMediaAppend(BaseModel):
    image_url: str


class POIResponse(POIBase):
    id: UUID
    latitude: float
    longitude: float
    distancia_metros: float | None = None

    model_config = ConfigDict(from_attributes=True)
