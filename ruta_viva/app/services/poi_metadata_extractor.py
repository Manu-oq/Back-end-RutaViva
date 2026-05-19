from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any


WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SPANISH_WEEKDAY_ALIASES = {
    "lunes": "mon",
    "martes": "tue",
    "miercoles": "wed",
    "miércoles": "wed",
    "jueves": "thu",
    "viernes": "fri",
    "sabado": "sat",
    "sábado": "sat",
    "domingo": "sun",
}
RANGE_ALIASES = {
    "lunes a viernes": ("mon", "fri"),
    "lunes a sabado": ("mon", "sat"),
    "lunes a sábado": ("mon", "sat"),
    "martes a domingo": ("tue", "sun"),
    "todos los dias": ("mon", "sun"),
    "todos los días": ("mon", "sun"),
}


@dataclass
class ExtractedMetadata:
    description: str | None = None
    opening_hours_text: str | None = None
    opening_hours_structured: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    services: dict[str, dict[str, Any]] = field(default_factory=dict)
    access: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._hidden_depth += 1
        if tag in {"p", "br", "li", "div", "section", "article", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._hidden_depth > 0:
            self._hidden_depth -= 1
        if tag in {"p", "li", "div", "section", "article", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._hidden_depth == 0:
            self.parts.append(data)

    def text(self) -> str:
        return clean_text(" ".join(self.parts)) or ""


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def html_to_text(html: str) -> str:
    parser = _TextHTMLParser()
    parser.feed(html)
    return parser.text()


def extract_metadata_from_text(
    *,
    poi_name: str,
    category_ids: list[int],
    raw_text: str,
    source_url: str | None = None,
    provider: str = "public_text",
) -> ExtractedMetadata:
    text = clean_text(raw_text) or ""
    metadata = ExtractedMetadata()

    description = extract_description(text, poi_name)
    if description:
        metadata.description = description
        metadata.evidence.append(_evidence("description", provider, source_url, "inferred"))

    hours_text = extract_opening_hours_text(text)
    if hours_text:
        metadata.opening_hours_text = hours_text
        metadata.opening_hours_structured = parse_opening_hours_text(hours_text)
        metadata.evidence.append(_evidence("opening_hours", provider, source_url, "inferred"))

    metadata.services = infer_services_from_text(text)
    metadata.access = infer_access_from_text(text)
    for key, value in metadata.services.items():
        if value.get("evidence_level") != "unknown":
            metadata.evidence.append(_evidence(f"services.{key}", provider, source_url, value["evidence_level"]))
    for key, value in metadata.access.items():
        if value.get("evidence_level") != "unknown":
            metadata.evidence.append(_evidence(f"access.{key}", provider, source_url, value["evidence_level"]))

    return metadata


def merge_enrichment_into_visit_rules(
    visit_rules: dict[str, Any] | None,
    extracted: ExtractedMetadata,
    *,
    provider: str,
    source_url: str | None,
    confidence: float,
) -> dict[str, Any]:
    rules = dict(visit_rules or {})
    enrichment = dict(rules.get("enrichment") or {})
    sources = list(enrichment.get("sources") or [])
    if source_url and not any(source.get("url") == source_url for source in sources):
        sources.append(
            {
                "url": source_url,
                "provider": provider,
                "fetched_at": datetime.utcnow().isoformat(),
                "confidence": confidence,
            }
        )
    enrichment["sources"] = sources
    enrichment["last_enriched_at"] = datetime.utcnow().isoformat()
    rules["enrichment"] = enrichment

    if extracted.opening_hours_structured:
        rules["opening_hours_structured"] = extracted.opening_hours_structured
    if extracted.services:
        current_services = dict(rules.get("services") or {})
        current_services.update(_prefer_known_values(current_services, extracted.services))
        rules["services"] = current_services
    if extracted.access:
        current_access = dict(rules.get("access") or {})
        current_access.update(_prefer_known_values(current_access, extracted.access))
        rules["access"] = current_access
    if extracted.evidence:
        evidence = list(rules.get("evidence") or [])
        evidence.extend(extracted.evidence)
        rules["evidence"] = evidence[-50:]

    rules.setdefault("confidence", "enriched" if confidence >= 0.75 else "inferred")
    return rules


def _split_opening_hours_segments(text: str) -> list[str]:
    segments = [text]
    for separator in ("; ", ".\n", ". "):
        expanded: list[str] = []
        for segment in segments:
            expanded.extend(part.strip() for part in segment.split(separator) if part.strip())
        segments = expanded
    if len(segments) <= 1:
        normalized_text = _normalize(text)
        day_names_in_text = [alias for alias in SPANISH_WEEKDAY_ALIASES if _normalize(alias) in normalized_text]
        if day_names_in_text:
            parts = [text]
            for day_name in sorted(day_names_in_text, key=lambda d: text.lower().index(_normalize(d)), reverse=True):
                expanded_parts: list[str] = []
                for part in parts:
                    lower_part = part.lower()
                    idx = lower_part.find(day_name)
                    if idx > 0:
                        before = part[:idx].strip()
                        after = part[idx:].strip()
                        if before:
                            expanded_parts.append(before)
                        expanded_parts.append(after)
                    else:
                        expanded_parts.append(part)
                parts = expanded_parts
            return parts
    return segments


def _has_cerrado(normalized: str) -> bool:
    return any(term in normalized for term in ("cerrado", "no abre", "no abren"))


def parse_opening_hours_text(value: str | None) -> dict[str, list[dict[str, str]]]:
    text = clean_text(value)
    if not text:
        return {}

    segments = _split_opening_hours_segments(text)
    result: dict[str, list[dict[str, str]]] = {}
    any_day_detected = False

    for segment in segments:
        normalized = _normalize(segment)
        time_ranges = _extract_time_ranges(normalized)
        days = _extract_days(normalized)

        if not days:
            if time_ranges:
                days = list(WEEKDAY_KEYS)
            elif _has_cerrado(normalized):
                for key in WEEKDAY_KEYS:
                    if key not in result:
                        result[key] = []
                any_day_detected = True
            continue

        any_day_detected = True
        if time_ranges:
            for day in days:
                result[day] = [{"open": start, "close": end} for start, end in time_ranges]
        elif _has_cerrado(normalized):
            for day in days:
                result[day] = []

    if not any_day_detected:
        return {}
    return result


def extract_opening_hours_text(text: str) -> str | None:
    candidates: list[str] = []
    patterns = [
        r"(?i)(?:horario|abierto|atenci[oó]n)[^.\n]{0,120}(?:\d{1,2}[:.]\d{2}|\d{1,2}\s*(?:am|pm))[^.\n]{0,80}",
        r"(?i)(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo|todos los d[ií]as)[^.\n]{0,120}\d{1,2}[:.]\d{2}[^.\n]{0,80}",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            candidate = clean_text(match.group(0))
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    if not candidates:
        return None
    return candidates[0][:500]


def extract_description(text: str, poi_name: str) -> str | None:
    cleaned = clean_text(text)
    if not cleaned:
        return None
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    useful: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 45:
            continue
        lower = sentence.lower()
        if any(term in lower for term in ("cookie", "javascript", "derechos reservados", "privacy", "captcha")):
            continue
        useful.append(sentence)
        if len(" ".join(useful)) > 350:
            break
    description = clean_text(" ".join(useful)) or cleaned[:350]
    return description[:700] if len(description) >= 60 else None


def infer_services_from_text(text: str) -> dict[str, dict[str, Any]]:
    normalized = _normalize(text)
    return {
        "bathrooms": _signal(
            normalized,
            confirmed_terms=("baños", "banos", "servicios higienicos", "servicio higienico", "toilets"),
        ),
        "parking": _signal(
            normalized,
            confirmed_terms=("estacionamiento", "parking", "aparcamiento"),
        ),
        "wheelchair_access": _signal(
            normalized,
            confirmed_terms=("accesibilidad universal", "silla de ruedas", "wheelchair", "acceso inclusivo"),
        ),
        "family_friendly": _signal(
            normalized,
            confirmed_terms=("apto para niños", "apto para ninos", "familiar", "familias", "family friendly"),
            inferred_terms=("juegos infantiles", "niños", "ninos"),
        ),
    }


def infer_access_from_text(text: str) -> dict[str, dict[str, Any]]:
    normalized = _normalize(text)
    return {
        "road_type": _road_type_signal(normalized),
        "vehicle_recommended": _signal(
            normalized,
            confirmed_terms=("vehiculo recomendado", "vehículo recomendado", "solo en auto", "4x4"),
            inferred_terms=("camino de ripio", "ripio", "camino rural"),
        ),
    }


def _extract_days(normalized: str) -> list[str]:
    for label, (start, end) in RANGE_ALIASES.items():
        if _normalize(label) in normalized:
            return _weekday_range(start, end)

    days: list[str] = []
    for alias, key in SPANISH_WEEKDAY_ALIASES.items():
        if _normalize(alias) in normalized and key not in days:
            days.append(key)
    return days


def _extract_time_ranges(normalized: str) -> list[tuple[str, str]]:
    ranges: list[tuple[str, str]] = []
    pattern = r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?\s*(?:a|hasta|-|–)\s*(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?"
    for match in re.finditer(pattern, normalized):
        start = _format_time(match.group(1), match.group(2), match.group(3))
        end = _format_time(match.group(4), match.group(5), match.group(6))
        if start and end and start != end:
            ranges.append((start, end))
    return ranges[:3]


def _format_time(hour_text: str, minute_text: str | None, meridiem: str | None) -> str | None:
    try:
        hour = int(hour_text)
        minute = int(minute_text or "0")
    except ValueError:
        return None
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def _weekday_range(start: str, end: str) -> list[str]:
    start_index = WEEKDAY_KEYS.index(start)
    end_index = WEEKDAY_KEYS.index(end)
    if start_index <= end_index:
        return list(WEEKDAY_KEYS[start_index : end_index + 1])
    return list(WEEKDAY_KEYS[start_index:]) + list(WEEKDAY_KEYS[: end_index + 1])


def _normalize(text: str) -> str:
    replacements = str.maketrans("áéíóúüñ", "aeiouun")
    return text.lower().translate(replacements)


def _signal(
    normalized: str,
    *,
    confirmed_terms: tuple[str, ...],
    inferred_terms: tuple[str, ...] = (),
) -> dict[str, Any]:
    if any(_normalize(term) in normalized for term in confirmed_terms):
        return {"evidence_level": "confirmed"}
    if any(_normalize(term) in normalized for term in inferred_terms):
        return {"evidence_level": "inferred"}
    return {"evidence_level": "unknown"}


def _road_type_signal(normalized: str) -> dict[str, Any]:
    if "ripio" in normalized:
        return {"value": "gravel", "evidence_level": "confirmed"}
    if "paviment" in normalized or "asfalto" in normalized:
        return {"value": "paved", "evidence_level": "confirmed"}
    return {"value": "unknown", "evidence_level": "unknown"}


def _evidence(field: str, provider: str, source_url: str | None, evidence_level: str) -> dict[str, Any]:
    return {
        "field": field,
        "provider": provider,
        "source_url": source_url,
        "evidence_level": evidence_level,
        "observed_at": datetime.utcnow().isoformat(),
    }


def _prefer_known_values(
    current: dict[str, dict[str, Any]],
    incoming: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    priority = {"unknown": 0, "inferred": 1, "confirmed": 2}
    for key, incoming_value in incoming.items():
        current_value = current.get(key)
        if current_value is None:
            merged[key] = incoming_value
            continue
        current_level = str(current_value.get("evidence_level", "unknown"))
        incoming_level = str(incoming_value.get("evidence_level", "unknown"))
        merged[key] = incoming_value if priority.get(incoming_level, 0) >= priority.get(current_level, 0) else current_value
    return merged
