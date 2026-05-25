from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import func, select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import app.db.models  # noqa: F401
from app.db.session import AsyncSessionLocal
from app.models.poi import POI
from app.models.poi_category import POICategory
from app.services.embedding_service import get_embedding_service
from app.services.poi_metadata_extractor import (
    extract_metadata_from_text,
    html_to_text,
    merge_enrichment_into_visit_rules,
    parse_opening_hours_text,
)

logger = logging.getLogger("poi_enrichment")
HTTP_TIMEOUT_SECONDS = 20.0
REQUEST_DELAY_SECONDS = 1.5

OSM_KEY_LABELS = {
    "opening_hours": "Horario",
    "description": "Descripción",
    "description:es": "Descripción",
    "amenity": "Tipo de servicio",
    "tourism": "Tipo turístico",
    "leisure": "Espacio recreativo",
    "natural": "Elemento natural",
    "shop": "Comercio",
    "cuisine": "Cocina",
    "wheelchair": "Accesibilidad",
    "parking": "Estacionamiento",
}

OSM_VALUE_LABELS = {
    "restaurant": "restaurante",
    "cafe": "cafetería",
    "fast_food": "comida rápida",
    "bar": "bar",
    "pub": "pub",
    "hotel": "hotel",
    "hostel": "hostal",
    "guest_house": "hospedaje familiar",
    "camp_site": "camping",
    "museum": "museo",
    "attraction": "atractivo turístico",
    "viewpoint": "mirador",
    "information": "centro de información turística",
    "park": "parque",
    "nature_reserve": "reserva natural",
    "garden": "jardín",
    "playground": "área de juegos",
    "peak": "cerro o mirador natural",
    "volcano": "volcán",
    "beach": "playa",
    "water": "cuerpo de agua",
    "wetland": "humedal",
    "hot_spring": "fuente termal",
    "waterfall": "cascada o salto de agua",
    "souvenir": "tienda de recuerdos y artesanía",
    "craft": "artesanía",
    "marketplace": "mercado o feria local",
    "yes": "sí",
    "no": "no",
    "limited": "limitada",
    "designated": "habilitado",
    "customers": "para clientes",
    "chilean": "chilena",
    "italian": "italiana",
    "coffee_shop": "café",
    "sandwich": "sándwiches",
    "burger": "hamburguesas",
    "seafood": "mariscos",
    "steak_house": "parrilla",
    "barbecue": "parrilla",
    "international": "internacional",
    "vegetarian": "vegetariana",
}


def media_as_dict(media: object) -> dict[str, Any]:
    return media if isinstance(media, dict) else {}


def website_from_media(media: object) -> str | None:
    payload = media_as_dict(media)
    for key in ("website", "contact:website", "url"):
        value = payload.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def build_text_from_osm_tags(poi: POI) -> str:
    media = media_as_dict(poi.multimedia_urls)
    osm_tags = media.get("osm_tags")
    if not isinstance(osm_tags, dict):
        return ""

    useful_parts = []
    for key in (
        "opening_hours",
        "description",
        "description:es",
        "amenity",
        "tourism",
        "leisure",
        "natural",
        "shop",
        "cuisine",
        "wheelchair",
        "parking",
    ):
        value = osm_tags.get(key)
        if value:
            label = OSM_KEY_LABELS.get(key, key.replace("_", " ").title())
            readable_value = humanize_osm_value(str(value))
            useful_parts.append(f"{label}: {readable_value}")
    return ". ".join(useful_parts)


def humanize_osm_value(value: str) -> str:
    parts = [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    if not parts:
        return value.replace("_", " ")
    return ", ".join(OSM_VALUE_LABELS.get(part, part.replace("_", " ")) for part in parts)


async def fetch_public_text(url: str) -> str | None:
    headers = {"User-Agent": "RutaVivaMetadataEnricher/0.1 (+local thesis project)"}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True, headers=headers) as client:
        response = await client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "text/html" in content_type:
            return html_to_text(response.text)
        if "text/plain" in content_type or "application/json" in content_type:
            return response.text
        return None


async def category_ids_for_poi(db, poi_id) -> list[int]:
    result = await db.execute(select(POICategory.category_id).where(POICategory.poi_id == poi_id))
    return list(result.scalars().all())


def should_enrich(poi: POI, *, include_with_hours: bool) -> bool:
    visit_rules = poi.visit_rules or {}
    if not include_with_hours and (poi.opening_hours_text or visit_rules.get("opening_hours_structured")):
        if len(poi.description or "") >= 120 and visit_rules.get("services"):
            return False
    return True


async def enrich_poi(
    poi: POI,
    *,
    refresh_embeddings: bool,
    dry_run: bool,
) -> bool:
    async with AsyncSessionLocal() as db:
        db_poi = await db.get(POI, poi.id)
        if db_poi is None:
            return False
        category_ids = await category_ids_for_poi(db, db_poi.id)

        extracted_any = False
        next_description = db_poi.description
        next_opening_hours = db_poi.opening_hours_text
        next_visit_rules = dict(db_poi.visit_rules or {})

        osm_text = build_text_from_osm_tags(db_poi)
        if osm_text:
            extracted = extract_metadata_from_text(
                poi_name=db_poi.name,
                category_ids=category_ids,
                raw_text=osm_text,
                source_url=media_as_dict(db_poi.multimedia_urls).get("osm_url"),
                provider="osm_tags",
            )
            next_visit_rules = merge_enrichment_into_visit_rules(
                next_visit_rules,
                extracted,
                provider="osm_tags",
                source_url=media_as_dict(db_poi.multimedia_urls).get("osm_url"),
                confidence=0.8,
            )
            if extracted.opening_hours_text and not next_opening_hours:
                next_opening_hours = extracted.opening_hours_text
            extracted_any = True

        website = website_from_media(db_poi.multimedia_urls)
        if website:
            try:
                text = await fetch_public_text(website)
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
            except httpx.HTTPError as exc:
                logger.warning("No se pudo consultar %s para %s: %s", website, db_poi.name, exc)
                text = None

            if text:
                extracted = extract_metadata_from_text(
                    poi_name=db_poi.name,
                    category_ids=category_ids,
                    raw_text=text,
                    source_url=website,
                    provider="official_website",
                )
                next_visit_rules = merge_enrichment_into_visit_rules(
                    next_visit_rules,
                    extracted,
                    provider="official_website",
                    source_url=website,
                    confidence=0.86,
                )
                if extracted.description and len(extracted.description) > len(next_description or ""):
                    next_description = extracted.description
                if extracted.opening_hours_text and not next_opening_hours:
                    next_opening_hours = extracted.opening_hours_text
                extracted_any = True

        if next_opening_hours and not next_visit_rules.get("opening_hours_structured"):
            parsed_hours = parse_opening_hours_text(next_opening_hours)
            if parsed_hours:
                next_visit_rules["opening_hours_structured"] = parsed_hours

        if not extracted_any:
            return False

        logger.info("Enriquecido: %s", db_poi.name)
        if dry_run:
            logger.info("DRY RUN %s -> hours=%s rules_keys=%s", db_poi.name, next_opening_hours, list(next_visit_rules.keys()))
            return True

        description_changed = next_description != db_poi.description
        db_poi.description = next_description
        db_poi.opening_hours_text = next_opening_hours
        db_poi.visit_rules = next_visit_rules

        if refresh_embeddings and description_changed:
            embedding_service = get_embedding_service()
            db_poi.description_embedding = await embedding_service.get_embedding(f"{db_poi.name}. {db_poi.description}")

        await db.commit()
        return True


async def main() -> None:
    parser = argparse.ArgumentParser(description="Enriquece metadata de POIs existentes desde fuentes públicas permitidas.")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--include-with-hours", action="store_true")
    parser.add_argument("--refresh-embeddings", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    async with AsyncSessionLocal() as db:
        stmt = select(POI).order_by(func.length(POI.description).asc()).limit(args.limit)
        result = await db.execute(stmt)
        pois = [poi for poi in result.scalars().all() if should_enrich(poi, include_with_hours=args.include_with_hours)]

    enriched = 0
    for index, poi in enumerate(pois, start=1):
        logger.info("Procesando %s/%s: %s", index, len(pois), poi.name)
        try:
            if await enrich_poi(poi, refresh_embeddings=args.refresh_embeddings, dry_run=args.dry_run):
                enriched += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("Falló enriquecimiento de %s: %s", poi.name, exc)

    logger.info("Finalizado. POIs enriquecidos: %s/%s", enriched, len(pois))


if __name__ == "__main__":
    asyncio.run(main())
