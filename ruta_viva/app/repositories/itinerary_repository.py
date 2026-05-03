from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.itinerary import Itinerary
from app.models.itinerary_step import ItineraryStep
from app.schemas.itinerary import GeneratedItinerary, ItineraryResponse, ItineraryStepResponse


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
