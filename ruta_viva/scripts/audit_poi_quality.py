from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import app.db.models  # noqa: F401
from app.db.session import AsyncSessionLocal
from app.models.poi import POI
from app.models.poi_category import POICategory

GASTRONOMY_CATEGORY_ID = 2
THERMAL_CATEGORY_ID = 9
NATURE_CATEGORY_ID = 1

FOOD_NAME_TERMS = ("cociner", "restaurant", "restaurante", "pizzer", "pizza", "café", "cafe", "comida", "empanad")
THERMAL_TERMS = ("terma", "termas", "thermal", "piscina termal", "spa")
GENERIC_DESCRIPTION_TERMS = (
    "punto de interés turístico",
    "ubicado en la región de la araucanía",
    "referencia territorial reportada por osm",
)


def audit_poi(poi: POI, category_ids: list[int]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    name = poi.name.lower()
    description = (poi.description or "").lower()
    visit_rules = poi.visit_rules or {}

    if not poi.opening_hours_text and not visit_rules.get("opening_hours_structured"):
        issues.append(_issue(poi, "opening_hours_missing", 0.75, "El POI no tiene horarios estructurados ni texto de apertura."))

    if len(poi.description or "") < 80 or any(term in description for term in GENERIC_DESCRIPTION_TERMS):
        issues.append(_issue(poi, "description_low_quality", 0.8, "La descripción es corta o genérica."))

    if any(term in name for term in FOOD_NAME_TERMS) and GASTRONOMY_CATEGORY_ID not in category_ids:
        issues.append(
            _issue(
                poi,
                "category_mismatch",
                0.9,
                "El nombre sugiere gastronomía, pero no tiene categoría Gastronomía.",
                suggested_fix={"add_category_ids": [GASTRONOMY_CATEGORY_ID]},
            )
        )

    if any(term in name for term in FOOD_NAME_TERMS) and any(term in description for term in THERMAL_TERMS):
        issues.append(
            _issue(
                poi,
                "description_category_mismatch",
                0.88,
                "El nombre sugiere gastronomía, pero la descripción contiene señales de termas/spa.",
                suggested_fix={"review_description": True, "add_category_ids": [GASTRONOMY_CATEGORY_ID]},
            )
        )

    if any(term in name for term in THERMAL_TERMS) and THERMAL_CATEGORY_ID not in category_ids:
        issues.append(
            _issue(
                poi,
                "category_mismatch",
                0.85,
                "El nombre sugiere termas/bienestar, pero no tiene esa categoría.",
                suggested_fix={"add_category_ids": [THERMAL_CATEGORY_ID]},
            )
        )

    services = visit_rules.get("services") or {}
    if not services or all((value or {}).get("evidence_level") == "unknown" for value in services.values() if isinstance(value, dict)):
        issues.append(_issue(poi, "services_unknown", 0.65, "No hay evidencia útil de servicios como baño, estacionamiento o accesibilidad."))

    return issues


def _issue(
    poi: POI,
    issue: str,
    confidence: float,
    reason: str,
    suggested_fix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "poi_id": str(poi.id),
        "name": poi.name,
        "issue": issue,
        "confidence": confidence,
        "reason": reason,
        "suggested_fix": suggested_fix or {},
    }


async def load_category_ids(poi_id) -> list[int]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(POICategory.category_id).where(POICategory.poi_id == poi_id))
        return list(result.scalars().all())


async def main() -> None:
    parser = argparse.ArgumentParser(description="Audita calidad de datos de POIs existentes.")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--output", type=Path, default=None, help="Ruta JSONL opcional para guardar issues.")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(POI).order_by(POI.name.asc()).limit(args.limit))
        pois = list(result.scalars().all())

        all_issues: list[dict[str, Any]] = []
        for poi in pois:
            category_result = await db.execute(select(POICategory.category_id).where(POICategory.poi_id == poi.id))
            category_ids = list(category_result.scalars().all())
            all_issues.extend(audit_poi(poi, category_ids))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as file:
            for issue in all_issues:
                file.write(json.dumps(issue, ensure_ascii=False) + "\n")

    summary: dict[str, int] = {}
    for issue in all_issues:
        summary[issue["issue"]] = summary.get(issue["issue"], 0) + 1

    print(json.dumps({"total_pois": len(pois), "total_issues": len(all_issues), "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
