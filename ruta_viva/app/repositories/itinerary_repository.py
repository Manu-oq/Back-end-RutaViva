from __future__ import annotations

import secrets
import string
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from app.core.exceptions import ItineraryNotEditableError
from app.core.time_utils import CHILE_TZ, to_chile_timezone
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.itinerary import Itinerary
from app.models.itinerary_step import ItineraryStep
from app.models.poi import POI
from app.models.poi_visit import POIVisit
from app.repositories.base import BaseRepository
from app.repositories.utils import build_poi_response_from_row, get_category_ids_batch
from app.schemas.itinerary import (
    GeneratedItinerary,
    ItineraryExportResponse,
    ItineraryExportStep,
    ItineraryResponse,
    ItineraryStepCreate,
    ItineraryStepResponse,
    ItineraryStepUpdate,
    ReorderStepsWithTimesRequest,
    RescheduleStepRequest,
)
from app.schemas.poi import POIResponse

SPANISH_WEEKDAYS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")


class ItineraryRepository(BaseRepository):
    @staticmethod
    def _today_in_chile() -> date:
        return datetime.now(CHILE_TZ).date()

    def _is_past_itinerary(self, itinerary: Itinerary) -> bool:
        return itinerary.end_date is not None and itinerary.end_date < self._today_in_chile()

    def _is_editable_itinerary(self, itinerary: Itinerary) -> bool:
        if itinerary.status in {"completed", "cancelled"}:
            return False
        return not self._is_past_itinerary(itinerary)

    def _ensure_itinerary_editable(self, itinerary: Itinerary) -> None:
        if not self._is_editable_itinerary(itinerary):
            raise ItineraryNotEditableError()

    @staticmethod
    def _validate_reorder_ids(
        current_step_ids: set[UUID],
        requested_step_ids: list[UUID],
        *,
        field_name: str,
    ) -> None:
        counts = Counter(requested_step_ids)
        duplicate_ids = [str(step_id) for step_id, count in counts.items() if count > 1]
        if duplicate_ids:
            raise ValueError(f"{field_name} contains duplicate step ids: {', '.join(duplicate_ids)}.")

        requested_set = set(requested_step_ids)
        missing_ids = [str(step_id) for step_id in sorted(current_step_ids - requested_set, key=str)]
        if missing_ids:
            raise ValueError(
                f"{field_name} is missing itinerary step ids: {', '.join(missing_ids)}."
            )

        unknown_ids = [str(step_id) for step_id in sorted(requested_set - current_step_ids, key=str)]
        if unknown_ids:
            raise ValueError(
                f"{field_name} contains step ids that do not belong to the itinerary: {', '.join(unknown_ids)}."
            )

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
                        name=step.name,
                        is_generic=step.is_generic,
                    )
                )

            db.add_all([
                POIVisit(
                    poi_id=step.poi_id,
                    visitor_id=tourist_id,
                    source="itinerary",
                )
                for step in ordered_steps
                if step.poi_id is not None and not step.is_generic
            ])

            await self._commit_or_rollback(db)
        except Exception:
            await db.rollback()
            raise

        return await self.get_itinerary_by_id(db, itinerary.id, tourist_id)

    async def mark_itinerary_abandoned(self, db: AsyncSession, itinerary_id: UUID) -> bool:
        """Mark an itinerary as cancelled (client disconnected after creation)."""
        itinerary = await db.get(Itinerary, itinerary_id)
        if itinerary is None:
            return False
        itinerary.status = "cancelled"
        await db.flush()
        return True

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
        offset: int = 0,
        limit: int = 20,
    ) -> list[ItineraryResponse]:
        stmt = (
            select(Itinerary)
            .options(selectinload(Itinerary.steps).selectinload(ItineraryStep.poi))
            .where(Itinerary.tourist_id == tourist_id)
            .order_by(Itinerary.start_date.desc().nullslast(), Itinerary.title.asc())
            .offset(offset)
            .limit(limit)
        )
        result = await db.execute(stmt)
        return [self._to_response(itinerary) for itinerary in result.scalars().all()]

    async def count_itineraries_by_tourist(
        self,
        db: AsyncSession,
        tourist_id: UUID,
    ) -> int:
        stmt = select(func.count(Itinerary.id)).where(Itinerary.tourist_id == tourist_id)
        result = await db.execute(stmt)
        return result.scalar_one()

    async def get_step_coordinates_batch(
        self,
        db: AsyncSession,
        step_ids: list[UUID],
    ) -> dict[UUID, tuple[float, float]]:
        if not step_ids:
            return {}
        stmt = (
            select(
                ItineraryStep.id,
                func.ST_Y(POI.location).label("lat"),
                func.ST_X(POI.location).label("lon"),
            )
            .join(POI, POI.id == ItineraryStep.poi_id)
            .where(ItineraryStep.id.in_(step_ids))
        )
        result = await db.execute(stmt)
        return {step_id: (float(lat), float(lon)) for step_id, lat, lon in result.all()}

    async def delete_itinerary(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
    ) -> bool:
        itinerary = await self._get_itinerary_model(db, itinerary_id, tourist_id)
        if itinerary is None:
            return False

        try:
            result = await db.execute(
                delete(Itinerary)
                .where(Itinerary.id == itinerary_id)
                .where(Itinerary.tourist_id == tourist_id)
            )
            await self._commit_or_rollback(db)
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
        stmt = (
            select(
                POI,
                func.ST_Y(POI.location).label("latitude"),
                func.ST_X(POI.location).label("longitude"),
            )
            .join(ItineraryStep, ItineraryStep.poi_id == POI.id)
            .join(Itinerary, Itinerary.id == ItineraryStep.itinerary_id)
            .where(ItineraryStep.itinerary_id == itinerary_id)
            .where(Itinerary.tourist_id == tourist_id)
            .order_by(ItineraryStep.step_order.asc())
        )
        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            exists_stmt = select(Itinerary.id).where(
                Itinerary.id == itinerary_id,
                Itinerary.tourist_id == tourist_id,
            )
            exists_result = await db.execute(exists_stmt)
            if exists_result.scalar_one_or_none() is None:
                return None
            return []

        category_map = await get_category_ids_batch(db, [poi.id for poi, _, _ in rows])
        responses: list[POIResponse] = []
        for poi, latitude, longitude in rows:
            responses.append(
                build_poi_response_from_row(poi, latitude, longitude, category_map.get(poi.id, []))
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
        self._ensure_itinerary_editable(itinerary)

        step = next((candidate for candidate in itinerary.steps if candidate.id == step_id), None)
        if step is None:
            return None

        if step_in.poi_id is not None:
            poi = await db.get(POI, step_in.poi_id)
            if poi is None:
                raise ValueError("POI not found.")
            step.poi_id = step_in.poi_id
            step.is_generic = False
        if step_in.name is not None:
            step.name = step_in.name
        if step_in.is_generic is not None:
            step.is_generic = step_in.is_generic
            if step.is_generic:
                step.poi_id = None
        if step_in.arrival_time is not None:
            step.arrival_time = step_in.arrival_time
        if step_in.departure_time is not None:
            step.departure_time = step_in.departure_time
        if step_in.ai_context is not None:
            step.ai_context = step_in.ai_context

        await self._commit_or_rollback(db)

        return await self.get_itinerary_by_id(db, itinerary.id, tourist_id)

    async def add_step(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
        step_data: ItineraryStepCreate,
    ) -> ItineraryResponse | None:
        itinerary = await self._get_itinerary_model(db, itinerary_id, tourist_id)
        if itinerary is None:
            return None
        self._ensure_itinerary_editable(itinerary)

        if step_data.is_generic:
            if not step_data.name:
                raise ValueError("name is required for generic itinerary steps.")
        else:
            if step_data.poi_id is None:
                raise ValueError("poi_id is required for non-generic itinerary steps.")
            poi = await db.get(POI, step_data.poi_id)
            if poi is None:
                raise ValueError("POI not found.")

        if step_data.arrival_time is not None and step_data.departure_time is not None:
            if step_data.arrival_time >= step_data.departure_time:
                raise ValueError("arrival_time must be before departure_time.")

        if step_data.arrival_time is not None and itinerary.start_date is not None:
            if step_data.arrival_time.date() < itinerary.start_date:
                raise ValueError("arrival_time is before itinerary start_date.")
        if step_data.departure_time is not None and itinerary.end_date is not None:
            if step_data.departure_time.date() > itinerary.end_date:
                raise ValueError("departure_time is after itinerary end_date.")

        existing_orders = [s.step_order for s in itinerary.steps]
        max_order = max(existing_orders) if existing_orders else 0

        step = ItineraryStep(
            itinerary_id=itinerary_id,
            poi_id=None if step_data.is_generic else step_data.poi_id,
            name=step_data.name,
            is_generic=step_data.is_generic,
            step_order=max_order + 1,
            arrival_time=step_data.arrival_time,
            departure_time=step_data.departure_time,
            ai_context=step_data.ai_context,
        )
        db.add(step)

        await self._commit_or_rollback(db)

        return await self.get_itinerary_by_id(db, itinerary.id, tourist_id)

    async def update_status(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
        new_status: str,
    ) -> ItineraryResponse | None:
        itinerary = await self._get_itinerary_model(db, itinerary_id, tourist_id)
        if itinerary is None:
            return None
        self._ensure_itinerary_editable(itinerary)

        itinerary.status = new_status

        await self._commit_or_rollback(db)

        return await self.get_itinerary_by_id(db, itinerary.id, tourist_id)

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
        self._ensure_itinerary_editable(itinerary)

        step = next((candidate for candidate in itinerary.steps if candidate.id == step_id), None)
        if step is None:
            return None

        try:
            remaining_steps = sorted(
                [candidate for candidate in itinerary.steps if candidate.id != step_id],
                key=lambda item: item.step_order,
            )

            await db.delete(step)
            await db.flush()

            # Two-phase reorder:
            # The DB has a unique constraint on (itinerary_id, step_order). If we
            # compact orders directly (for example 13 -> 12 while another row is
            # still 12), PostgreSQL checks the constraint per statement/flush and
            # can raise a transient UniqueViolation. Move all remaining rows to a
            # temporary high-offset namespace first, flush, then assign the final
            # compact positive order.
            OFFSET = 100_000
            for index, remaining_step in enumerate(remaining_steps, start=1):
                remaining_step.step_order = OFFSET + index
            await db.flush()

            for index, remaining_step in enumerate(remaining_steps, start=1):
                remaining_step.step_order = index

            await self._commit_or_rollback(db)
        except Exception:
            await db.rollback()
            raise

        return await self.get_itinerary_by_id(db, itinerary.id, tourist_id)

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
        self._ensure_itinerary_editable(itinerary)

        current_step_ids = {step.id for step in itinerary.steps}
        self._validate_reorder_ids(current_step_ids, step_ids, field_name="step_ids")

        steps_by_id = {step.id: step for step in itinerary.steps}

        OFFSET = 100_000
        try:
            for index, step_id in enumerate(step_ids, start=1):
                steps_by_id[step_id].step_order = OFFSET + index
            await db.flush()

            for index, step_id in enumerate(step_ids, start=1):
                steps_by_id[step_id].step_order = index

            await self._commit_or_rollback(db)
        except Exception:
            await db.rollback()
            raise

        return await self.get_itinerary_by_id(db, itinerary.id, tourist_id)

    async def reschedule_step(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
        step_id: UUID,
        payload: RescheduleStepRequest,
    ) -> ItineraryResponse | None:
        itinerary = await self._get_itinerary_model(db, itinerary_id, tourist_id)
        if itinerary is None:
            return None
        self._ensure_itinerary_editable(itinerary)

        target = next((s for s in itinerary.steps if s.id == step_id), None)
        if target is None:
            return None

        new_arrival = to_chile_timezone(payload.arrival_time)

        old_departure = to_chile_timezone(target.departure_time)

        if payload.duration_minutes is not None:
            new_departure = new_arrival + timedelta(minutes=payload.duration_minutes)
        elif old_departure is not None:
            duration = old_departure - (target.arrival_time if target.arrival_time else new_arrival)
            new_departure = new_arrival + max(duration, timedelta(minutes=15))
        else:
            new_departure = new_arrival + timedelta(minutes=60)

        target.arrival_time = new_arrival
        target.departure_time = new_departure

        target_day = new_arrival.date()
        old_arrival = to_chile_timezone(target.arrival_time)

        subsequent_on_day = sorted(
            [
                s for s in itinerary.steps
                if s.id != target.id
                and s.arrival_time is not None
                and to_chile_timezone(s.arrival_time).date() == target_day
            ],
            key=lambda s: s.arrival_time,
        )

        if old_departure is not None:
            old_departure_normalized = to_chile_timezone(old_departure)
            shift_delta = new_departure - old_departure_normalized
        else:
            shift_delta = timedelta(0)

        if shift_delta != timedelta(0):
            for step in subsequent_on_day:
                step_arrival = to_chile_timezone(step.arrival_time)
                if step_arrival is not None:
                    if step_arrival >= old_departure_normalized or shift_delta < timedelta(0):
                        step.arrival_time = step_arrival + shift_delta
                        if step.departure_time is not None:
                            step.departure_time = to_chile_timezone(step.departure_time) + shift_delta

        await self._commit_or_rollback(db)

        return await self.get_itinerary_by_id(db, itinerary.id, tourist_id)

    async def reorder_steps_with_times(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
        payload: ReorderStepsWithTimesRequest,
    ) -> ItineraryResponse | None:
        itinerary = await self._get_itinerary_model(db, itinerary_id, tourist_id)
        if itinerary is None:
            return None
        self._ensure_itinerary_editable(itinerary)

        start_date = itinerary.start_date
        current_step_ids = {step.id for step in itinerary.steps}
        self._validate_reorder_ids(
            current_step_ids,
            [step_position.step_id for step_position in payload.steps],
            field_name="steps",
        )

        steps_by_id = {step.id: step for step in itinerary.steps}

        day_groups: dict[int, list[StepDayPosition]] = {}
        for sp in payload.steps:
            day_groups.setdefault(sp.day_index, []).append(sp)
        for day_index in day_groups:
            day_groups[day_index].sort(key=lambda sp: sp.position)

        DEFAULT_START_HOUR = 9
        DEFAULT_START_MINUTE = 0
        GAP_MINUTES = 15

        try:
            for day_index, positions in day_groups.items():
                if start_date is not None:
                    target_date = start_date + timedelta(days=day_index - 1)
                elif itinerary.steps and itinerary.steps[0].arrival_time is not None:
                    first_arrival = to_chile_timezone(itinerary.steps[0].arrival_time)
                    target_date = first_arrival.date() + timedelta(days=day_index - 1)
                else:
                    target_date = None

                cursor_minutes = DEFAULT_START_HOUR * 60 + DEFAULT_START_MINUTE

                for sp in positions:
                    step = steps_by_id[sp.step_id]

                    old_arrival = step.arrival_time
                    old_departure = step.departure_time
                    duration: timedelta = timedelta(hours=1)

                    if old_arrival is not None and old_departure is not None:
                        a = to_chile_timezone(old_arrival)
                        d = to_chile_timezone(old_departure)
                        computed_duration = d - a
                        if computed_duration >= timedelta(minutes=5):
                            duration = computed_duration

                    if target_date is not None:
                        new_arrival = datetime(
                            target_date.year, target_date.month, target_date.day,
                            cursor_minutes // 60, cursor_minutes % 60, 0,
                            tzinfo=CHILE_TZ,
                        )
                    elif old_arrival is not None:
                        a = to_chile_timezone(old_arrival)
                        new_arrival = a.replace(
                            hour=cursor_minutes // 60,
                            minute=cursor_minutes % 60,
                            second=0,
                            microsecond=0,
                        )
                    else:
                        new_arrival = None

                    new_departure = new_arrival + duration if new_arrival is not None else None

                    step.arrival_time = new_arrival
                    step.departure_time = new_departure

                    if new_departure is not None:
                        cursor_minutes = (new_departure.hour * 60 + new_departure.minute) + GAP_MINUTES

            OFFSET = 100_000
            for index, sp in enumerate(payload.steps, start=1):
                steps_by_id[sp.step_id].step_order = OFFSET + index
            await db.flush()

            for index, sp in enumerate(payload.steps, start=1):
                steps_by_id[sp.step_id].step_order = index

            await self._commit_or_rollback(db)
        except Exception:
            await db.rollback()
            raise

        return await self.get_itinerary_by_id(db, itinerary.id, tourist_id)

    async def get_export_data(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
    ) -> ItineraryExportResponse | None:
        stmt = (
            select(Itinerary)
            .options(selectinload(Itinerary.steps).selectinload(ItineraryStep.poi))
            .where(Itinerary.id == itinerary_id)
            .where(Itinerary.tourist_id == tourist_id)
        )
        result = await db.execute(stmt)
        itinerary = result.scalar_one_or_none()
        if itinerary is None:
            return None

        coords = await self.get_step_coordinates_batch(
            db, [s.id for s in itinerary.steps]
        )
        return self._to_export_response(itinerary, coords)

    async def get_export_data_by_public_id(
        self,
        db: AsyncSession,
        public_id: str,
    ) -> ItineraryExportResponse | None:
        itinerary = await self.get_itinerary_by_public_id(db, public_id)
        if itinerary is None:
            return None

        coords = await self.get_step_coordinates_batch(
            db, [s.id for s in itinerary.steps]
        )
        return self._to_export_response(itinerary, coords)

    def _to_export_response(
        self,
        itinerary: Itinerary,
        coords: dict[UUID, tuple[float, float]],
    ) -> ItineraryExportResponse:
        start_date = itinerary.start_date
        steps: list[ItineraryExportStep] = []
        for step in itinerary.steps:
            arrival_time = to_chile_timezone(step.arrival_time)
            departure_time = to_chile_timezone(step.departure_time)
            day_date = arrival_time.date() if arrival_time is not None else None
            day_index = None
            if day_date is not None and start_date is not None:
                day_index = (day_date - start_date).days + 1

            lat, lon = coords.get(step.id, (None, None))

            steps.append(
                ItineraryExportStep(
                    day=day_index or 1,
                    date=day_date.isoformat() if day_date is not None else "",
                    order=step.step_order,
                    poi_name=step.name if step.is_generic else (step.poi.name if step.poi is not None else ""),
                    poi_description=None if step.is_generic else (step.poi.description if step.poi is not None else None),
                    poi_address=None,
                    arrival_time=arrival_time.strftime("%H:%M") if arrival_time is not None else None,
                    departure_time=departure_time.strftime("%H:%M") if departure_time is not None else None,
                    tips=None,
                    weather=None,
                    latitude=lat,
                    longitude=lon,
                )
            )

        total_days = 1
        if start_date is not None and itinerary.end_date is not None:
            total_days = (itinerary.end_date - start_date).days + 1

        generated_at = datetime.now(timezone.utc).isoformat()

        return ItineraryExportResponse(
            title=itinerary.title,
            start_date=start_date.isoformat() if start_date is not None else None,
            end_date=itinerary.end_date.isoformat() if itinerary.end_date is not None else None,
            steps=steps,
            total_days=total_days,
            total_steps=len(steps),
            generated_at=generated_at,
        )

    async def get_itinerary_by_public_id(
        self,
        db: AsyncSession,
        public_id: str,
    ) -> Itinerary | None:
        stmt = (
            select(Itinerary)
            .options(selectinload(Itinerary.steps).selectinload(ItineraryStep.poi))
            .where(Itinerary.public_id == public_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def generate_public_id(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
    ) -> str | None:
        itinerary = await self._get_itinerary_model(db, itinerary_id, tourist_id)
        if itinerary is None:
            return None

        if itinerary.public_id is not None:
            return itinerary.public_id

        alphabet = string.ascii_letters + string.digits
        for _ in range(10):
            candidate = "".join(secrets.choice(alphabet) for _ in range(8))
            exists = await db.execute(
                select(Itinerary.id).where(Itinerary.public_id == candidate)
            )
            if exists.scalar_one_or_none() is None:
                itinerary.public_id = candidate
                await self._commit_or_rollback(db)
                return candidate

        raise ValueError("Could not generate a unique public_id after 10 attempts")

    async def clear_public_id(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
    ) -> bool:
        itinerary = await self._get_itinerary_model(db, itinerary_id, tourist_id)
        if itinerary is None:
            return False

        itinerary.public_id = None
        await self._commit_or_rollback(db)
        return True

    async def record_step_visit(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
        step_id: UUID,
        note: str | None = None,
    ) -> StepVisitResponse | None:
        itinerary = await self._get_itinerary_model(db, itinerary_id, tourist_id)
        if itinerary is None:
            return None

        step = next((s for s in itinerary.steps if s.id == step_id), None)
        if step is None:
            return None

        if step.is_generic or step.poi_id is None:
            raise ValueError("Generic itinerary steps cannot be marked as POI visits.")

        existing = await db.execute(
            select(POIVisit).where(
                POIVisit.poi_id == step.poi_id,
                POIVisit.visitor_id == tourist_id,
                POIVisit.source == "itinerary",
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError("This step has already been marked as visited.")

        visit = POIVisit(
            poi_id=step.poi_id,
            visitor_id=tourist_id,
            source="itinerary",
            note=note,
        )
        db.add(visit)
        await self._commit_or_rollback(db)
        await db.refresh(visit)

        return StepVisitResponse(
            id=visit.id,
            step_id=step.id,
            poi_id=visit.poi_id,
            visited_at=visit.created_at,
            source=visit.source,
            note=visit.note,
        )

    async def get_visits_for_itinerary(
        self,
        db: AsyncSession,
        itinerary_id: UUID,
        tourist_id: UUID,
    ) -> list[StepVisitResponse] | None:
        itinerary = await self._get_itinerary_model(db, itinerary_id, tourist_id)
        if itinerary is None:
            return None

        poi_ids = [step.poi_id for step in itinerary.steps if step.poi_id is not None and not step.is_generic]
        if not poi_ids:
            return []

        step_by_poi = {step.poi_id: step.id for step in itinerary.steps if step.poi_id is not None and not step.is_generic}

        result = await db.execute(
            select(POIVisit)
            .where(
                POIVisit.poi_id.in_(poi_ids),
                POIVisit.visitor_id == tourist_id,
            )
            .order_by(POIVisit.created_at.desc())
        )
        visits = result.scalars().all()

        return [
            StepVisitResponse(
                id=visit.id,
                step_id=step_by_poi.get(visit.poi_id),
                poi_id=visit.poi_id,
                visited_at=visit.created_at,
                source=visit.source,
                note=visit.note,
            )
            for visit in visits
        ]

    def _to_response(self, itinerary: Itinerary) -> ItineraryResponse:
        start_date = itinerary.start_date
        is_past = self._is_past_itinerary(itinerary)
        is_editable = self._is_editable_itinerary(itinerary)
        return ItineraryResponse(
            id=itinerary.id,
            tourist_id=itinerary.tourist_id,
            title=itinerary.title,
            start_date=start_date,
            end_date=itinerary.end_date,
            status=itinerary.status,
            is_past=is_past,
            is_editable=is_editable,
            steps=[
                self._step_to_response(step, start_date)
                for step in itinerary.steps
            ],
        )

    def _step_to_response(self, step: ItineraryStep, start_date: date | None) -> ItineraryStepResponse:
        arrival_time = to_chile_timezone(step.arrival_time)
        departure_time = to_chile_timezone(step.departure_time)
        day_date = arrival_time.date() if arrival_time is not None else None
        day_index = None
        day_label = None

        if day_date is not None:
            if start_date is not None:
                day_index = (day_date - start_date).days + 1
            day_label = f"{SPANISH_WEEKDAYS[day_date.weekday()]} {day_date.day:02d}"

        return ItineraryStepResponse(
            id=step.id,
            itinerary_id=step.itinerary_id,
            poi_id=step.poi_id,
            name=step.name,
            is_generic=step.is_generic,
            lat=None,
            lon=None,
            poi_name=step.name if step.is_generic else (step.poi.name if step.poi is not None else None),
            poi_description=None if step.is_generic else (step.poi.description if step.poi is not None else None),
            step_order=step.step_order,
            arrival_time=arrival_time,
            departure_time=departure_time,
            day_index=day_index,
            day_date=day_date,
            day_label=day_label,
            ai_context=step.ai_context,
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
