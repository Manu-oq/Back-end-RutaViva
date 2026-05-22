from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ara_message import AraMessage
from app.models.ara_session import AraSession
from app.repositories.base import BaseRepository
from app.schemas.ara import AraMessageResponse, AraQuickReply

_UNSET = object()


class AraRepository(BaseRepository):
    async def create_session(
        self,
        db: AsyncSession,
        tourist_id: UUID,
        initial_query: str,
        lat: float | None,
        lon: float | None,
        radius: float | None,
        start_date: date | None,
        end_date: date | None,
        intent_data: dict[str, Any],
        preferences_data: dict[str, Any],
        candidate_poi_ids: list[UUID],
    ) -> AraSession:
        session = AraSession(
            tourist_id=tourist_id,
            status="clarifying",
            initial_query=initial_query,
            radius=radius,
            start_date=start_date,
            end_date=end_date,
            intent_data=intent_data,
            preferences_data=preferences_data,
            candidate_poi_ids=candidate_poi_ids,
        )
        session.set_coordinates(lat, lon)
        db.add(session)
        await db.flush()
        return session

    async def get_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        tourist_id: UUID,
    ) -> AraSession | None:
        stmt = (
            select(
                AraSession,
                func.ST_Y(AraSession.location).label("lat"),
                func.ST_X(AraSession.location).label("lon"),
            )
            .options(selectinload(AraSession.messages))
            .where(AraSession.id == session_id)
            .where(AraSession.tourist_id == tourist_id)
        )
        result = await db.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return None
        session, lat, lon = row
        session._lat = float(lat) if lat is not None else None
        session._lon = float(lon) if lon is not None else None
        return session

    async def add_message(
        self,
        db: AsyncSession,
        session_id: UUID,
        role: str,
        content: str,
        quick_replies: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AraMessage:
        message = AraMessage(
            session_id=session_id,
            role=role,
            content=content,
            quick_replies=quick_replies,
            message_metadata=metadata,
        )
        db.add(message)
        await db.flush()
        return message

    async def update_session_context(
        self,
        db: AsyncSession,
        session: AraSession,
        *,
        expected_version: int | None = None,
        status: str | None = None,
        intent_data: dict[str, Any] | None = None,
        preferences_data: dict[str, Any] | None = None,
        candidate_poi_ids: list[UUID] | None = None,
        generated_itinerary_id: UUID | None | object = _UNSET,
    ) -> bool:
        if expected_version is not None:
            sets: list[str] = []
            params: dict[str, Any] = {"id": session.id, "expected_version": expected_version}

            if status is not None:
                sets.append("status = :status")
                params["status"] = status
            if intent_data is not None:
                sets.append("intent_data = :intent_data")
                params["intent_data"] = json.dumps(intent_data)
            if preferences_data is not None:
                sets.append("preferences_data = :preferences_data")
                params["preferences_data"] = json.dumps(preferences_data)
            if candidate_poi_ids is not None:
                sets.append("candidate_poi_ids = :candidate_poi_ids")
                params["candidate_poi_ids"] = candidate_poi_ids
            if generated_itinerary_id is not _UNSET:
                sets.append("generated_itinerary_id = :generated_itinerary_id")
                params["generated_itinerary_id"] = generated_itinerary_id

            sets.append("version = version + 1")

            sql = f"UPDATE ara_sessions SET {', '.join(sets)} WHERE id = :id AND version = :expected_version RETURNING version"
            result = await db.execute(text(sql), params)
            row = result.fetchone()
            if row is None:
                return False

            new_version = row[0]
            session.version = new_version
            if status is not None:
                session.status = status
            if intent_data is not None:
                session.intent_data = intent_data
            if preferences_data is not None:
                session.preferences_data = preferences_data
            if candidate_poi_ids is not None:
                session.candidate_poi_ids = candidate_poi_ids
            if generated_itinerary_id is not _UNSET:
                session.generated_itinerary_id = generated_itinerary_id

            return True

        if status is not None:
            session.status = status
        if intent_data is not None:
            session.intent_data = intent_data
        if preferences_data is not None:
            session.preferences_data = preferences_data
        if candidate_poi_ids is not None:
            session.candidate_poi_ids = candidate_poi_ids
        if generated_itinerary_id is not _UNSET:
            session.generated_itinerary_id = generated_itinerary_id
        await db.flush()
        return True

    def to_message_response(self, message: AraMessage) -> AraMessageResponse:
        quick_replies = [AraQuickReply.model_validate(reply) for reply in (message.quick_replies or [])]
        return AraMessageResponse(
            id=message.id,
            session_id=message.session_id,
            role=message.role,
            content=message.content,
            quick_replies=quick_replies,
            metadata=message.message_metadata,
            created_at=message.created_at,
        )
