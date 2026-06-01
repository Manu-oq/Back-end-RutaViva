from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT_DIR / "data" / "conaf_protected_areas.json"

CONAF_SITEMAP_URL = "https://www.conaf.cl/parque_nacionales-sitemap.xml"
CONAF_BASE_URL = "https://www.conaf.cl"
REQUEST_DELAY_SECONDS = 1.0

logger = logging.getLogger("conaf_scraper")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrapea datos detallados de parques CONAF desde sus paginas web oficiales."
    )
    parser.add_argument("--region", type=str, default="La Araucanía",
                       help="Region a filtrar (default: 'La Araucanía').")
    parser.add_argument("--output", type=Path, default=DATA_FILE,
                       help=f"Archivo JSON de salida (default: {DATA_FILE}).")
    parser.add_argument("--dry-run", action="store_true",
                       help="Solo muestra las URLs que se scrapearian.")
    parser.add_argument("--limit", type=int, default=0,
                       help="Maximo de paginas a scrapear (0=todas).")
    return parser.parse_args()


async def fetch_sitemap_urls() -> list[str]:
    logger.info("Fetching sitemap: %s", CONAF_SITEMAP_URL)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(CONAF_SITEMAP_URL)
        response.raise_for_status()

    urls = re.findall(r"<loc>(https://www\.conaf\.cl/parque_nacionales/[^<]+)</loc>", response.text)
    unique_urls = list(dict.fromkeys(urls))
    logger.info("Sitemap contiene %s URLs de parques", len(unique_urls))
    return unique_urls


def extract_field(text: str, field: str) -> str | None:
    pattern = rf"{re.escape(field)}\s*(.+?)(?:\n|$)"
    match = re.search(pattern, text)
    if match:
        return match.group(1).strip()
    return None


def extract_section(text: str, start_header: str, end_header: str | None = None) -> str | None:
    escaped = re.escape(start_header)
    if end_header:
        end_escaped = re.escape(end_header)
        pattern = rf"{escaped}\s*\n(.*?)\n\s*{end_escaped}"
    else:
        pattern = rf"{escaped}\s*\n((?:(?!\n\w).)*)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def extract_trails(text: str) -> list[dict[str, str]]:
    trails: list[dict[str, str]] = []
    trail_blocks = re.split(r"\n(?=Sendero )", text)

    for block in trail_blocks:
        name_match = re.match(r"Sendero (.+)", block)
        if not name_match:
            continue
        trail: dict[str, str] = {"name": name_match.group(1).strip()}
        for field in ["Longitud", "Duración del trayecto", "Dificultad de caminata",
                       "Dificultad de caminata invernal", "Riesgos del sector"]:
            value = extract_field(block, field)
            if value:
                key = field.lower().replace(" ", "_").replace("ó", "o")
                trail[key] = value.replace(":", "").strip()
        trails.append(trail)

    return trails


def extract_prohibitions(text: str) -> list[str]:
    items = re.findall(r"(?:^|\n)(?:No |Está prohibido |Se prohíbe )(.+?)(?:\n|$)", text)
    if not items:
        items = re.findall(r"[•-]\s*(.+?)(?:\n|$)", text)
    return [item.strip() for item in items if len(item.strip()) > 10]


def clean_html(raw_html: str) -> str:
    clean = re.sub(r"<script[^>]*>.*?</script>", "", raw_html, flags=re.DOTALL)
    clean = re.sub(r"<style[^>]*>.*?</style>", "", clean, flags=re.DOTALL)
    clean = re.sub(r"<noscript[^>]*>.*?</noscript>", "", clean, flags=re.DOTALL)
    clean = re.sub(r"<svg[^>]*>.*?</svg>", "", clean, flags=re.DOTALL)
    clean = re.sub(r"<br\s*/?>", "\n", clean)
    clean = re.sub(r"</?p[^>]*>", "\n", clean)
    clean = re.sub(r"</?li[^>]*>", "\n", clean)
    clean = re.sub(r"</?h\d[^>]*>", "\n", clean)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"&nbsp;", " ", clean)
    clean = re.sub(r"&aacute;", "á", clean)
    clean = re.sub(r"&eacute;", "é", clean)
    clean = re.sub(r"&iacute;", "í", clean)
    clean = re.sub(r"&oacute;", "ó", clean)
    clean = re.sub(r"&uacute;", "ú", clean)
    clean = re.sub(r"&ntilde;", "ñ", clean)
    clean = re.sub(r"&amp;", "&", clean)
    clean = re.sub(r"\n\s*\n\s*\n+", "\n\n", clean)
    clean = re.sub(r" {2,}", " ", clean)
    return clean.strip()


async def scrape_park_page(url: str, client: httpx.AsyncClient) -> dict[str, Any] | None:
    try:
        response = await client.get(url)
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return None

    text = clean_html(response.text)

    region_match = re.search(r"Región de La Araucanía", text, re.IGNORECASE)
    if not region_match:
        return None

    name = extract_field(text, "Unidad") or extract_field(text, "Parque Nacional") or url.rstrip("/").split("/")[-1].replace("-", " ").title()

    park: dict[str, Any] = {
        "name": name,
        "url": url,
        "superficie_ha": extract_field(text, "Superficie"),
        "provincias": extract_field(text, "Provincias"),
        "comunas": extract_field(text, "Comunas"),
    }

    general = extract_section(text, "Datos generales", "Flora")
    if general:
        park["datos_generales"] = general

    flora = extract_section(text, "Flora", "Fauna silvestre") or extract_section(text, "Flora", "Fauna")
    if flora:
        park["flora"] = flora

    fauna = extract_section(text, "Fauna silvestre", "Servicios") or extract_section(text, "Fauna", "Servicios")
    if fauna:
        park["fauna"] = fauna

    services = extract_section(text, "Servicios", "Senderos habilitados") or extract_section(text, "Servicios", "Sendero")
    if services:
        park["servicios"] = services

    trails_text = extract_section(text, "Senderos habilitados", "Accesos")
    if trails_text:
        trails = extract_trails(trails_text)
        if trails:
            park["senderos"] = trails
            park["num_senderos"] = len(trails)

    access = extract_section(text, "Accesos", "Prohibiciones")
    if access:
        park["accesos"] = access

    prohibitions_text = extract_section(text, "Prohibiciones", "Recomendaciones")
    if prohibitions_text:
        park["prohibiciones"] = extract_prohibitions(prohibitions_text)

    recommendations = extract_section(text, "Recomendaciones", "Información de contacto")
    if recommendations:
        park["recomendaciones"] = recommendations

    contact = extract_section(text, "Información de contacto", None)
    if contact:
        park["informacion_contacto"] = contact

    email_match = re.search(r"([\w.+-]+@[\w-]+\.[\w.]+)", text)
    if email_match:
        park["email"] = email_match.group(1)

    website_match = re.search(r"(www\.[\w.-]+\.[a-z]{2,})", text)
    if website_match:
        park["website_concesionario"] = website_match.group(1)

    return park


def is_araucania_park(url: str) -> bool:
    araucania_slugs = {
        "parque-nacional-conguillio",
        "parque-nacional-villarrica",
        "parque-nacional-huerquehue",
        "parque-nacional-nahuelbuta",
        "parque-nacional-tolhuaca",
        "reserva-nacional-malalcahuello",
        "reserva-nacional-nalcas",
        "reserva-nacional-alto-biobio",
        "reserva-nacional-china-muerta",
        "reserva-nacional-malleco",
        "reserva-nacional-villarrica-o-hualalafquen",
        "monumento-natural-cerro-nielol",
        "monumento-natural-contulmo",
        "monumento-natural-cavernas-de-caren",
        "reserva-nacional-villarrica",
    }
    url_lower = url.lower()
    return any(slug in url_lower for slug in araucania_slugs)


async def scrape_all_parks(args: argparse.Namespace) -> list[dict[str, Any]]:
    urls = await fetch_sitemap_urls()
    urls = [u for u in urls if is_araucania_park(u)]

    if args.limit > 0:
        urls = urls[:args.limit]

    logger.info("Scrapeando %s parques de La Araucanía...", len(urls))

    parks: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True,
                                 headers={"User-Agent": "RutaVivaCONAFScraper/0.1"}) as client:
        for i, url in enumerate(urls, start=1):
            logger.info("[%s/%s] %s", i, len(urls), url)
            park = await scrape_park_page(url, client)
            if park:
                parks.append(park)
                logger.info("  ✓ %s (%s senderos)", park["name"], park.get("num_senderos", 0))
            else:
                logger.info("  ✗ No es de La Araucanía o falló")
            await asyncio.sleep(REQUEST_DELAY_SECONDS)

    return parks


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def _normalize_name(name: str) -> str:
    return name.lower().replace("parque nacional ", "").replace("reserva nacional ", "").replace("monumento natural ", "").strip()


def _match_curated(scraped_name: str, curated_areas: list[dict[str, Any]]) -> dict[str, Any] | None:
    scraped_norm = _normalize_name(scraped_name)
    for area in curated_areas:
        curated_norm = _normalize_name(area.get("name", ""))
        common_words = set(scraped_norm.split()) & set(curated_norm.split())
        if len(common_words) >= 2 or scraped_norm == curated_norm or curated_norm in scraped_norm:
            return area
    return None


def _build_enriched_description(scraped: dict[str, Any], curated: dict[str, Any] | None) -> str:
    parts: list[str] = []
    datos = scraped.get("datos_generales", "")
    if datos:
        parts.append(datos.strip().rstrip("."))
    flora = scraped.get("flora", "")
    if flora:
        parts.append(f"Flora destacada: {flora.strip().rstrip('.')}.")
    fauna = scraped.get("fauna", "")
    if fauna:
        parts.append(f"Fauna silvestre: {fauna.strip().rstrip('.')}.")
    if curated and curated.get("area_hectares"):
        parts.append(f"Superficie: {curated['area_hectares']:,} hectareas.".replace(",", "."))
    servicios = scraped.get("servicios", "")
    if servicios:
        clean_serv = servicios.strip().rstrip(".")[:300]
        parts.append(f"Servicios: {clean_serv}.")
    return " ".join(parts)


def _build_enriched_visit_rules(scraped: dict[str, Any], curated: dict[str, Any] | None) -> dict[str, Any]:
    rules: dict[str, Any] = {
        "is_primary_experience": True,
        "requires_daylight": True,
        "night_suitable": False,
        "latest_recommended_start_time": "15:30",
        "access_notes": "Area silvestre protegida CONAF. Verificar horarios en pasesparques.cl.",
        "confidence": "known",
        "source": "CONAF",
    }
    if curated:
        rules["area_type"] = curated.get("type")
        rules["region"] = curated.get("region")
        rules["commune"] = curated.get("commune")
    senderos = scraped.get("senderos")
    if senderos:
        rules["trails"] = senderos
        rules["num_trails"] = len(senderos)
    accesos = scraped.get("accesos")
    if accesos:
        rules["access_routes"] = accesos.strip()
    prohibiciones = scraped.get("prohibiciones")
    if prohibiciones:
        rules["prohibitions"] = prohibiciones
    recomendaciones = scraped.get("recomendaciones")
    if recomendaciones:
        rules["recommendations"] = recomendaciones.strip()
    return rules


async def main() -> None:
    configure_logging()
    args = parse_args()

    if args.dry_run:
        urls = await fetch_sitemap_urls()
        urls = [u for u in urls if is_araucania_park(u)]
        print(f"Parques a scrapear: {len(urls)}")
        for url in urls:
            print(f"  {url}")
        return

    existing = {}
    if args.output.exists():
        try:
            existing = json.loads(args.output.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    curated_areas = existing.get("protected_areas", [])

    scraped_parks = await scrape_all_parks(args)

    enriched_areas: list[dict[str, Any]] = []
    matched_curated = set()

    for scraped in scraped_parks:
        curated = _match_curated(scraped.get("name", ""), curated_areas)
        if curated:
            matched_curated.add(curated.get("name", ""))

        enriched: dict[str, Any] = {
            "name": curated.get("name", scraped.get("name", "")),
            "type": curated.get("type", "") if curated else "",
            "latitude": curated.get("latitude") if curated else None,
            "longitude": curated.get("longitude") if curated else None,
            "region": curated.get("region", "La Araucanía") if curated else "La Araucanía",
            "commune": curated.get("commune", "") if curated else "",
            "area_hectares": curated.get("area_hectares") if curated else None,
            "website": curated.get("website") if curated else scraped.get("url", ""),
        }

        enriched["description"] = _build_enriched_description(scraped, curated)
        enriched["visit_rules"] = _build_enriched_visit_rules(scraped, curated)

        enriched_areas.append(enriched)

    for curated in curated_areas:
        if curated.get("name") not in matched_curated:
            enriched_areas.append(dict(curated))

    output = {
        "source": "CONAF (curado + scraped de conaf.cl)",
        "source_url": "https://www.conaf.cl/parque_nacionales-sitemap.xml",
        "total_parks": len(enriched_areas),
        "protected_areas": enriched_areas,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Dataset enriquecido guardado: %s areas (%s con datos scrapeados)",
                len(enriched_areas), len(scraped_parks))
    logger.info("Datos guardados en %s (%s parques)", args.output, len(parks))


if __name__ == "__main__":
    asyncio.run(main())
