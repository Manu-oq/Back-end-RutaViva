from __future__ import annotations

from pydantic import BaseModel


class GeocodingResult(BaseModel):
    display_name: str
    latitude: float
    longitude: float
    type: str | None = None
    importance: float | None = None
    bounding_box: list[float] | None = None
