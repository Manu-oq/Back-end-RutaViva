from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.itinerary import Itinerary
from app.models.itinerary_step import ItineraryStep
from app.schemas.itinerary import GeneratedItinerary, ItineraryResponse


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

        return await self.get_itinerary_by_id(db, itinerary.id)

    async def get_itinerary_by_id(self, db: AsyncSession, itinerary_id: UUID) -> ItineraryResponse:
        stmt = (
            select(Itinerary)
            .options(selectinload(Itinerary.steps))
            .where(Itinerary.id == itinerary_id)
        )
        result = await db.execute(stmt)
        itinerary = result.scalar_one()
        return ItineraryResponse.model_validate(itinerary)
