from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import select, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import app.db.models  # noqa: F401
from app.db.session import AsyncSessionLocal, init_db
from app.models.category import Category
from app.models.poi import POI
from app.repositories.poi_repository import POIRepository
from app.schemas.poi import POICreate
from app.services.embedding_service import get_embedding_service

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_SECONDS = 300
EMBEDDING_DELAY_SECONDS = 0.5
DEFAULT_LIMIT = 1000
DEFAULT_BATCH_SIZE = 10
ARAUCANIA_BBOX = "(-39.90,-73.80,-37.35,-70.75)"

FOOD_AMENITIES = {
    "restaurant",
    "cafe",
    "fast_food",
    "bar",
    "pub",
    "food_court",
    "ice_cream",
}
NATURAL_FEATURES = {"beach", "water", "peak"}
WATER_NATURAL_FEATURES = {"beach", "water"}
PEAK_NATURAL_FEATURES = {"peak"}
INFORMATION_TOURISM = {"information"}
TREKKING_TOURISM = {"trail", "hiking", "route"}
THERMAL_KEYWORDS = {"terma", "termas", "thermal", "hot spring", "spa"}
TRANSPORT_AMENITIES = {"bus_station", "ferry_terminal", "parking", "taxi"}
CRAFT_AMENITIES = {"marketplace"}
LODGING_TOURISM = {
    "hotel",
    "hostel",
    "guest_house",
    "apartment",
    "camp_site",
    "caravan_site",
    "wilderness_hut",
    "chalet",
}
CULTURE_TOURISM = {
    "museum",
    "gallery",
    "artwork",
    "attraction",
    "theme_park",
}
VIEWPOINT_TOURISM = {"viewpoint"}

DEFAULT_CATEGORIES = {
    1: "Naturaleza",
    2: "Gastronomía",
    3: "Turismo",
    4: "Alojamiento",
    5: "Cultura",
    6: "Trekking/Senderismo",
    7: "Lagos/Ríos/Playas",
    8: "Montañas/Volcanes/Miradores",
    9: "Termas/Bienestar",
    10: "Parques/Reservas",
    11: "Museos/Patrimonio",
    12: "Aventura/Deportes",
    13: "Servicios turísticos/Información",
    14: "Transporte/Accesos",
    15: "Artesanía/Compras locales",
}

logger = logging.getLogger("osm_import")
poi_repository = POIRepository()
embedding_service = None


@dataclass(slots=True)
class OSMPlace:
    osm_id: int
    osm_type: str
    name: str
    description: str
    latitude: float
    longitude: float
    access_type: str
    phone: str | None
    email: str | None
    multimedia_urls: dict[str, Any] | None
    opening_hours_text: str | None
    visit_rules: dict[str, Any] | None
    category_names: list[str]
    raw_tags: dict[str, str]


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


def build_overpass_queries() -> list[str]:
    selectors = """
  nwr["tourism"](area.searchArea);
  nwr["amenity"~"restaurant|cafe|fast_food|bar|pub|food_court|ice_cream"](area.searchArea);
  nwr["leisure"="park"](area.searchArea);
  nwr["natural"~"beach|water|peak"](area.searchArea);
""".strip()
    bbox_selectors = f"""
  nwr["tourism"]{ARAUCANIA_BBOX};
  nwr["amenity"~"restaurant|cafe|fast_food|bar|pub|food_court|ice_cream"]{ARAUCANIA_BBOX};
  nwr["leisure"="park"]{ARAUCANIA_BBOX};
  nwr["natural"~"beach|water|peak"]{ARAUCANIA_BBOX};
""".strip()

    return [
        f"""
[out:json][timeout:{OVERPASS_TIMEOUT_SECONDS}];
area["boundary"="administrative"]["ISO3166-2"="CL-AR"]->.searchArea;
(
{selectors}
);
out center tags qt;
""".strip(),
        f"""
[out:json][timeout:{OVERPASS_TIMEOUT_SECONDS}];
area["boundary"="administrative"]["wikidata"="Q2170"]->.searchArea;
(
{selectors}
);
out center tags qt;
""".strip(),
        f"""
[out:json][timeout:{OVERPASS_TIMEOUT_SECONDS}];
area["boundary"="administrative"]["admin_level"="4"]["name"~"Araucanía|Araucania"]->.searchArea;
(
{selectors}
);
out center tags qt;
""".strip(),
        f"""
[out:json][timeout:{OVERPASS_TIMEOUT_SECONDS}];
(
{bbox_selectors}
);
out center tags qt;
""".strip(),
    ]


async def execute_overpass_query(query: str, attempt: int) -> list[dict[str, Any]]:
    response = await asyncio.to_thread(
        requests.post,
        OVERPASS_URL,
        data={"data": query},
        headers={"User-Agent": "RutaVivaBackend/0.1 OSM importer"},
        timeout=OVERPASS_TIMEOUT_SECONDS,
    )

    if response.status_code >= 400:
        logger.warning(
            "Overpass rechazó intento %s con HTTP %s. Respuesta: %s",
            attempt,
            response.status_code,
            response.text[:1000],
        )
        response.raise_for_status()

    payload = response.json()
    return payload.get("elements", [])


async def fetch_osm_elements(limit: int) -> list[dict[str, Any]]:
    queries = build_overpass_queries()

    logger.info("Consultando Overpass API para la Región de La Araucanía...")

    last_error: Exception | None = None
    elements: list[dict[str, Any]] = []
    for attempt, query in enumerate(queries, start=1):
        try:
            elements = await execute_overpass_query(query, attempt)
            if elements:
                logger.info("Overpass intento %s exitoso con %s elementos brutos.", attempt, len(elements))
                break
            logger.warning("Overpass intento %s no devolvió elementos. Probando fallback...", attempt)
        except requests.HTTPError as exc:
            last_error = exc
            logger.warning("Falló intento Overpass %s. Probando fallback si existe...", attempt)

    if not elements and last_error is not None:
        raise last_error

    unique_elements: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for element in elements:
        key = (str(element.get("type", "")), int(element.get("id", 0)))
        if key in seen:
            continue
        seen.add(key)
        unique_elements.append(element)

    logger.info(
        "Overpass devolvió %s candidatos únicos brutos. Se intentarán importar hasta %s POIs válidos.",
        len(unique_elements),
        limit,
    )
    return unique_elements


async def ensure_categories() -> dict[str, int]:
    await init_db()

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Category).order_by(Category.id))
        categories = list(result.scalars().all())
        existing_by_name = {category.name: category for category in categories}
        existing_by_id = {category.id: category for category in categories}

        category_map: dict[str, int] = {}

        for desired_id, category_name in DEFAULT_CATEGORIES.items():
            existing_by_name_match = existing_by_name.get(category_name)
            existing_by_id_match = existing_by_id.get(desired_id)

            if existing_by_name_match is not None:
                category_map[category_name] = existing_by_name_match.id
                if existing_by_name_match.id != desired_id:
                    logger.warning(
                        "La categoría %s ya existe con id=%s, no con el id esperado=%s. "
                        "Se usará el id existente para evitar duplicados.",
                        category_name,
                        existing_by_name_match.id,
                        desired_id,
                    )
                continue

            if existing_by_id_match is not None:
                logger.warning(
                    "El id=%s ya existe ocupado por la categoría %s. "
                    "No se renombrará automáticamente para evitar alterar datos existentes.",
                    desired_id,
                    existing_by_id_match.name,
                )
                category_map[category_name] = existing_by_id_match.id
                continue

            category = Category(id=desired_id, name=category_name)
            db.add(category)
            await db.flush()
            existing_by_name[category_name] = category
            existing_by_id[desired_id] = category
            category_map[category_name] = category.id
            logger.info("Categoría creada: %s (id=%s)", category_name, category.id)

        await db.execute(
            text(
                """
                SELECT setval(
                    pg_get_serial_sequence('categories', 'id'),
                    COALESCE((SELECT MAX(id) FROM categories), 1),
                    true
                )
                """
            )
        )

        await db.commit()
        return category_map


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return cleaned.strip() or None


def get_lat_lon(element: dict[str, Any]) -> tuple[float | None, float | None]:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])

    center = element.get("center") or {}
    if "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])

    return None, None


def infer_access_type(tags: dict[str, str]) -> str:
    access = clean_text(tags.get("access"))
    if access in {"private", "no"}:
        return "privado"
    if access in {"customers", "permissive", "destination"}:
        return "restringido"
    return "publico"


def infer_category_names(tags: dict[str, str]) -> list[str]:
    category_names: list[str] = []
    tourism = tags.get("tourism")
    amenity = tags.get("amenity")
    natural = tags.get("natural")
    name = clean_text(tags.get("name")) or ""
    lower_name = name.lower()

    if natural in NATURAL_FEATURES:
        category_names.append("Naturaleza")
    if tags.get("leisure") == "park":
        if "Naturaleza" not in category_names:
            category_names.append("Naturaleza")
        category_names.append("Parques/Reservas")
    if natural in WATER_NATURAL_FEATURES:
        category_names.append("Lagos/Ríos/Playas")
    if natural in PEAK_NATURAL_FEATURES:
        category_names.append("Montañas/Volcanes/Miradores")
    if "volc" in lower_name or "mirador" in lower_name:
        category_names.append("Montañas/Volcanes/Miradores")
    if "lago" in lower_name or "playa" in lower_name or "río" in lower_name or "rio" in lower_name:
        category_names.append("Lagos/Ríos/Playas")
    if "sendero" in lower_name or "trekking" in lower_name:
        category_names.append("Trekking/Senderismo")
    if any(keyword in lower_name for keyword in THERMAL_KEYWORDS):
        category_names.append("Termas/Bienestar")
    if amenity in FOOD_AMENITIES:
        category_names.append("Gastronomía")
    if amenity in TRANSPORT_AMENITIES:
        category_names.append("Transporte/Accesos")
    if amenity in CRAFT_AMENITIES or "artesanía" in lower_name or "artesania" in lower_name:
        category_names.append("Artesanía/Compras locales")
    if tourism in INFORMATION_TOURISM or "conaf" in lower_name or "información" in lower_name or "informacion" in lower_name:
        category_names.append("Servicios turísticos/Información")
    if tourism in LODGING_TOURISM:
        category_names.append("Alojamiento")
    elif tourism in CULTURE_TOURISM:
        category_names.append("Museos/Patrimonio")
        category_names.append("Cultura")
    elif tourism in VIEWPOINT_TOURISM:
        category_names.append("Montañas/Volcanes/Miradores")
    elif tourism:
        category_names.append("Turismo")

    if not category_names:
        category_names.append("Turismo")

    deduped: list[str] = []
    for name in category_names:
        if name not in deduped:
            deduped.append(name)
    return deduped


def infer_visit_rules(name: str, tags: dict[str, str], category_names: list[str]) -> dict[str, Any]:
    lower_name = name.lower()
    rules: dict[str, Any] = {
        "is_primary_experience": True,
        "requires_daylight": False,
        "night_suitable": False,
        "latest_recommended_start_time": None,
        "access_notes": None,
        "confidence": "inferred",
    }

    if "Servicios turísticos/Información" in category_names:
        rules.update(
            {
                "is_primary_experience": False,
                "requires_daylight": False,
                "night_suitable": False,
                "latest_recommended_start_time": "17:00",
                "access_notes": "Centro u oficina informativa: usar como apoyo, no como parada turística principal salvo intención explícita.",
            }
        )
    elif "Termas/Bienestar" in category_names or tags.get("amenity") in FOOD_AMENITIES:
        rules.update(
            {
                "requires_daylight": False,
                "night_suitable": True,
                "latest_recommended_start_time": "20:00",
                "access_notes": "Experiencia potencialmente apta para tarde/noche si el horario informado lo permite.",
            }
        )
    elif (
        "Montañas/Volcanes/Miradores" in category_names
        or "Trekking/Senderismo" in category_names
        or "Parques/Reservas" in category_names
        or "volc" in lower_name
        or "sendero" in lower_name
    ):
        rules.update(
            {
                "requires_daylight": True,
                "night_suitable": False,
                "latest_recommended_start_time": "15:30",
                "access_notes": "Actividad outdoor o de acceso natural: programar con luz de día salvo horario conocido que indique lo contrario.",
            }
        )

    if clean_text(tags.get("opening_hours")):
        rules["confidence"] = "known"

    return rules


def describe_place_type(tags: dict[str, str]) -> str:
    tourism = tags.get("tourism")
    amenity = tags.get("amenity")
    leisure = tags.get("leisure")
    natural = tags.get("natural")

    if amenity in FOOD_AMENITIES:
        cuisine = clean_text(tags.get("cuisine"))
        if cuisine:
            return f"espacio gastronómico tipo {amenity.replace('_', ' ')} con cocina {cuisine.replace(';', ', ')}"
        return f"espacio gastronómico tipo {amenity.replace('_', ' ')}"

    if leisure == "park":
        return "parque o área recreativa al aire libre"

    if natural in NATURAL_FEATURES:
        return f"atractivo natural tipo {natural.replace('_', ' ')}"

    if tourism:
        return f"atractivo turístico tipo {tourism.replace('_', ' ')}"

    return "punto de interés turístico"


def build_description(name: str, tags: dict[str, str]) -> str:
    description = (
        clean_text(tags.get("description"))
        or clean_text(tags.get("description:es"))
    )
    if description:
        return description

    place_type = describe_place_type(tags)
    locality = clean_text(tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:state"))
    opening_hours = clean_text(tags.get("opening_hours"))

    base = f"{name} es un {place_type} ubicado en la Región de La Araucanía, Chile."
    if locality:
        base += f" Referencia territorial reportada por OSM: {locality}."
    if opening_hours:
        base += f" Horario informado en OSM: {opening_hours}."
    return base


def build_multimedia_payload(element: dict[str, Any], tags: dict[str, str]) -> dict[str, Any]:
    osm_type = str(element.get("type"))
    osm_id = int(element.get("id"))
    website = clean_text(tags.get("website") or tags.get("contact:website"))
    image = clean_text(tags.get("image"))
    wikipedia = clean_text(tags.get("wikipedia"))

    payload: dict[str, Any] = {
        "source": "OpenStreetMap",
        "osm_type": osm_type,
        "osm_id": osm_id,
        "osm_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
    }

    if website:
        payload["website"] = website
    if image:
        payload["image"] = image
    if wikipedia:
        payload["wikipedia"] = wikipedia

    return payload


def build_place(element: dict[str, Any]) -> OSMPlace | None:
    tags = {str(k): str(v) for k, v in (element.get("tags") or {}).items()}
    name = clean_text(tags.get("name"))
    if not name:
        return None

    latitude, longitude = get_lat_lon(element)
    if latitude is None or longitude is None:
        return None

    description = build_description(name, tags)
    phone = clean_text(tags.get("phone") or tags.get("contact:phone"))
    email = clean_text(tags.get("email") or tags.get("contact:email"))
    opening_hours = clean_text(tags.get("opening_hours"))
    category_names = infer_category_names(tags)

    return OSMPlace(
        osm_id=int(element["id"]),
        osm_type=str(element["type"]),
        name=name,
        description=description,
        latitude=latitude,
        longitude=longitude,
        access_type=infer_access_type(tags),
        phone=phone,
        email=email,
        multimedia_urls=build_multimedia_payload(element, tags),
        opening_hours_text=opening_hours,
        visit_rules=infer_visit_rules(name, tags, category_names),
        category_names=category_names,
        raw_tags=tags,
    )


async def osm_poi_with_embedding_already_imported(db, place: OSMPlace) -> bool:
    stmt = select(POI.id).where(
        POI.multimedia_urls.contains(
            {
                "source": "OpenStreetMap",
                "osm_type": place.osm_type,
                "osm_id": place.osm_id,
            }
        )
    ).where(POI.description_embedding.is_not(None))
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"

    minutes, remaining_seconds = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {remaining_seconds}s"

    hours, remaining_minutes = divmod(minutes, 60)
    return f"{hours}h {remaining_minutes}m"


def calculate_eta(started_at: float, processed: int, total: int) -> str:
    if processed <= 0:
        return "calculando"

    elapsed = time.perf_counter() - started_at
    average_seconds_per_item = elapsed / processed
    remaining_items = max(total - processed, 0)
    return format_duration(average_seconds_per_item * remaining_items)


async def import_place(
    place: OSMPlace,
    position: int,
    total: int,
    category_map: dict[str, int],
    rate_limiter: EmbeddingRateLimiter,
    started_at: float,
) -> bool:
    eta = calculate_eta(started_at, position - 1, total)
    logger.info("Importando %s/%s: %s... ETA: %s", position, total, place.name, eta)

    try:
        async with AsyncSessionLocal() as db:
            if await osm_poi_with_embedding_already_imported(db, place):
                logger.info(
                    "Checkpoint: omitido porque ya tenía embedding generado: %s",
                    place.name,
                )
                return False

        await rate_limiter.wait_turn()
        if embedding_service is None:
            raise RuntimeError("Embedding service is not initialized.")

        embedding = await embedding_service.get_embedding(place.description)

        category_ids = [category_map[name] for name in place.category_names if name in category_map]
        poi_in = POICreate(
            nombre=place.name,
            descripcion=place.description,
            tipo_acceso=place.access_type,
            telefono_publico=place.phone,
            email_publico=place.email,
            multimedia_urls=place.multimedia_urls,
            opening_hours_text=place.opening_hours_text,
            visit_rules=place.visit_rules,
            category_ids=category_ids,
            latitude=place.latitude,
            longitude=place.longitude,
        )

        async with AsyncSessionLocal() as db:
            await poi_repository.create_poi(
                db,
                poi_in=poi_in,
                embedding=embedding,
                entrepreneur_id=None,
            )

        return True
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falló la importación de %s (%s/%s): %s", place.name, position, total, exc)
        return False


async def process_places(elements: list[dict[str, Any]], batch_size: int, limit: int) -> None:
    category_map = await ensure_categories()
    rate_limiter = EmbeddingRateLimiter(min_interval_seconds=EMBEDDING_DELAY_SECONDS)

    places: list[OSMPlace] = []
    skipped_without_name = 0
    skipped_without_coords = 0

    for element in elements:
        place = build_place(element)
        if place is None:
            tags = element.get("tags") or {}
            if not clean_text(tags.get("name")):
                skipped_without_name += 1
            else:
                skipped_without_coords += 1
            continue
        places.append(place)
        if len(places) >= limit:
            break

    total = len(places)
    logger.info(
        "Candidatos listos para importar: %s (omitidos sin nombre: %s, sin coordenadas/centro: %s)",
        total,
        skipped_without_name,
        skipped_without_coords,
    )

    imported = 0
    not_imported = 0
    started_at = time.perf_counter()

    for batch_start in range(0, total, batch_size):
        batch = places[batch_start : batch_start + batch_size]
        tasks = [
            import_place(
                place=place,
                position=batch_start + index + 1,
                total=total,
                category_map=category_map,
                rate_limiter=rate_limiter,
                started_at=started_at,
            )
            for index, place in enumerate(batch)
        ]
        results = await asyncio.gather(*tasks)
        imported += sum(1 for result in results if result)
        not_imported += sum(1 for result in results if not result)

        processed = min(batch_start + len(batch), total)
        logger.info(
            "Progreso: %s/%s procesados | nuevos: %s | omitidos/fallidos: %s | ETA: %s",
            processed,
            total,
            imported,
            not_imported,
            calculate_eta(started_at, processed, total),
        )

    logger.info(
        "Ingesta finalizada. Importados nuevos: %s | Omitidos o fallidos: %s",
        imported,
        not_imported,
    )


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Importa POIs reales de la Región de La Araucanía desde OpenStreetMap usando Overpass.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Cantidad máxima de candidatos OSM a procesar (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Cantidad de POIs a procesar en paralelo por lote (default: {DEFAULT_BATCH_SIZE}).",
    )
    return parser.parse_args()


async def main() -> None:
    global embedding_service

    configure_logging()
    args = parse_args()
    embedding_service = get_embedding_service()

    if args.limit <= 0:
        raise ValueError("--limit debe ser mayor que cero.")
    if args.batch_size <= 0:
        raise ValueError("--batch-size debe ser mayor que cero.")

    elements = await fetch_osm_elements(limit=args.limit)
    if not elements:
        logger.warning("Overpass no devolvió elementos para importar.")
        return

    await process_places(elements=elements, batch_size=args.batch_size, limit=args.limit)


if __name__ == "__main__":
    asyncio.run(main())
