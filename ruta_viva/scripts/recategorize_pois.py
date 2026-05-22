from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import app.db.models  # noqa: F401,E402
from app.db.session import AsyncSessionLocal, init_db
from app.models.category import Category
from app.models.poi import POI
from app.models.poi_category import POICategory


logger = logging.getLogger("recategorize_pois")

THERMAL_KEYWORDS = ("terma", "termas", "thermal", "spa")
INFO_KEYWORDS = ("conaf", "información", "informacion", "oficina", "centro de visitantes")
VOLCANO_KEYWORDS = ("volcán", "volcan", "mirador", "cerro", "montaña")
WATER_KEYWORDS = ("lago", "laguna", "río", "rio", "playa", "salto", "cascada")
TREKKING_KEYWORDS = ("sendero", "trekking", "trail", "hiking", "camino")
PARK_KEYWORDS = ("parque", "reserva", "monumento natural")
CULTURE_KEYWORDS = ("museo", "patrimonio", "histórico", "historico", "galería", "galeria")
CRAFT_KEYWORDS = ("artesanía", "artesania", "mercado", "feria")
FOOD_KEYWORDS = ("restaurant", "restaurante", "café", "cafe", "bar", "pub", "comida")
LODGING_KEYWORDS = ("hotel", "hostal", "hostel", "cabaña", "cabana", "camping")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def infer_categories(name: str, description: str) -> list[str]:
    text = f"{name} {description}".lower()
    categories: list[str] = []

    if contains_any(text, INFO_KEYWORDS):
        categories.append("Servicios turísticos/Información")
    if contains_any(text, FOOD_KEYWORDS):
        categories.append("Gastronomía")
    if contains_any(text, LODGING_KEYWORDS):
        categories.append("Alojamiento")
    if contains_any(text, THERMAL_KEYWORDS):
        categories.extend(["Termas/Bienestar", "Naturaleza"])
    if contains_any(text, WATER_KEYWORDS):
        categories.extend(["Lagos/Ríos/Playas", "Naturaleza"])
    if contains_any(text, VOLCANO_KEYWORDS):
        categories.extend(["Montañas/Volcanes/Miradores", "Naturaleza"])
    if contains_any(text, TREKKING_KEYWORDS):
        categories.extend(["Trekking/Senderismo", "Naturaleza"])
    if contains_any(text, PARK_KEYWORDS):
        categories.extend(["Parques/Reservas", "Naturaleza"])
    if contains_any(text, CULTURE_KEYWORDS):
        categories.extend(["Museos/Patrimonio", "Cultura"])
    if contains_any(text, CRAFT_KEYWORDS):
        categories.append("Artesanía/Compras locales")

    if not categories:
        categories.append("Turismo")

    deduped: list[str] = []
    for category in categories:
        if category not in deduped:
            deduped.append(category)
    return deduped


def infer_visit_rules(name: str, description: str, categories: list[str]) -> dict[str, Any]:
    text = f"{name} {description}".lower()
    rules: dict[str, Any] = {
        "is_primary_experience": True,
        "requires_daylight": False,
        "night_suitable": False,
        "latest_recommended_start_time": None,
        "access_notes": None,
        "confidence": "inferred",
    }

    if "Servicios turísticos/Información" in categories:
        rules.update(
            {
                "is_primary_experience": False,
                "latest_recommended_start_time": "17:00",
                "access_notes": "Centro u oficina informativa: usar como apoyo, no como parada turística principal salvo intención explícita.",
            }
        )
    elif "Termas/Bienestar" in categories or "Gastronomía" in categories:
        rules.update(
            {
                "night_suitable": True,
                "latest_recommended_start_time": "20:00",
                "access_notes": "Experiencia potencialmente apta para tarde/noche si el horario informado lo permite.",
            }
        )
    elif (
        "Montañas/Volcanes/Miradores" in categories
        or "Trekking/Senderismo" in categories
        or "Parques/Reservas" in categories
        or contains_any(text, VOLCANO_KEYWORDS + TREKKING_KEYWORDS)
    ):
        rules.update(
            {
                "requires_daylight": True,
                "latest_recommended_start_time": "15:30",
                "access_notes": "Actividad outdoor o de acceso natural: programar con luz de día salvo horario conocido que indique lo contrario.",
            }
        )

    return rules


def merge_visit_rules(existing: dict[str, Any] | None, inferred: dict[str, Any]) -> dict[str, Any]:
    """Merge inferred rules without discarding richer import/enrichment metadata."""
    merged = dict(existing or {})

    for key, value in inferred.items():
        if value is None and key in merged:
            continue
        if key == "confidence" and merged.get("confidence") == "known" and value == "inferred":
            continue
        merged[key] = value

    if existing and existing.get("blocked_for_itinerary") and "blocked_for_itinerary" not in inferred:
        merged["blocked_for_itinerary"] = True
        if existing.get("block_reason"):
            merged["block_reason"] = existing["block_reason"]

    return merged


async def load_category_map() -> dict[str, int]:
    await init_db()
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Category))
        return {category.name: category.id for category in result.scalars().all()}


async def recategorize() -> None:
    category_map = await load_category_map()

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(POI).order_by(POI.name.asc()))
        pois = list(result.scalars().all())

        updated = 0
        for poi in pois:
            categories = infer_categories(poi.name, poi.description)
            category_ids = [category_map[name] for name in categories if name in category_map]
            poi.visit_rules = merge_visit_rules(
                poi.visit_rules,
                infer_visit_rules(poi.name, poi.description, categories),
            )

            await db.execute(delete(POICategory).where(POICategory.poi_id == poi.id))
            for category_id in category_ids:
                db.add(POICategory(poi_id=poi.id, category_id=category_id))

            updated += 1
            if updated % 100 == 0:
                logger.info("Recategorizados %s/%s POIs...", updated, len(pois))

        await db.commit()
        logger.info("Recategorización finalizada. POIs actualizados: %s", updated)


async def main() -> None:
    configure_logging()
    await recategorize()


if __name__ == "__main__":
    asyncio.run(main())
