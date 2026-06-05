from __future__ import annotations

from typing import Any

from app.models.ara_session import AraSession


def is_slot_filled(slot: dict[str, Any]) -> bool:
    slot_type = slot.get("type")
    status = slot.get("status")
    if slot_type == "meal":
        return status in ("filled", "requested")
    if slot_type == "activity":
        return status == "filled" and slot.get("poi_id") is not None
    return status in ("filled", "requested")


def are_all_slots_filled(session: AraSession) -> bool:
    preferences = dict(session.preferences_data or {})
    trip_draft = dict(preferences.get("trip_draft") or {})
    slots = trip_draft.get("slots", [])
    if not slots:
        return False
    return all(
        is_slot_filled(s)
        for s in slots
        if isinstance(s, dict)
    )
