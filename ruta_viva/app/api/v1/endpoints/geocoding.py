import httpx
from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.geocoding import GeocodingResult
from app.services.geocoding_service import search_places


router = APIRouter(tags=["geocoding"])


@router.get("/search", response_model=list[GeocodingResult])
async def search_geocoding(
    q: str = Query(..., min_length=2),
    lat: float | None = Query(default=None),
    lon: float | None = Query(default=None),
    limit: int = Query(default=8, ge=1, le=20),
) -> list[GeocodingResult]:
    try:
        return await search_places(query=q, lat=lat, lon=lon, limit=limit)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Geocoding provider failed.",
        ) from exc
