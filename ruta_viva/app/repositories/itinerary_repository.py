from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.itinerary import Itinerary
from app.models.itinerary_step import ItineraryStep
from app.models.poi import POI
from app.models.poi_category import POICategory
from app.schemas.itinerary import GeneratedItinerary, ItineraryResponse, ItineraryStepResponse, ItineraryStepUpdate
from app.schemas.poi import POIResponse


class ItineraryRepository:
    async def create_generated_itinerary(
        self,
        db: AsyncSession,
        tourist_id: UUID,
        start_date: date,
        end_date: date,
        generated_itinerary: GeneratedItinerary,
    ) -> ItineraryResponse:
        itinerary = Itinerary(
            tourist_id=tourist_id,
            title=generated_itinerary.title,
            start_date=start_date,
            end_date=end_date,
            status=generated_itinerary.status,
        )
        db.add(itinerary)

        try:
            await db.flush()

            ordered_steps = sorted(generated_itinerary.steps, key=lambda step: step.step_order)
            for index, step in enumerate(ordered_steps, start=1):
                db.add(
                    ItineraryStep(
                        itinerary_id=itinerary.id,
                        poi_id=step.poi_id,
                        step_order=index,
                        arrival_time=step.arrival_time,
                        departure_time=step.departure_time,
                        ai_context=step.ai_context,
                    )
                )

            await db.commit()
        except Exception:
            await db.rollback()
            raise

        itinerary_response = await self.get_itinerary_by_id(db, itinerary.id)
        if itinerary_response is None:
            raise RuntimeError("Generated itinerary was persisted but could not be reloaded.")

        return itinerary_response

    async def get_itinerary_by_id(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID | None = None,
    ) -> ItineraryResponse | None:
        stmt = (
            select(Itinerary)
            .options(selectinload(Itinerary.steps).selectinload(ItineraryStep.poi))
            .where(Itinerary.id == itinerary_id)
        )
        if tourist_id is not None:
            stmt = stmt.where(Itinerary.tourist_id == tourist_id)

        result = await db.execute(stmt)
        itinerary = result.scalar_one_or_none()
        if itinerary is None:
            return None

        return self._to_response(itinerary)

    async def list_itineraries_by_tourist(
        self,
        db: AsyncSession,
        tourist_id: UUID,
    ) -> list[ItineraryResponse]:
        stmt = (
            select(Itinerary)
            .options(selectinload(Itinerary.steps).selectinload(ItineraryStep.poi))
            .where(Itinerary.tourist_id == tourist_id)
            .order_by(Itinerary.start_date.desc().nullslast(), Itinerary.title.asc())
        )
        result = await db.execute(stmt)
        return [self._to_response(itinerary) for itinerary in result.scalars().all()]

    async def delete_itinerary(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
    ) -> bool:
        try:
            result = await db.execute(
                delete(Itinerary)
                .where(Itinerary.id == itinerary_id)
                .where(Itinerary.tourist_id == tourist_id)
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return bool(result.rowcount)

    async def list_pois_for_itinerary(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
    ) -> list[POIResponse] | None:
        itinerary_exists = await db.execute(
            select(Itinerary.id)
            .where(Itinerary.id == itinerary_id)
            .where(Itinerary.tourist_id == tourist_id)
        )
        if itinerary_exists.scalar_one_or_none() is None:
            return None

        stmt = (
            select(
                POI,
                func.ST_Y(POI.location).label("latitude"),
                func.ST_X(POI.location).label("longitude"),
            )
            .join(ItineraryStep, ItineraryStep.poi_id == POI.id)
            .where(ItineraryStep.itinerary_id == itinerary_id)
            .order_by(ItineraryStep.step_order.asc())
        )
        result = await db.execute(stmt)

        responses: list[POIResponse] = []
        for poi, latitude, longitude in result.all():
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
                    opening_hours_text=poi.opening_hours_text,
                    visit_rules=poi.visit_rules,
                    category_ids=category_ids,
                    latitude=float(latitude),
                    longitude=float(longitude),
                )
            )

        return responses

    async def update_step(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
        step_id: UUID,
        step_in: ItineraryStepUpdate,
    ) -> ItineraryResponse | None:
        itinerary = await self._get_itinerary_model(db, itinerary_id, tourist_id)
        if itinerary is None:
            return None

        step = next((candidate for candidate in itinerary.steps if candidate.id == step_id), None)
        if step is None:
            return None

        if step_in.poi_id is not None:
            poi = await db.get(POI, step_in.poi_id)
            if poi is None:
                raise ValueError("POI not found.")
            step.poi_id = step_in.poi_id
        if step_in.arrival_time is not None:
            step.arrival_time = step_in.arrival_time
        if step_in.departure_time is not None:
            step.departure_time = step_in.departure_time
        if step_in.ai_context is not None:
            step.ai_context = step_in.ai_context

        try:
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return await self.get_itinerary_by_id(db, itinerary_id, tourist_id)

    async def delete_step(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
        step_id: UUID,
    ) -> ItineraryResponse | None:
        itinerary = await self._get_itinerary_model(db, itinerary_id, tourist_id)
        if itinerary is None:
            return None

        step = next((candidate for candidate in itinerary.steps if candidate.id == step_id), None)
        if step is None:
            return None

        try:
            await db.delete(step)
            await db.flush()

            remaining_steps = [candidate for candidate in itinerary.steps if candidate.id != step_id]
            for index, remaining_step in enumerate(sorted(remaining_steps, key=lambda item: item.step_order), start=1):
                remaining_step.step_order = index

            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return await self.get_itinerary_by_id(db, itinerary_id, tourist_id)

    async def reorder_steps(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
        step_ids: list[UUID],
    ) -> ItineraryResponse | None:
        itinerary = await self._get_itinerary_model(db, itinerary_id, tourist_id)
        if itinerary is None:
            return None

        current_step_ids = {step.id for step in itinerary.steps}
        requested_step_ids = set(step_ids)
        if current_step_ids != requested_step_ids or len(step_ids) != len(current_step_ids):
            raise ValueError("step_ids must contain every itinerary step exactly once.")

        steps_by_id = {step.id: step for step in itinerary.steps}

        try:
            for index, step_id in enumerate(step_ids, start=1):
                steps_by_id[step_id].step_order = -index
            await db.flush()

            for index, step_id in enumerate(step_ids, start=1):
                steps_by_id[step_id].step_order = index

            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return await self.get_itinerary_by_id(db, itinerary_id, tourist_id)

    def _to_response(self, itinerary: Itinerary) -> ItineraryResponse:
        return ItineraryResponse(
            id=itinerary.id,
            tourist_id=itinerary.tourist_id,
            title=itinerary.title,
            start_date=itinerary.start_date,
            end_date=itinerary.end_date,
            status=itinerary.status,
            steps=[
                ItineraryStepResponse(
                    id=step.id,
                    itinerary_id=step.itinerary_id,
                    poi_id=step.poi_id,
                    poi_nombre=step.poi.name if step.poi is not None else None,
                    poi_descripcion=step.poi.description if step.poi is not None else None,
                    step_order=step.step_order,
                    arrival_time=step.arrival_time,
                    departure_time=step.departure_time,
                    ai_context=step.ai_context,
                )
                for step in itinerary.steps
            ],
        )

    async def _get_itinerary_model(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
    ) -> Itinerary | None:
        stmt = (
            select(Itinerary)
            .options(selectinload(Itinerary.steps))
            .where(Itinerary.id == itinerary_id)
            .where(Itinerary.tourist_id == tourist_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_category_ids(self, db: AsyncSession, poi_id: UUID) -> list[int]:
        stmt = select(POICategory.category_id).where(POICategory.poi_id == poi_id)
        result = await db.execute(stmt)
        return list(result.scalars().all())
