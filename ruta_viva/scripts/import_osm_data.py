from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import delete, select, text

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
CEMETERY_AMENITIES = {"crematorium", "grave_yard"}
BLACKLIST_LANDUSE = {"cemetery", "industrial", "landfill"}
SERVICE_AMENITIES = {
    "atm",
    "bank",
    "bureau_de_change",
    "charging_station",
    "clinic",
    "dentist",
    "doctors",
    "drinking_water",
    "fuel",
    "hospital",
    "pharmacy",
    "police",
    "post_office",
    "public_bath",
    "ranger_station",
    "recycling",
    "shower",
    "toilets",
    "veterinary",
}
CULTURE_AMENITIES = {
    "arts_centre",
    "cinema",
    "community_centre",
    "events_venue",
    "library",
    "theatre",
}
NATURAL_FEATURES = {
    "bay",
    "beach",
    "cave_entrance",
    "cliff",
    "forest",
    "geyser",
    "glacier",
    "hot_spring",
    "peak",
    "peninsula",
    "reef",
    "rock",
    "saddle",
    "spring",
    "stone",
    "tree",
    "volcano",
    "water",
    "wetland",
    "wood",
}
WATER_NATURAL_FEATURES = {"bay", "beach", "geyser", "hot_spring", "spring", "water", "wetland"}
PEAK_NATURAL_FEATURES = {"cliff", "peak", "rock", "saddle", "stone", "volcano"}
INFORMATION_TOURISM = {"information"}
TREKKING_TOURISM = {"trail", "hiking", "route"}
THERMAL_KEYWORDS = {"terma", "termas", "thermal", "hot spring", "hot_spring", "spa"}
TRANSPORT_AMENITIES = {
    "bicycle_parking",
    "bicycle_rental",
    "bus_station",
    "car_rental",
    "ferry_terminal",
    "parking",
    "taxi",
}
CRAFT_AMENITIES = {"marketplace"}
RELEVANT_SHOPS = {
    "alcohol",
    "bakery",
    "books",
    "butcher",
    "chocolate",
    "coffee",
    "confectionery",
    "convenience",
    "craft",
    "deli",
    "farm",
    "greengrocer",
    "mall",
    "outdoor",
    "pastry",
    "seafood",
    "sports",
    "supermarket",
    "souvenir",
    "tea",
    "travel_agency",
    "wine",
}
RELEVANT_LEISURE = {
    "bird_hide",
    "common",
    "dog_park",
    "firepit",
    "fishing",
    "garden",
    "marina",
    "nature_reserve",
    "park",
    "picnic_table",
    "pitch",
    "playground",
    "sports_centre",
    "stadium",
    "swimming_area",
    "swimming_pool",
    "track",
    "water_park",
}
RELEVANT_MAN_MADE = {
    "beacon",
    "bridge",
    "cross",
    "lighthouse",
    "obelisk",
    "observatory",
    "pier",
    "survey_point",
    "tower",
    "water_tower",
    "watermill",
}
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
PLACE_TYPES = {"city", "town", "village", "hamlet", "locality", "suburb", "neighbourhood", "isolated_dwelling"}

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


class ImportStatus(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"
    FAILED = "failed"


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
  nwr["amenity"~"restaurant|cafe|fast_food|bar|pub|food_court|ice_cream|arts_centre|cinema|community_centre|events_venue|library|theatre|marketplace|bus_station|ferry_terminal|parking|taxi|bicycle_rental|car_rental|fuel|charging_station|toilets|shower|drinking_water|public_bath|bank|atm|bureau_de_change|pharmacy|hospital|clinic|doctors|dentist|police|post_office|ranger_station|grave_yard|crematorium"](area.searchArea);
  nwr["leisure"~"park|nature_reserve|garden|picnic_table|playground|sports_centre|stadium|swimming_pool|swimming_area|water_park|track|pitch|marina|fishing|firepit|bird_hide|dog_park|common"](area.searchArea);
  nwr["natural"~"bay|beach|cave_entrance|cliff|forest|geyser|glacier|hot_spring|peak|peninsula|reef|rock|saddle|spring|stone|tree|volcano|water|wetland|wood"](area.searchArea);
  nwr["historic"](area.searchArea);
  nwr["shop"~"alcohol|bakery|books|butcher|chocolate|coffee|confectionery|convenience|craft|deli|farm|greengrocer|mall|outdoor|pastry|seafood|sports|supermarket|souvenir|tea|travel_agency|wine"](area.searchArea);
  nwr["craft"](area.searchArea);
  nwr["sport"](area.searchArea);
  nwr["man_made"~"beacon|bridge|cross|lighthouse|obelisk|observatory|pier|survey_point|tower|water_tower|watermill"](area.searchArea);
  nwr["waterway"](area.searchArea);
  nwr["place"~"city|town|village|hamlet|locality|suburb|neighbourhood|isolated_dwelling"](area.searchArea);
  nwr["landuse"~"cemetery|industrial|landfill"](area.searchArea);
  nwr["highway"="bus_stop"](area.searchArea);
  nwr["railway"~"station|halt"](area.searchArea);
  nwr["public_transport"](area.searchArea);
  nwr["route"~"hiking|bicycle|mtb|foot|horse"](area.searchArea);
  nwr["information"](area.searchArea);
""".strip()
    bbox_selectors = f"""
  nwr["tourism"]{ARAUCANIA_BBOX};
  nwr["amenity"~"restaurant|cafe|fast_food|bar|pub|food_court|ice_cream|arts_centre|cinema|community_centre|events_venue|library|theatre|marketplace|bus_station|ferry_terminal|parking|taxi|bicycle_rental|car_rental|fuel|charging_station|toilets|shower|drinking_water|public_bath|bank|atm|bureau_de_change|pharmacy|hospital|clinic|doctors|dentist|police|post_office|ranger_station|grave_yard|crematorium"]{ARAUCANIA_BBOX};
  nwr["leisure"~"park|nature_reserve|garden|picnic_table|playground|sports_centre|stadium|swimming_pool|swimming_area|water_park|track|pitch|marina|fishing|firepit|bird_hide|dog_park|common"]{ARAUCANIA_BBOX};
  nwr["natural"~"bay|beach|cave_entrance|cliff|forest|geyser|glacier|hot_spring|peak|peninsula|reef|rock|saddle|spring|stone|tree|volcano|water|wetland|wood"]{ARAUCANIA_BBOX};
  nwr["historic"]{ARAUCANIA_BBOX};
  nwr["shop"~"alcohol|bakery|books|butcher|chocolate|coffee|confectionery|convenience|craft|deli|farm|greengrocer|mall|outdoor|pastry|seafood|sports|supermarket|souvenir|tea|travel_agency|wine"]{ARAUCANIA_BBOX};
  nwr["craft"]{ARAUCANIA_BBOX};
  nwr["sport"]{ARAUCANIA_BBOX};
  nwr["man_made"~"beacon|bridge|cross|lighthouse|obelisk|observatory|pier|survey_point|tower|water_tower|watermill"]{ARAUCANIA_BBOX};
  nwr["waterway"]{ARAUCANIA_BBOX};
  nwr["place"~"city|town|village|hamlet|locality|suburb|neighbourhood|isolated_dwelling"]{ARAUCANIA_BBOX};
  nwr["landuse"~"cemetery|industrial|landfill"]{ARAUCANIA_BBOX};
  nwr["highway"="bus_stop"]{ARAUCANIA_BBOX};
  nwr["railway"~"station|halt"]{ARAUCANIA_BBOX};
  nwr["public_transport"]{ARAUCANIA_BBOX};
  nwr["route"~"hiking|bicycle|mtb|foot|horse"]{ARAUCANIA_BBOX};
  nwr["information"]{ARAUCANIA_BBOX};
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
        return "private"
    if access in {"customers", "permissive", "destination"}:
        return "restricted"
    return "public"


def infer_category_names(tags: dict[str, str]) -> list[str]:
    category_names: list[str] = []
    tourism = tags.get("tourism")
    amenity = tags.get("amenity")
    natural = tags.get("natural")
    landuse = tags.get("landuse")
    leisure = tags.get("leisure")
    shop = tags.get("shop")
    historic = tags.get("historic")
    craft = tags.get("craft")
    sport = tags.get("sport")
    man_made = tags.get("man_made")
    waterway = tags.get("waterway")
    place = tags.get("place")
    highway = tags.get("highway")
    railway = tags.get("railway")
    route = tags.get("route")
    public_transport = tags.get("public_transport")
    landuse = tags.get("landuse")
    name = clean_text(tags.get("name")) or ""
    lower_name = name.lower()

    if natural in NATURAL_FEATURES:
        category_names.append("Naturaleza")
    if leisure in RELEVANT_LEISURE:
        if "Naturaleza" not in category_names:
            category_names.append("Naturaleza")
        if leisure in {"park", "nature_reserve", "garden", "common", "bird_hide"}:
            category_names.append("Parques/Reservas")
        if leisure in {"sports_centre", "stadium", "swimming_pool", "swimming_area", "water_park", "track", "pitch"}:
            category_names.append("Aventura/Deportes")
    if natural in WATER_NATURAL_FEATURES:
        category_names.append("Lagos/Ríos/Playas")
    if natural in PEAK_NATURAL_FEATURES:
        category_names.append("Montañas/Volcanes/Miradores")
    if waterway:
        category_names.append("Lagos/Ríos/Playas")
        if "Naturaleza" not in category_names:
            category_names.append("Naturaleza")
    if natural == "hot_spring" or any(keyword in lower_name for keyword in THERMAL_KEYWORDS):
        category_names.append("Termas/Bienestar")
    if "volc" in lower_name or "mirador" in lower_name or tourism in VIEWPOINT_TOURISM:
        category_names.append("Montañas/Volcanes/Miradores")
    if "lago" in lower_name or "playa" in lower_name or "río" in lower_name or "rio" in lower_name:
        category_names.append("Lagos/Ríos/Playas")
    if "sendero" in lower_name or "trekking" in lower_name or route in {"hiking", "foot", "horse"}:
        category_names.append("Trekking/Senderismo")
    if route in {"bicycle", "mtb"} or sport:
        category_names.append("Aventura/Deportes")
    if amenity in FOOD_AMENITIES:
        category_names.append("Gastronomía")
    if amenity in CEMETERY_AMENITIES or landuse == "cemetery" or "cementerio" in lower_name:
        category_names.append("Cultura")
    if shop in {"bakery", "chocolate", "coffee", "confectionery", "deli", "pastry", "seafood", "tea", "wine"}:
        category_names.append("Gastronomía")
    if amenity in TRANSPORT_AMENITIES:
        category_names.append("Transporte/Accesos")
    if highway == "bus_stop" or railway in {"station", "halt"} or public_transport:
        category_names.append("Transporte/Accesos")
    if amenity in SERVICE_AMENITIES:
        category_names.append("Servicios turísticos/Información")
    if amenity in CRAFT_AMENITIES or shop in {"craft", "souvenir"} or craft or "artesanía" in lower_name or "artesania" in lower_name:
        category_names.append("Artesanía/Compras locales")
    if shop in RELEVANT_SHOPS and shop not in {"craft", "souvenir"}:
        category_names.append("Turismo")
    if amenity in CULTURE_AMENITIES or historic:
        category_names.append("Cultura")
        category_names.append("Museos/Patrimonio")
    if man_made in RELEVANT_MAN_MADE:
        category_names.append("Turismo")
        if man_made in {"tower", "observatory", "lighthouse", "survey_point"}:
            category_names.append("Montañas/Volcanes/Miradores")
    if landuse in {"industrial", "landfill"}:
        category_names.append("Servicios turísticos/Información")
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
    if place in PLACE_TYPES:
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
    amenity = tags.get("amenity")
    tourism = tags.get("tourism")
    natural = tags.get("natural")
    route = tags.get("route")
    shop = tags.get("shop")
    landuse = tags.get("landuse")
    searchable_text = " ".join(
        filter(
            None,
            [
                lower_name,
                tags.get("amenity"),
                tags.get("landuse"),
                tags.get("industrial"),
                tags.get("man_made"),
            ],
        )
    )
    rules: dict[str, Any] = {
        "is_primary_experience": True,
        "requires_daylight": False,
        "night_suitable": False,
        "latest_recommended_start_time": None,
        "access_notes": None,
        "confidence": "inferred",
    }

    if amenity in CEMETERY_AMENITIES or landuse == "cemetery" or "cementerio" in lower_name or "cemetery" in searchable_text:
        rules.update(
            {
                "is_primary_experience": False,
                "requires_daylight": True,
                "night_suitable": False,
                "latest_recommended_start_time": "16:30",
                "blocked_for_itinerary": True,
                "block_reason": "cemetery",
                "allow_if_user_intent": ["cementerio", "patrimonial", "histórico", "historico", "memorial"],
                "access_notes": "Cementerio o memorial: no usar como panorama familiar salvo interés patrimonial explícito.",
            }
        )
    elif landuse == "landfill" or any(term in searchable_text for term in ("landfill", "waste", "dump", "vertedero", "basural")):
        rules.update(
            {
                "is_primary_experience": False,
                "requires_daylight": False,
                "night_suitable": False,
                "latest_recommended_start_time": None,
                "blocked_for_itinerary": True,
                "block_reason": "waste",
                "access_notes": "Infraestructura de residuos: no usar como parada turística.",
            }
        )
    elif landuse == "industrial" or any(term in searchable_text for term in ("industrial", "factory", "works", "plant")):
        rules.update(
            {
                "is_primary_experience": False,
                "requires_daylight": False,
                "night_suitable": False,
                "latest_recommended_start_time": None,
                "blocked_for_itinerary": True,
                "block_reason": "industrial",
                "access_notes": "Zona o infraestructura industrial: no usar como parada turística.",
            }
        )
    elif "Servicios turísticos/Información" in category_names or amenity in SERVICE_AMENITIES:
        rules.update(
            {
                "is_primary_experience": False,
                "requires_daylight": False,
                "night_suitable": False,
                "latest_recommended_start_time": "17:00",
                "blocked_for_itinerary": True,
                "block_reason": "logistic_service",
                "allow_if_user_intent": ["servicio", "farmacia", "hospital", "banco", "baño", "combustible", "emergencia"],
                "access_notes": "Servicio de apoyo logístico: usar como referencia o necesidad puntual, no como parada turística principal salvo intención explícita.",
            }
        )
    elif amenity in TRANSPORT_AMENITIES or tags.get("highway") == "bus_stop" or tags.get("railway") in {"station", "halt"}:
        rules.update(
            {
                "is_primary_experience": False,
                "requires_daylight": False,
                "night_suitable": False,
                "latest_recommended_start_time": "20:00",
                "blocked_for_itinerary": True,
                "block_reason": "pure_transport",
                "allow_if_user_intent": ["transporte", "bus", "terminal", "salida", "llegada", "traslado"],
                "access_notes": "Punto de transporte: usar solo si el usuario necesita llegar, salir o trasladarse.",
            }
        )
    elif "Alojamiento" in category_names:
        rules.update(
            {
                "is_primary_experience": False,
                "requires_daylight": False,
                "night_suitable": True,
                "latest_recommended_start_time": "21:00",
                "access_notes": "Alojamiento: usar solo para check-in/check-out o descanso cuando el usuario lo pida explícitamente.",
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
        or natural in PEAK_NATURAL_FEATURES
        or route in {"hiking", "foot", "horse", "bicycle", "mtb"}
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
    elif shop in RELEVANT_SHOPS or tourism in CULTURE_TOURISM:
        rules.update(
            {
                "requires_daylight": False,
                "night_suitable": False,
                "latest_recommended_start_time": "18:00",
                "access_notes": "Comercio, cultura o punto urbano: verificar horario informado antes de programar.",
            }
        )

    if clean_text(tags.get("opening_hours")):
        rules["confidence"] = "known"

    return rules


OSM_TAG_HUMANIZED: dict[str, str] = {
    # Naturaleza
    "peak": "cerro o mirador natural con vistas panorámicas",
    "volcano": "volcán activo o inactivo, atractivo geológico",
    "beach": "playa con acceso a lago o río",
    "waterfall": "cascada o salto de agua natural",
    "bay": "bahía o ensenada costera",
    "cave_entrance": "entrada de cueva o formación rocosa",
    "cliff": "acantilado con vistas al paisaje",
    "forest": "bosque nativo con senderos naturales",
    "geyser": "géiser o fuente termal natural",
    "glacier": "glaciar o masa de hielo natural",
    "hot_spring": "fuente de agua termal natural",
    "peninsula": "península o formación costera",
    "reef": "arrecife o formación rocosa marina",
    "rock": "formación rocosa natural",
    "saddle": "paso de montaña entre cerros",
    "spring": "nacimiento de agua natural",
    "stone": "formación rocosa o piedra natural",
    "tree": "árbol notable o punto de referencia natural",
    "water": "cuerpo de agua natural",
    "wetland": "humedal o zona húmeda con fauna nativa",
    "wood": "bosque o área arbolada",
    # Turismo
    "viewpoint": "mirador con vistas panorámicas del paisaje",
    "museum": "museo con colecciones históricas o culturales",
    "hotel": "hotel con servicios de hospedaje",
    "hostel": "albergue u hostal para viajeros",
    "guest_house": "hospedaje familiar o casa de huéspedes",
    "apartment": "apartamento o departamento en alquiler",
    "camp_site": "camping o área de acampada",
    "caravan_site": "área para caravanas o autocaravanas",
    "wilderness_hut": "refugio de montaña o cabaña rústica",
    "chalet": "cabaña o chalet de montaña",
    "information": "centro de información turística",
    "attraction": "atractivo turístico de interés",
    "picnic_site": "área de picnic con mesas y sombra",
    "zoo": "zoológico o centro de fauna local",
    "theme_park": "parque temático o de diversiones",
    # Gastronomía
    "restaurant": "restaurante con cocina local",
    "cafe": "café o cafetería con bebidas y snacks",
    "fast_food": "comida rápida para llevar",
    "bar": "bar o pub con bebidas",
    "pub": "pub o bar con ambiente local",
    "food_court": "patio de comidas con varias opciones",
    "ice_cream": "heladería artesanal",
    # Cultura
    "arts_centre": "centro de artes con exposiciones y talleres",
    "cinema": "cine o sala de proyecciones",
    "community_centre": "centro comunitario o cultural",
    "events_venue": "sala de eventos o espectáculos",
    "library": "biblioteca pública o comunitaria",
    "theatre": "teatro con programación cultural",
    # Recreación
    "dog_park": "parque canino o área para mascotas",
    "firepit": "fogón o área de fogata",
    "fishing": "zona de pesca deportiva o recreativa",
    "garden": "jardín botánico o área verde ornamental",
    "marina": "marina o puerto deportivo",
    "nature_reserve": "reserva natural con flora y fauna nativa",
    "park": "parque urbano o natural para recreación",
    "picnic_table": "mesa de picnic en área verde",
    "playground": "área de juegos infantiles",
    "sports_centre": "centro deportivo con instalaciones",
    "stadium": "estadio o cancha deportiva",
    "swimming_area": "área de natación natural",
    "swimming_pool": "piscina o alberca",
    "track": "pista o circuito deportivo",
    "water_park": "parque acuático",
    "common": "área verde comunitaria",
    "bird_hide": "observatorio de aves",
    # Servicios
    "toilets": "baños públicos",
    "public_bath": "baño público o termal",
    "fuel": "estación de servicio o combustibles",
    "atm": "cajero automático",
    "bank": "banco o entidad financiera",
    "pharmacy": "farmacia o botica",
    "clinic": "clínica o centro de salud",
    "hospital": "hospital o centro médico",
    "police": "comisaría o puesto policial",
    "post_office": "oficina de correos",
    "charging_station": "estación de carga eléctrica",
    "bureau_de_change": "casa de cambio de moneda",
    "drinking_water": "fuente de agua potable",
    "ranger_station": "estación de guardaparques",
    "recycling": "punto de reciclaje",
    "shower": "duchas públicas",
    "veterinary": "veterinaria o centro de salud animal",
    # Transporte
    "parking": "estacionamiento público",
    "bicycle_parking": "estacionamiento para bicicletas",
    "bicycle_rental": "alquiler de bicicletas",
    "bus_station": "estación de buses",
    "car_rental": "alquiler de autos",
    "ferry_terminal": "terminal de ferry o embarcadero",
    "taxi": "parada de taxi",
    # Comercio
    "marketplace": "mercado o feria local",
    "souvenir": "tienda de recuerdos y artesanías",
    "bakery": "panadería artesanal",
    "supermarket": "supermercado o minimarket",
    "convenience": "tienda de conveniencia",
    "alcohol": "licorería o vinoteca",
    "butcher": "carnicería",
    "coffee": "tienda de café",
    "tea": "tienda de té",
    "wine": "vinoteca o tienda de vinos",
    "outdoor": "tienda de equipos outdoor",
    "sports": "tienda de artículos deportivos",
    "travel_agency": "agencia de viajes",
    "farm": "feria o venta de productos de granja",
    # Estructuras
    "lighthouse": "faro costero o marítimo",
    "tower": "torre o mirador elevado",
    "bridge": "puente o pasarela",
    "pier": "muelle o embarcadero",
    "beacon": "señal o baliza luminosa",
    "cross": "cruz o monumento religioso",
    "obelisk": "obelisco o monumento conmemorativo",
    "observatory": "observatorio astronómico o natural",
    "survey_point": "punto de referencia topográfica",
    "water_tower": "torre de agua",
    "watermill": "molino de agua",
    # Otros
    "trail": "sendero o camino de trekking",
    "hiking": "ruta de senderismo",
    "route": "ruta o recorrido turístico",
    "foot": "sendero peatonal",
    "horse": "ruta ecuestre",
    "bicycle": "ciclovía o ruta ciclista",
    "mtb": "ruta de mountain bike",
}

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "Naturaleza": "Atractivo natural en la Región de La Araucanía, ideal para conectar con el entorno.",
    "Gastronomía": "Espacio gastronómico que ofrece opciones culinarias en la zona.",
    "Turismo": "Punto de interés turístico que destaca en la Región de La Araucanía.",
    "Alojamiento": "Opción de hospedaje para visitantes en la zona.",
    "Cultura": "Espacio cultural con relevancia histórica o artística local.",
    "Trekking/Senderismo": "Ruta o sendero apto para caminatas y exploración natural.",
    "Lagos/Ríos/Playas": "Cuerpo de agua o zona costera con acceso para visitantes.",
    "Montañas/Volcanes/Miradores": "Elevación natural o mirador con vistas panorámicas.",
    "Termas/Bienestar": "Centro de termas o spa para relajo y bienestar.",
    "Parques/Reservas": "Área protegida o parque con valor natural o recreativo.",
    "Museos/Patrimonio": "Museo o sitio patrimonial con relevancia histórica.",
    "Aventura/Deportes": "Espacio para actividades deportivas o de aventura.",
    "Servicios turísticos/Información": "Punto de información o apoyo para turistas.",
    "Transporte/Accesos": "Punto de acceso o transporte para movilidad en la zona.",
    "Artesanía/Compras locales": "Espacio para compras de artesanía o productos locales.",
}

STRICT_BLACKLIST = {
    "amenity": {
        "grave_yard", "crematorium", "funeral_hall",
        "toilets", "public_bath",
        "fuel", "atm", "bank", "bureau_de_change",
        "parking",
        "recycling", "waste_disposal", "waste_transfer_station",
        "veterinary",
    },
    "landuse": {
        "cemetery", "industrial", "landfill", "quarry",
        "military", "brownfield", "construction",
    },
    "shop": {
        "car", "car_repair", "car_parts", "tyres",
        "hardware", "doityourself", "electronics",
        "computer", "mobile_phone", "chemist",
        "laundry", "dry_cleaning", "hairdresser",
        "beauty", "massage", "tattoo",
        "optician", "jewelry", "furniture",
        "appliance", "carpet", "curtain",
        "fabric", "paint", "trade",
        "wholesale", "kiosk",
    },
    "man_made": {
        "wastewater_plant", "water_works", "pumping_station",
        "communications_tower", "surveillance", "street_cabinet",
        "pipeline", "storage_tank", "silo",
    },
    "highway": {
        "services", "rest_area",
    },
}


def _is_strictly_blacklisted(tags: dict[str, str]) -> bool:
    """Return True when a candidate is a pure non-touristic/logistic POI."""
    has_explicit_tourism_value = bool(clean_text(tags.get("tourism")))
    if has_explicit_tourism_value:
        return False

    for key, blacklist in STRICT_BLACKLIST.items():
        value = tags.get(key)
        if value and value in blacklist:
            return True
    return False


def _humanize_tag(tag: str) -> str:
    return OSM_TAG_HUMANIZED.get(tag, tag.replace("_", " "))


OSM_VALUE_HUMANIZED: dict[str, str] = {
    "chilean": "chilena",
    "regional": "regional",
    "local": "local",
    "italian": "italiana",
    "pizza": "pizza",
    "coffee_shop": "café",
    "coffee": "café",
    "sandwich": "sándwiches",
    "burger": "hamburguesas",
    "seafood": "mariscos",
    "fish": "pescados",
    "steak_house": "parrilla",
    "barbecue": "parrilla",
    "ice_cream": "helados",
    "bakery": "panadería",
    "latin_american": "latinoamericana",
    "international": "internacional",
    "vegetarian": "vegetariana",
}


def _humanize_list(value: str) -> str:
    parts = [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    if not parts:
        return value.replace("_", " ")
    return ", ".join(OSM_VALUE_HUMANIZED.get(part, part.replace("_", " ")) for part in parts)


def describe_place_type(tags: dict[str, str]) -> str:
    tourism = tags.get("tourism")
    amenity = tags.get("amenity")
    landuse = tags.get("landuse")
    leisure = tags.get("leisure")
    natural = tags.get("natural")
    historic = tags.get("historic")
    shop = tags.get("shop")
    craft = tags.get("craft")
    sport = tags.get("sport")
    man_made = tags.get("man_made")
    waterway = tags.get("waterway")
    place = tags.get("place")
    highway = tags.get("highway")
    railway = tags.get("railway")
    route = tags.get("route")

    if amenity in FOOD_AMENITIES:
        cuisine = clean_text(tags.get("cuisine"))
        if cuisine:
            food_base = {
                "restaurant": "restaurante",
                "cafe": "cafetería",
                "fast_food": "local de comida rápida",
                "bar": "bar",
                "pub": "pub",
                "food_court": "patio de comidas",
                "ice_cream": "heladería",
            }.get(amenity, _humanize_tag(amenity))
            return f"{food_base} con especialidad {_humanize_list(cuisine)}"
        return _humanize_tag(amenity)

    if amenity in CEMETERY_AMENITIES or landuse == "cemetery":
        return "cementerio o memorial"

    if landuse in {"industrial", "landfill"}:
        return f"zona de uso {landuse.replace('_', ' ')}"

    if amenity in CULTURE_AMENITIES:
        return _humanize_tag(amenity)

    if amenity in TRANSPORT_AMENITIES or highway == "bus_stop" or railway in {"station", "halt"}:
        tag_key = amenity or highway or railway
        return _humanize_tag(tag_key) if tag_key else "punto de transporte o acceso"

    if amenity in SERVICE_AMENITIES:
        return _humanize_tag(amenity)

    if leisure in RELEVANT_LEISURE:
        return _humanize_tag(leisure)

    if natural in NATURAL_FEATURES:
        return _humanize_tag(natural)

    if historic:
        tag_val = _humanize_tag(historic)
        return f"hito histórico o patrimonial: {tag_val}"

    if shop:
        return _humanize_tag(shop)

    if craft:
        tag_val = _humanize_tag(craft)
        return f"actividad artesanal o productiva: {tag_val}"

    if sport:
        tag_val = _humanize_tag(sport)
        return f"espacio deportivo relacionado con {tag_val}"

    if man_made:
        return _humanize_tag(man_made)

    if waterway:
        tag_val = _humanize_tag(waterway)
        return f"curso o cuerpo de agua: {tag_val}"

    if place:
        return f"localidad o referencia territorial: {place.replace('_', ' ')}"

    if route:
        return _humanize_tag(route)

    if tourism:
        return _humanize_tag(tourism)

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
    cuisine = clean_text(tags.get("cuisine"))
    operator = clean_text(tags.get("operator"))

    category_names = infer_category_names(tags)
    fallback_desc = next(
        (CATEGORY_DESCRIPTIONS[cat_name] for cat_name in category_names if cat_name in CATEGORY_DESCRIPTIONS),
        CATEGORY_DESCRIPTIONS["Turismo"],
    )

    base = f"{name} es un lugar descrito como {place_type} en la Región de La Araucanía, Chile. {fallback_desc}"
    if locality:
        base += f" Se ubica o referencia en el sector de {locality}."
    if cuisine and _humanize_list(cuisine) not in place_type:
        base += f" Se destaca por su cocina o especialidad en {_humanize_list(cuisine)}."
    if operator:
        base += f" Operado por {operator}."
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
    if image and (image.startswith("http://") or image.startswith("https://")):
        payload["image"] = image
        payload["cover"] = image
        payload["gallery"] = [image]
    if wikipedia:
        payload["wikipedia"] = wikipedia

    relevant_osm_tag_keys = {
        "amenity",
        "tourism",
        "leisure",
        "natural",
        "historic",
        "shop",
        "craft",
        "sport",
        "man_made",
        "waterway",
        "place",
        "highway",
        "railway",
        "public_transport",
        "route",
        "landuse",
        "industrial",
        "opening_hours",
        "description",
        "description:es",
        "cuisine",
        "wheelchair",
        "parking",
        "operator",
    }
    osm_tags = {key: value for key, value in tags.items() if key in relevant_osm_tag_keys}
    if osm_tags:
        payload["osm_tags"] = osm_tags

    return payload


def build_place(element: dict[str, Any]) -> OSMPlace | None:
    tags = {str(k): str(v) for k, v in (element.get("tags") or {}).items()}
    name = clean_text(tags.get("name"))
    if not name:
        return None

    if _is_strictly_blacklisted(tags):
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


async def get_existing_osm_poi(db, place: OSMPlace) -> POI | None:
    stmt = select(POI).where(
        POI.multimedia_urls.contains(
            {
                "source": "OpenStreetMap",
                "osm_type": place.osm_type,
                "osm_id": place.osm_id,
            }
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def delete_existing_osm_pois() -> int:
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                delete(POI).where(POI.multimedia_urls.contains({"source": "OpenStreetMap"}))
            )
            await db.commit()
            deleted_count = int(result.rowcount or 0)
            logger.warning("POIs OpenStreetMap eliminados antes de importar: %s", deleted_count)
            return deleted_count
        except Exception:
            await db.rollback()
            raise


def merge_multimedia_payload(existing_media: object, new_media: dict[str, Any] | None) -> dict[str, Any] | list[Any] | None:
    if not new_media:
        return existing_media if isinstance(existing_media, (dict, list)) else None

    if isinstance(existing_media, dict):
        merged = dict(existing_media)
        merged.update(new_media)
        return merged

    if isinstance(existing_media, list):
        return {
            "gallery": existing_media,
            **new_media,
        }

    return new_media


def calculate_osm_confidence_score(place: OSMPlace, category_ids: list[int]) -> float:
    """Score OSM POI quality using the same 0.0-1.0 confidence scale as user-created POIs."""
    media = place.multimedia_urls or {}
    score = 0.55

    if category_ids:
        score += 0.1
    if len(place.description or "") >= 120:
        score += 0.15
    elif len(place.description or "") >= 60:
        score += 0.1
    elif len(place.description or "") >= 30:
        score += 0.05
    if place.opening_hours_text:
        score += 0.1
    if place.phone or place.email:
        score += 0.05
    if media.get("website") or media.get("wikipedia"):
        score += 0.1
    if media.get("image") or media.get("cover") or media.get("gallery"):
        score += 0.05

    visit_rules = place.visit_rules or {}
    if visit_rules.get("blocked_for_itinerary"):
        score -= 0.15

    return min(max(round(score, 2), 0.0), 1.0)


def should_refresh_description(existing_description: str | None, place: OSMPlace, refresh_embeddings: bool) -> bool:
    if refresh_embeddings:
        return True
    cleaned_existing = clean_text(existing_description)
    if not cleaned_existing:
        return True
    return len(cleaned_existing) < 40 and len(place.description) > len(cleaned_existing)


async def update_existing_osm_poi(
    db,
    poi: POI,
    place: OSMPlace,
    category_ids: list[int],
    embedding: list[float] | None,
    *,
    refresh_embeddings: bool,
) -> None:
    poi.name = place.name
    if should_refresh_description(poi.description, place, refresh_embeddings):
        poi.description = place.description
    if embedding is not None:
        poi.description_embedding = embedding
    poi.location = from_text(f"POINT({place.longitude} {place.latitude})", srid=4326)
    poi.access_type = place.access_type
    poi.contact_phone = place.phone
    poi.contact_email = place.email
    poi.multimedia_urls = merge_multimedia_payload(poi.multimedia_urls, place.multimedia_urls)
    poi.opening_hours_text = place.opening_hours_text
    poi.visit_rules = place.visit_rules
    poi.verification_status = "verified"
    poi.confidence_score = calculate_osm_confidence_score(place, category_ids)

    await db.execute(delete(POICategory).where(POICategory.poi_id == poi.id))
    for category_id in category_ids:
        db.add(POICategory(poi_id=poi.id, category_id=category_id))


async def create_osm_poi(
    db,
    place: OSMPlace,
    category_ids: list[int],
    embedding: list[float],
) -> POI:
    poi = POI(
        entrepreneur_id=None,
        name=place.name,
        description=place.description,
        description_embedding=embedding,
        location=from_text(f"POINT({place.longitude} {place.latitude})", srid=4326),
        access_type=place.access_type,
        contact_phone=place.phone,
        contact_email=place.email,
        multimedia_urls=place.multimedia_urls,
        opening_hours_text=place.opening_hours_text,
        visit_rules=place.visit_rules,
        verification_status="verified",
        confidence_score=calculate_osm_confidence_score(place, category_ids),
    )
    db.add(poi)
    await db.flush()

    for category_id in category_ids:
        db.add(POICategory(poi_id=poi.id, category_id=category_id))

    return poi


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
    *,
    update_existing: bool,
    refresh_embeddings: bool,
) -> ImportStatus:
    eta = calculate_eta(started_at, position - 1, total)
    logger.info("Importando %s/%s: %s... ETA: %s", position, total, place.name, eta)

    try:
        category_ids = [category_map[name] for name in place.category_names if name in category_map]

        async with AsyncSessionLocal() as db:
            existing_poi = await get_existing_osm_poi(db, place)
            if existing_poi is not None:
                if not update_existing:
                    logger.info(
                        "Checkpoint: omitido porque ya existía como POI OSM: %s",
                        place.name,
                    )
                    return ImportStatus.SKIPPED

                embedding: list[float] | None = None
                description_needs_refresh = should_refresh_description(
                    existing_poi.description,
                    place,
                    refresh_embeddings,
                )
                if refresh_embeddings or existing_poi.description_embedding is None or description_needs_refresh:
                    await rate_limiter.wait_turn()
                    if embedding_service is None:
                        raise RuntimeError("Embedding service is not initialized.")
                    embedding = await embedding_service.get_embedding(place.description)

                await update_existing_osm_poi(
                    db,
                    existing_poi,
                    place,
                    category_ids,
                    embedding,
                    refresh_embeddings=refresh_embeddings,
                )
                await db.commit()
                if embedding is None:
                    logger.info("Actualizado sin regenerar embedding: %s", place.name)
                else:
                    logger.info("Actualizado regenerando embedding: %s", place.name)
                return ImportStatus.UPDATED

        await rate_limiter.wait_turn()
        if embedding_service is None:
            raise RuntimeError("Embedding service is not initialized.")

        embedding = await embedding_service.get_embedding(place.description)

        async with AsyncSessionLocal() as db:
            await create_osm_poi(
                db,
                place=place,
                category_ids=category_ids,
                embedding=embedding,
            )
            await db.commit()

        return ImportStatus.CREATED
    except Exception as exc:  # noqa: BLE001
        logger.exception("Falló la importación de %s (%s/%s): %s", place.name, position, total, exc)
        return ImportStatus.FAILED


async def process_places(
    elements: list[dict[str, Any]],
    batch_size: int,
    limit: int,
    *,
    update_existing: bool,
    refresh_embeddings: bool,
) -> None:
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

    created_total = 0
    updated_total = 0
    skipped_total = 0
    failed_total = 0
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
                update_existing=update_existing,
                refresh_embeddings=refresh_embeddings,
            )
            for index, place in enumerate(batch)
        ]
        results = await asyncio.gather(*tasks)
        created_total += sum(1 for result in results if result == ImportStatus.CREATED)
        updated_total += sum(1 for result in results if result == ImportStatus.UPDATED)
        skipped_total += sum(1 for result in results if result == ImportStatus.SKIPPED)
        failed_total += sum(1 for result in results if result == ImportStatus.FAILED)

        processed = min(batch_start + len(batch), total)
        logger.info(
            "Progreso: %s/%s procesados | nuevos: %s | actualizados: %s | omitidos: %s | fallidos: %s | ETA: %s",
            processed,
            total,
            created_total,
            updated_total,
            skipped_total,
            failed_total,
            calculate_eta(started_at, processed, total),
        )

    logger.info(
        "Ingesta finalizada. Nuevos: %s | Actualizados: %s | Omitidos: %s | Fallidos: %s",
        created_total,
        updated_total,
        skipped_total,
        failed_total,
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
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help=(
            "Actualiza POIs ya importados desde OSM en vez de omitirlos por checkpoint. "
            "Útil para agregar nuevas categorías, visit_rules, opening_hours_text y osm_tags."
        ),
    )
    parser.add_argument(
        "--refresh-embeddings",
        action="store_true",
        help=(
            "Regenera embeddings de POIs OSM existentes. Solo tiene efecto junto a --update-existing; "
            "los POIs nuevos siempre generan embedding."
        ),
    )
    parser.add_argument(
        "--delete-existing-osm",
        action="store_true",
        help=(
            "Elimina primero los POIs cuyo multimedia_urls.source sea OpenStreetMap y luego importa desde cero. "
            "Usar solo si quieres reconstruir la capa OSM; puede borrar relaciones históricas de esos POIs."
        ),
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
    if args.refresh_embeddings and not args.update_existing:
        logger.warning(
            "--refresh-embeddings fue indicado sin --update-existing; solo se generarán embeddings para POIs nuevos."
        )
    if args.delete_existing_osm:
        logger.warning(
            "Modo destructivo acotado activado: se eliminarán POIs OSM antes de importar. "
            "No se tocarán POIs manuales/no OSM."
        )
        await delete_existing_osm_pois()

    elements = await fetch_osm_elements(limit=args.limit)
    if not elements:
        logger.warning("Overpass no devolvió elementos para importar.")
        return

    await process_places(
        elements=elements,
        batch_size=args.batch_size,
        limit=args.limit,
        update_existing=args.update_existing,
        refresh_embeddings=args.refresh_embeddings,
    )


if __name__ == "__main__":
    asyncio.run(main())
