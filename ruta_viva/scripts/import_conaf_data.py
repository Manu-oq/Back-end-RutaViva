from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import app.db.models  # noqa: F401
from app.db.session import AsyncSessionLocal, init_db
from app.models.category import Category
from app.models.poi import POI
from app.models.poi_category import POICategory
from app.repositories.poi_repository import from_text
from app.services.embedding_service import get_embedding_service

logger = logging.getLogger("conaf_import")

DATA_FILE = ROOT_DIR / "data" / "conaf_protected_areas.json"
GEO_DEDUP_RADIUS_METERS = 500.0
EMBEDDING_DELAY_SECONDS = 0.5

CONAF_CATEGORIES = ["Parques/Reservas", "Naturaleza"]


class EmbeddingRateLimiter:
    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval_seconds = min_interval_seconds
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def wait_turn(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            elapsed = now - self._last_call
            if elapsed < self.min_interval_seconds:
                await asyncio.sleep(self.min_interval_seconds - elapsed)
            self._last_call = loop.time()


def build_description(area: dict[str, Any]) -> str:
    enriched = area.get("description", "")
    if enriched and len(enriched) >= 80:
        return enriched
    desc = area.get("description", "")
    if area.get("area_hectares"):
        desc += f" Superficie: {area['area_hectares']:,} hectareas.".replace(",", ".")
    if area.get("website"):
        desc += f" Mas informacion en {area['website']}"
    return desc


def build_visit_rules(area: dict[str, Any]) -> dict[str, Any]:
    enriched = area.get("visit_rules")
    if enriched and isinstance(enriched, dict):
        return enriched
    area_type = area.get("type", "Area protegida")
    return {
        "is_primary_experience": True,
        "requires_daylight": True,
        "night_suitable": False,
        "latest_recommended_start_time": "15:30",
        "access_notes": f"Area silvestre protegida ({area_type}). Verificar horarios de acceso y tarifas de entrada en CONAF.",
        "confidence": "known",
        "source": "CONAF",
    }


def build_multimedia(area: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": "CONAF",
        "area_type": area.get("type"),
        "region": area.get("region"),
        "commune": area.get("commune"),
    }
    if area.get("area_hectares"):
        payload["area_hectares"] = area["area_hectares"]
    if area.get("website"):
        payload["website"] = area["website"]
    return payload


async def find_existing_poi(db, name: str, lat: float, lon: float) -> POI | None:
    stmt = select(POI).where(
        func.ST_DWithin(
            func.ST_GeogFromText(f"POINT({lon} {lat})"),
            POI.location.ST_AsGeoJSON().cast(func.geography),
            GEO_DEDUP_RADIUS_METERS,
        )
    ).limit(5)

    result = await db.execute(stmt)
    candidates = list(result.scalars().all())

    for candidate in candidates:
        candidate_name = (candidate.name or "").lower()
        target_name = name.lower()
        common_words = set(candidate_name.split()) & set(target_name.split())
        if len(common_words) >= 2 or candidate_name == target_name:
            return candidate

    return None


async def import_conaf_areas(
    limit: int,
) -> dict[str, int]:
    await init_db()

    with DATA_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    areas = data.get("protected_areas", [])
    if limit > 0:
        areas = areas[:limit]

    logger.info("Dataset CONAF cargado: %s areas protegidas", len(areas))

    async with AsyncSessionLocal() as db:
        cat_result = await db.execute(select(Category))
        categories = {c.name: c.id for c in cat_result.scalars().all()}

    category_ids = [
        categories[name] for name in CONAF_CATEGORIES if name in categories
    ]
    if len(category_ids) != len(CONAF_CATEGORIES):
        missing = set(CONAF_CATEGORIES) - set(categories.keys())
        raise RuntimeError(f"Categorias faltantes en DB: {missing}")

    embedding_service = get_embedding_service()
    rate_limiter = EmbeddingRateLimiter(EMBEDDING_DELAY_SECONDS)

    stats = {"created": 0, "skipped": 0, "failed": 0}

    for i, area in enumerate(areas, start=1):
        name = area["name"]
        lat = area["latitude"]
        lon = area["longitude"]

        logger.info("Importando %s/%s: %s", i, len(areas), name)

        try:
            async with AsyncSessionLocal() as db:
                existing = await find_existing_poi(db, name, lat, lon)
                if existing is not None:
                    logger.info("Ya existe POI similar: %s (id=%s)", existing.name, existing.id)
                    stats["skipped"] += 1
                    continue

            description = build_description(area)
            visit_rules = build_visit_rules(area)
            multimedia = build_multimedia(area)

            await rate_limiter.wait_turn()
            embedding = await embedding_service.get_embedding(
                f"{name}. {description}"
            )

            poi = POI(
                id=uuid4(),
                entrepreneur_id=None,
                name=name,
                description=description,
                description_embedding=embedding,
                location=from_text(f"POINT({lon} {lat})", srid=4326),
                access_type="public",
                contact_phone=None,
                contact_email=None,
                multimedia_urls=multimedia,
                opening_hours_text=None,
                visit_rules=visit_rules,
                verification_status="verified",
                confidence_score=0.85,
            )

            async with AsyncSessionLocal() as db:
                db.add(poi)
                await db.flush()

                for category_id in category_ids:
                    db.add(POICategory(poi_id=poi.id, category_id=category_id))

                await db.commit()

            stats["created"] += 1
            logger.info("Creado: %s", name)

        except Exception as exc:
            logger.exception("Fallo importacion de %s: %s", name, exc)
            stats["failed"] += 1

    return stats


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Importa areas protegidas de CONAF a la base de datos de POIs.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Maximo de areas a importar (0=todas).")
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra que se importaria.")
    return parser.parse_args()


async def main() -> None:
    configure_logging()
    args = parse_args()

    if args.dry_run:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        areas = data.get("protected_areas", [])
        print(f"Areas protegidas a importar: {len(areas)}")
        for area in areas:
            print(f"  - {area['name']} ({area['type']}, {area['commune']})")
        return

    stats = await import_conaf_areas(limit=args.limit)
    print(f"\nImportacion finalizada: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
