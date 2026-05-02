from __future__ import annotations

from uuid import UUID

from geoalchemy2 import Geography
from geoalchemy2.elements import WKTElement
from sqlalchemy import cast, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.poi import POI
from app.models.poi_category import POICategory
from app.schemas.poi import POICreate, POIResponse


def from_text(wkt: str, srid: int) -> WKTElement:
    return WKTElement(wkt, srid=srid)


class POIRepository:
    async def create_poi(
        self,
        db: AsyncSession,
        poi_in: POICreate,
        embedding: list[float],
        entrepreneur_id: UUID | None = None,
    ) -> POIResponse:
        location = from_text(f"POINT({poi_in.longitude} {poi_in.latitude})", srid=4326)

        poi = POI(
            entrepreneur_id=entrepreneur_id,
            name=poi_in.nombre,
            description=poi_in.descripcion,
            description_embedding=embedding,
            location=location,
            access_type=poi_in.tipo_acceso,
            contact_phone=poi_in.telefono_publico,
            contact_email=poi_in.email_publico,
            multimedia_urls=poi_in.multimedia_urls,
        )
        db.add(poi)

        try:
            await db.flush()

            for category_id in poi_in.category_ids:
                db.add(POICategory(poi_id=poi.id, category_id=category_id))

            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return await self._get_poi_response_by_id(db, poi.id)

    async def get_pois_nearby(
        self,
        db: AsyncSession,
        lat: float,
        lon: float,
        radius_meters: float,
    ) -> list[POIResponse]:
        reference_point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
        poi_geography = cast(POI.location, Geography)
        reference_geography = cast(reference_point, Geography)

        stmt = (
            select(
                POI,
                func.ST_Y(POI.location).label("latitude"),
                func.ST_X(POI.location).label("longitude"),
                func.ST_Distance(poi_geography, reference_geography).label("distancia_metros"),
            )
            .where(func.ST_DWithin(poi_geography, reference_geography, radius_meters))
            .order_by("distancia_metros")
        )

        result = await db.execute(stmt)
        rows = result.all()
        responses: list[POIResponse] = []
        for poi, latitude, longitude, distancia_metros in rows:
            category_ids = await self._get_category_ids(db, poi.id)
            responses.append(
                POIResponse(
                    id=poi.id,
                    nombre=poi.name,
                    descripcion=poi.description,
                    tipo_acceso=poi.access_type,
                    telefono_publico=poi.contact_phone,
                    email_publico=poi.contact_email,
                    multimedia_urls=poi.multimedia_urls,
                    category_ids=category_ids,
                    latitude=float(latitude),
                    longitude=float(longitude),
                    distancia_metros=float(distancia_metros) if distancia_metros is not None else None,
                )
            )
        return responses

    async def search_hybrid(
        self,
        db: AsyncSession,
        lat: float,
        lon: float,
        radius_meters: float,
        query_embedding: list[float],
        user_interests_embedding: list[float] | None = None,
        limit: int = 5,
    ) -> list[POIResponse]:
        reference_point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
        poi_geography = cast(POI.location, Geography)
        reference_geography = cast(reference_point, Geography)
        query_distance = POI.description_embedding.cosine_distance(query_embedding)
        ranking_score = query_distance

        if user_interests_embedding is not None:
            profile_distance = POI.description_embedding.cosine_distance(user_interests_embedding)
            ranking_score = (query_distance * 0.7) + (profile_distance * 0.3)

        stmt = (
            select(
                POI,
                func.ST_Y(POI.location).label("latitude"),
                func.ST_X(POI.location).label("longitude"),
                func.ST_Distance(poi_geography, reference_geography).label("distancia_metros"),
                ranking_score.label("ranking_score"),
            )
            .where(func.ST_DWithin(poi_geography, reference_geography, radius_meters))
            .where(POI.description_embedding.is_not(None))
            .order_by("ranking_score")
            .limit(limit)
        )

        result = await db.execute(stmt)
        rows = result.all()
        responses: list[POIResponse] = []
        for poi, latitude, longitude, distancia_metros, _ranking_score in rows:
            category_ids = await self._get_category_ids(db, poi.id)
            responses.append(
                POIResponse(
                    id=poi.id,
                    nombre=poi.name,
                    descripcion=poi.description,
                    tipo_acceso=poi.access_type,
                    telefono_publico=poi.contact_phone,
                    email_publico=poi.contact_email,
                    multimedia_urls=poi.multimedia_urls,
                    category_ids=category_ids,
                    latitude=float(latitude),
                    longitude=float(longitude),
                    distancia_metros=float(distancia_metros) if distancia_metros is not None else None,
                )
            )
        return responses

    async def _get_poi_response_by_id(self, db: AsyncSession, poi_id: UUID) -> POIResponse:
        stmt = select(
            POI,
            func.ST_Y(POI.location).label("latitude"),
            func.ST_X(POI.location).label("longitude"),
        ).where(POI.id == poi_id)
        result = await db.execute(stmt)
        row = result.one()
        poi, latitude, longitude = row
        category_ids = await self._get_category_ids(db, poi.id)
        return POIResponse(
            id=poi.id,
            nombre=poi.name,
            descripcion=poi.description,
            tipo_acceso=poi.access_type,
            telefono_publico=poi.contact_phone,
            email_publico=poi.contact_email,
            multimedia_urls=poi.multimedia_urls,
            category_ids=category_ids,
            latitude=float(latitude),
            longitude=float(longitude),
        )

    async def _get_category_ids(self, db: AsyncSession, poi_id: UUID) -> list[int]:
        stmt = select(POICategory.category_id).where(POICategory.poi_id == poi_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())
