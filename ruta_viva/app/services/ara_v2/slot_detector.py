from __future__ import annotations

import re
from typing import Any

MEAL_PATTERNS: dict[str, list[str]] = {
    "breakfast": ["desayuno", "desayunar", "desayune"],
    "lunch": ["almuerzo", "almorzar", "almuerce", "comida", "comer", "comida al mediodía"],
    "once": ["once", "merienda", "tarde comida"],
    "dinner": ["cena", "cenar", "cene"],
}

PERIOD_KEYWORDS: dict[str, list[str]] = {
    "morning": ["mañana", "manana", "temprano", "por la mañana", "en la mañana"],
    "afternoon": ["tarde", "por la tarde", "en la tarde"],
    "night": ["noche", "por la noche", "en la noche"],
}

EMPTY_SLOT_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"no\s+(?:s[eé]|se)\s+qu[eé]\s+hacer",
        r"qu[eé]\s+me\s+recomiendas",
        r"qu[eé]\s+me\s+sugieres",
        r"no\s+conozco\s+nada",
        r"no\s+cacho\s+nada",
        r"no\s+tengo\s+idea",
        r"alguna\s+sugerencia",
        r"alg[uú]n\s+plan",
        r"no\s+se\s+me\s+ocurre",
        r"que\s+mas\s+puedo\s+hacer",
        r"que\s+m[aá]s\s+hay",
        r"que\s+otro\s+lugar",
        r"que\s+otra\s+cosa",
    )
]

TIME_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"a\s+las\s+(\d{1,2}(?::\d{2})?)",
        r"tipo\s+(\d{1,2}(?::\d{2})?)",
        r"como\s+a\s+las\s+(\d{1,2}(?::\d{2})?)",
        r"a\s+eso\s+de\s+las\s+(\d{1,2}(?::\d{2})?)",
        r"(\d{1,2}:\d{2})",
    )
]


def _extract_time_near(text: str, keyword: str) -> str | None:
    idx = text.find(keyword)
    if idx == -1:
        return None
    start = max(0, idx - 50)
    end = min(len(text), idx + len(keyword) + 60)
    segment = text[start:end]
    for pattern in TIME_PATTERNS:
        match = pattern.search(segment)
        if match:
            return match.group(1)
    return None


def detect_slots(message: str) -> list[dict[str, Any]]:
    normalized = message.lower().strip()
    slots: list[dict[str, Any]] = []
    has_meal = False

    for meal_type, keywords in MEAL_PATTERNS.items():
        found_kw = next((kw for kw in keywords if kw in normalized), None)
        if found_kw is None:
            continue
        has_meal = True
        time = _extract_time_near(normalized, found_kw)
        slots.append({
            "type": "meal",
            "meal_type": meal_type,
            "time": time,
            "status": "requested",
            "poi_id": None,
        })

    for period, keywords in PERIOD_KEYWORDS.items():
        if any(kw in normalized for kw in keywords):
            already_as_meal = has_meal and period in ("afternoon", "night")
            if already_as_meal:
                continue
            slots.append({
                "type": "activity",
                "period": period,
                "status": "empty" if _is_empty_slot(normalized) else "requested",
            })

    if _is_empty_slot(normalized):
        has_specific_period = any(s["type"] == "activity" for s in slots)
        if not has_specific_period:
            slots.append({
                "type": "activity",
                "period": None,
                "status": "empty",
            })

    return slots


def _is_empty_slot(text: str) -> bool:
    return any(pattern.search(text) for pattern in EMPTY_SLOT_PATTERNS)
