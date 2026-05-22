from __future__ import annotations

from typing import Any
from uuid import UUID

from geoalchemy2 import Geography
from geoalchemy2.elements import WKTElement
from sqlalchemy import cast, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entrepreneur_profile import EntrepreneurProfile
from app.models.poi import POI
from app.models.poi_category import POICategory
from app.models.poi_visit import POIVisit
from app.models.review import Review
from app.repositories.base import BaseRepository
from app.repositories.utils import build_poi_response_from_row, get_category_ids_batch
from app.schemas.poi import POICreate, POIResponse, POIUpdate, PotentialDuplicate


DUPLICATE_GEO_RADIUS_METERS = 50.0
DUPLICATE_CATEGORY_OVERLAP_BONUS = 0.1
DUPLICATE_SEMANTIC_THRESHOLD = 0.75


def from_text(wkt: str, srid: int) -> WKTElement:
    return WKTElement(wkt, srid=srid)


class POIRepository(BaseRepository):
    async def create_poi(
        self,
        db: AsyncSession,
        poi_in: POICreate,
        embedding: list[float],
        entrepreneur_id: UUID | None = None,
        verification_status: str = "pending",
        confidence_score: float = 0.0,
    ) -> POIResponse:
        location = from_text(f"POINT({poi_in.longitude} {poi_in.latitude})", srid=4326)

        multimedia_urls: dict[str, Any] = {"cover": poi_in.image_url, "gallery": [poi_in.image_url]}

        poi = POI(
            entrepreneur_id=entrepreneur_id,
            name=poi_in.name,
            description=poi_in.description,
            description_embedding=embedding,
            location=location,
            access_type=poi_in.access_type,
            contact_phone=poi_in.contact_phone,
            contact_email=poi_in.contact_email,
            multimedia_urls=multimedia_urls,
            opening_hours_text=poi_in.opening_hours_text,
            visit_rules=poi_in.visit_rules,
            verification_status=verification_status,
            confidence_score=confidence_score,
        )
        db.add(poi)

        try:
            await db.flush()

            for category_id in poi_in.category_ids:
                db.add(POICategory(poi_id=poi.id, category_id=category_id))

            await self._commit_or_rollback(db)
        except Exception:
            await db.rollback()
            raise

        return await self._get_poi_response_by_id(db, poi.id)

    async def update_poi(
        self,
        db: AsyncSession,
        poi_id: UUID,
        poi_in: POIUpdate,
        embedding: list[float] | None = None,
    ) -> POIResponse | None:
        poi = await db.get(POI, poi_id)
        if poi is None:
            return None

        if poi_in.name is not None:
            poi.name = poi_in.name
        if poi_in.description is not None:
            poi.description = poi_in.description
        if embedding is not None:
            poi.description_embedding = embedding
        if poi_in.access_type is not None:
            poi.access_type = poi_in.access_type
        if poi_in.contact_phone is not None:
            poi.contact_phone = poi_in.contact_phone
        if poi_in.contact_email is not None:
            poi.contact_email = poi_in.contact_email
        if poi_in.opening_hours_text is not None:
            poi.opening_hours_text = poi_in.opening_hours_text
        if poi_in.visit_rules is not None:
            poi.visit_rules = poi_in.visit_rules
        if poi_in.latitude is not None and poi_in.longitude is not None:
            poi.location = from_text(f"POINT({poi_in.longitude} {poi_in.latitude})", srid=4326)

        try:
            if poi_in.category_ids is not None:
                await db.execute(delete(POICategory).where(POICategory.poi_id == poi_id))
                for category_id in poi_in.category_ids:
                    db.add(POICategory(poi_id=poi_id, category_id=category_id))

            await self._commit_or_rollback(db)
        except Exception:
            await db.rollback()
            raise

        return await self._get_poi_response_by_id(db, poi_id)

    async def delete_poi(self, db: AsyncSession, poi_id: UUID) -> bool:
        poi = await db.get(POI, poi_id)
        if poi is None:
            return False

        try:
            await db.delete(poi)
            await self._commit_or_rollback(db)
        except Exception:
            await db.rollback()
            raise

        return True

    async def get_pois_by_entrepreneur(
        self,
        db: AsyncSession,
        entrepreneur_id: UUID,
    ) -> list[POIResponse]:
        stmt = (
            select(
                POI,
                func.ST_Y(POI.location).label("latitude"),
                func.ST_X(POI.location).label("longitude"),
            )
            .where(POI.entrepreneur_id == entrepreneur_id)
            .order_by(POI.name.asc())
        )
        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            return []
        category_map = await get_category_ids_batch(db, [poi.id for poi, _, _ in rows])
        return [
            build_poi_response_from_row(poi, latitude, longitude, category_map.get(poi.id, []))
            for poi, latitude, longitude in rows
        ]

    async def append_media_url(
        self,
        db: AsyncSession,
        poi_id: UUID,
        image_url: str,
    ) -> POIResponse | None:
        poi = await db.get(POI, poi_id)
        if poi is None:
            return None

        poi.multimedia_urls = self._append_image_to_media(poi.multimedia_urls, image_url)

        await self._commit_or_rollback(db)

        return await self._get_poi_response_by_id(db, poi_id)

    async def get_pois_nearby(
        self,
        db: AsyncSession,
        lat: float,
        lon: float,
        radius_meters: float,
        category_ids: list[int] | None = None,
    ) -> list[POIResponse]:
        reference_point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
        poi_geography = cast(POI.location, Geography)
        reference_geography = cast(reference_point, Geography)

        stmt = (
            select(
                POI,
                func.ST_Y(POI.location).label("latitude"),
                func.ST_X(POI.location).label("longitude"),
                func.ST_Distance(poi_geography, reference_geography).label("distance_meters"),
            )
            .where(func.ST_DWithin(poi_geography, reference_geography, radius_meters))
            .where(POI.verification_status != "flagged")
            .order_by("distance_meters")
        )
        if category_ids:
            matching_poi_ids = select(POICategory.poi_id).where(
                POICategory.category_id.in_(category_ids)
            )
            stmt = stmt.where(POI.id.in_(matching_poi_ids))

        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            return []
        category_map = await get_category_ids_batch(db, [poi.id for poi, _, _, _ in rows])
        return [
            build_poi_response_from_row(
                poi, latitude, longitude,
                category_map.get(poi.id, []),
                distance_meters=float(distance_meters) if distance_meters is not None else None,
            )
            for poi, latitude, longitude, distance_meters in rows
        ]

    async def search_hybrid(
        self,
        db: AsyncSession,
        lat: float,
        lon: float,
        radius_meters: float,
        query_embedding: list[float],
        user_interests_embedding: list[float] | None = None,
        profile_weight: float = 0.3,
        limit: int = 5,
    ) -> list[POIResponse]:
        reference_point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
        poi_geography = cast(POI.location, Geography)
        reference_geography = cast(reference_point, Geography)
        query_distance = POI.description_embedding.cosine_distance(query_embedding)
        ranking_score = query_distance

        if user_interests_embedding is not None and profile_weight > 0.0:
            profile_distance = POI.description_embedding.cosine_distance(user_interests_embedding)
            query_weight = max(0.0, min(1.0, 1.0 - profile_weight))
            ranking_score = (query_distance * query_weight) + (profile_distance * profile_weight)

        stmt = (
            select(
                POI,
                func.ST_Y(POI.location).label("latitude"),
                func.ST_X(POI.location).label("longitude"),
                func.ST_Distance(poi_geography, reference_geography).label("distance_meters"),
                ranking_score.label("ranking_score"),
            )
            .where(func.ST_DWithin(poi_geography, reference_geography, radius_meters))
            .where(POI.description_embedding.is_not(None))
            .where(POI.verification_status != "flagged")
            .order_by("ranking_score")
            .limit(limit)
        )

        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            return []
        category_map = await get_category_ids_batch(db, [poi.id for poi, _, _, _, _ in rows])
        return [
            build_poi_response_from_row(
                poi, latitude, longitude,
                category_map.get(poi.id, []),
                distance_meters=float(distance_meters) if distance_meters is not None else None,
            )
            for poi, latitude, longitude, distance_meters, _ranking_score in rows
        ]

    async def get_poi_by_id(self, db: AsyncSession, poi_id: UUID) -> POIResponse | None:
        stmt = select(
            POI,
            func.ST_Y(POI.location).label("latitude"),
            func.ST_X(POI.location).label("longitude"),
        ).where(POI.id == poi_id)
        result = await db.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return None

        poi, latitude, longitude = row
        category_map = await get_category_ids_batch(db, [poi.id])
        return build_poi_response_from_row(poi, latitude, longitude, category_map.get(poi.id, []))

    async def get_pois_by_ids(self, db: AsyncSession, poi_ids: list[UUID]) -> list[POIResponse]:
        if not poi_ids:
            return []

        stmt = select(
            POI,
            func.ST_Y(POI.location).label("latitude"),
            func.ST_X(POI.location).label("longitude"),
        ).where(POI.id.in_(poi_ids))
        result = await db.execute(stmt)
        rows = result.all()
        order_by_id = {poi_id: index for index, poi_id in enumerate(poi_ids)}

        category_map = await get_category_ids_batch(db, [poi.id for poi, _, _ in rows])
        return [
            build_poi_response_from_row(poi, latitude, longitude, category_map.get(poi.id, []))
            for poi, latitude, longitude in sorted(rows, key=lambda row: order_by_id.get(row[0].id, len(order_by_id)))
        ]

    async def get_poi_model_by_id(self, db: AsyncSession, poi_id: UUID) -> POI | None:
        return await db.get(POI, poi_id)

    async def _get_poi_response_by_id(self, db: AsyncSession, poi_id: UUID) -> POIResponse:
        stmt = select(
            POI,
            func.ST_Y(POI.location).label("latitude"),
            func.ST_X(POI.location).label("longitude"),
        ).where(POI.id == poi_id)
        result = await db.execute(stmt)
        row = result.one()
        poi, latitude, longitude = row
        category_map = await get_category_ids_batch(db, [poi.id])
        return build_poi_response_from_row(poi, latitude, longitude, category_map.get(poi.id, []))

    async def find_potential_duplicates(
        self,
        db: AsyncSession,
        lat: float,
        lon: float,
        query_embedding: list[float],
        category_ids: list[int],
        radius_meters: float = DUPLICATE_GEO_RADIUS_METERS,
        semantic_threshold: float = DUPLICATE_SEMANTIC_THRESHOLD,
    ) -> list[PotentialDuplicate]:
        reference_point = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
        poi_geography = cast(POI.location, Geography)
        reference_geography = cast(reference_point, Geography)

        distance_expr = func.ST_Distance(poi_geography, reference_geography)
        cosine_distance = POI.description_embedding.cosine_distance(query_embedding)

        stmt = (
            select(
                POI,
                func.ST_Y(POI.location).label("latitude"),
                func.ST_X(POI.location).label("longitude"),
                distance_expr.label("distance_meters"),
                cosine_distance.label("semantic_distance"),
            )
            .where(func.ST_DWithin(poi_geography, reference_geography, radius_meters))
            .where(POI.description_embedding.is_not(None))
        )

        if category_ids:
            matching_poi_ids = select(POICategory.poi_id).where(
                POICategory.category_id.in_(category_ids)
            )
            stmt = stmt.where(POI.id.in_(matching_poi_ids))

        stmt = stmt.order_by("distance_meters").limit(10)

        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            return []

        candidate_poi_ids = [poi.id for poi, _, _, _, _ in rows]
        category_map = await get_category_ids_batch(db, candidate_poi_ids)

        duplicates: list[PotentialDuplicate] = []
        for poi, latitude, longitude, distance_meters, semantic_distance in rows:
            similarity = 1.0 - float(semantic_distance)
            if similarity >= (1.0 - semantic_threshold):
                duplicates.append(
                    PotentialDuplicate(
                        id=poi.id,
                        name=poi.name,
                        description=poi.description[:200] if poi.description else "",
                        latitude=float(latitude),
                        longitude=float(longitude),
                        category_ids=category_map.get(poi.id, []),
                        distance_meters=float(distance_meters),
                        semantic_similarity=round(similarity, 3),
                    )
                )

        return duplicates

    def _append_image_to_media(
        self,
        media: object,
        image_url: str,
    ) -> dict[str, object] | list[object]:
        if isinstance(media, list):
            updated = list(media)
            if image_url not in updated:
                updated.append(image_url)
            return updated

        if isinstance(media, dict):
            gallery = media.get("gallery")
            if not isinstance(gallery, list):
                gallery = []

            if image_url not in gallery:
                gallery.append(image_url)

            updated = dict(media)
            updated["gallery"] = gallery
            if not updated.get("cover"):
                updated["cover"] = image_url
            return updated

        return {
            "cover": image_url,
            "gallery": [image_url],
        }

    async def recalculate_confidence(self, db: AsyncSession, poi_id: UUID) -> float:
        poi = await db.get(POI, poi_id)
        if poi is None:
            return 0.0
    
        score = 0.0
    
        has_image = False
        if poi.multimedia_urls is not None:
            if isinstance(poi.multimedia_urls, dict):
                has_image = bool(poi.multimedia_urls.get("cover")) or bool(poi.multimedia_urls.get("gallery"))
            elif isinstance(poi.multimedia_urls, list) and len(poi.multimedia_urls) > 0:
                has_image = True
        if has_image:
            score += 0.2
    
        desc_len = len(poi.description) if poi.description else 0
        if desc_len >= 50:
            score += 0.15
        elif desc_len >= 20:
            score += 0.05
    
        stats_stmt = (
            select(
                func.coalesce(func.count(POICategory.category_id), 0).label("category_count"),
                func.coalesce(func.count(Review.id), 0).label("review_count"),
                func.coalesce(func.count(POIVisit.id), 0).label("visit_count"),
            )
            .outerjoin(POICategory, POICategory.poi_id == POI.id)
            .outerjoin(Review, Review.poi_id == POI.id)
            .outerjoin(POIVisit, POIVisit.poi_id == POI.id)
            .where(POI.id == poi_id)
            .group_by(POI.id)
        )
        stats_result = await db.execute(stats_stmt)
        stats_row = stats_result.one_or_none()
    
        if stats_row is not None:
            category_count, review_count, visit_count = stats_row
    
            if category_count and category_count > 0:
                score += 0.1
            if review_count and review_count > 0:
                score += min(0.1, review_count * 0.02)
            if visit_count and visit_count > 0:
                score += min(0.1, visit_count * 0.01)
    
        if poi.opening_hours_text:
            score += 0.1
    
        if poi.contact_phone or poi.contact_email:
            score += 0.05
    
        if poi.entrepreneur_id is not None:
            profile = await db.get(EntrepreneurProfile, poi.entrepreneur_id)
            if profile is not None and profile.verification_status == "verified":
                score += 0.2
    
        score = min(round(score, 2), 1.0)
    
        poi.confidence_score = score
        if poi.verification_status == "flagged" and score >= 0.4:
            poi.verification_status = "pending"
    
        await self._commit_or_rollback(db)
        await db.refresh(poi)
    
        return score
