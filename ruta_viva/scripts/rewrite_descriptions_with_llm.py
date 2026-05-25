from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from openai import AsyncOpenAI
from sqlalchemy import func, select


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import app.db.models  # noqa: F401,E402
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.category import Category
from app.models.poi import POI
from app.models.poi_category import POICategory
from app.services.embedding_service import get_embedding_service


logger = logging.getLogger("rewrite_descriptions")

TECHNICAL_MARKERS = (
    "amenity:",
    "tourism:",
    "leisure:",
    "natural:",
    "shop:",
    "osm",
    " tipo peak",
    " tipo volcano",
    " tipo park",
    " tipo museum",
    " tipo viewpoint",
    " tipo camp_site",
    " tipo nature_reserve",
    " tipo dog_park",
    "atractivo natural tipo",
    "atractivo turístico tipo",
    "espacio cultural tipo",
    "área recreativa tipo",
    "servicio de apoyo para viajeros tipo",
)

GENERIC_MARKERS = (
    "punto de interés turístico ubicado en la región de la araucanía",
    "punto de interes turistico ubicado en la region de la araucania",
    "punto de interés turístico que destaca en la región de la araucanía",
    "punto de interes turistico que destaca en la region de la araucania",
)


def is_bad_description(description: str | None) -> bool:
    if not description:
        return True

    normalized = " ".join(description.lower().split())
    if len(normalized) < 60:
        return True
    if any(marker in normalized for marker in TECHNICAL_MARKERS):
        return True
    if any(marker in normalized for marker in GENERIC_MARKERS):
        return True
    return False


async def category_names_for_poi(db, poi_id) -> list[str]:
    result = await db.execute(
        select(Category.name)
        .join(POICategory, POICategory.category_id == Category.id)
        .where(POICategory.poi_id == poi_id)
        .order_by(Category.id.asc())
    )
    return list(result.scalars().all())


def build_prompt(poi_name: str, category_names: list[str], current_description: str) -> list[dict[str, str]]:
    categories = ", ".join(category_names) if category_names else "Turismo"
    return [
        {
            "role": "system",
            "content": (
                "Eres redactor turístico para Ruta Viva, una app de itinerarios en La Araucanía, Chile. "
                "Escribe en español neutro, natural y útil para viajeros. No inventes datos concretos "
                "como precios, horarios, direcciones exactas, dificultad o servicios si no aparecen en el texto."
            ),
        },
        {
            "role": "user",
            "content": (
                "Reescribe la descripción de este lugar turístico. Debe quedar en 1 o 2 frases, "
                "entre 60 y 260 caracteres, sin tecnicismos de OpenStreetMap, sin inglés innecesario "
                "y sin sonar robótica.\n\n"
                f"Nombre: {poi_name}\n"
                f"Categoría(s): {categories}\n"
                f"Descripción actual: {current_description}\n\n"
                "Devuelve solo la descripción final."
            ),
        },
    ]


def clean_model_description(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.replace('"', "").split()).strip()
    if not cleaned:
        return None
    return cleaned[:500]


async def rewrite_description(
    client: AsyncOpenAI,
    *,
    model: str,
    poi_name: str,
    category_names: list[str],
    current_description: str,
) -> str | None:
    response = await client.chat.completions.create(
        model=model,
        temperature=0.35,
        messages=build_prompt(poi_name, category_names, current_description),
        timeout=settings.gpt_mini_timeout_seconds,
    )
    return clean_model_description(response.choices[0].message.content)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reescribe con GPT descripciones malas, cortas o técnicas de POIs existentes.",
    )
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--model", default=settings.openai_gpt_mini_model)
    parser.add_argument("--refresh-embeddings", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=0.2, help="Pausa entre llamadas al LLM.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY es requerido para reescribir descripciones con LLM.")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    embedding_service = get_embedding_service() if args.refresh_embeddings and not args.dry_run else None

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(POI).order_by(func.length(POI.description).asc()))
        candidates = [poi for poi in result.scalars().all() if is_bad_description(poi.description)]
        candidates = candidates[: args.limit]

        logger.info("POIs candidatos para reescritura: %s", len(candidates))

        rewritten = 0
        for index, poi in enumerate(candidates, start=1):
            category_names = await category_names_for_poi(db, poi.id)
            logger.info("Procesando %s/%s: %s", index, len(candidates), poi.name)

            next_description = await rewrite_description(
                client,
                model=args.model,
                poi_name=poi.name,
                category_names=category_names,
                current_description=poi.description,
            )
            await asyncio.sleep(args.delay)

            if not next_description:
                logger.warning("GPT no devolvió descripción para %s", poi.name)
                continue

            if args.dry_run:
                logger.info("DRY RUN | %s\n  Antes: %s\n  Después: %s", poi.name, poi.description, next_description)
                rewritten += 1
                continue

            poi.description = next_description
            if embedding_service is not None:
                poi.description_embedding = await embedding_service.get_embedding(f"{poi.name}. {poi.description}")
            rewritten += 1

            if rewritten % 25 == 0:
                await db.commit()
                logger.info("Commit parcial: %s POIs reescritos.", rewritten)

        if not args.dry_run:
            await db.commit()

        logger.info("Finalizado. Descripciones reescritas: %s/%s", rewritten, len(candidates))


if __name__ == "__main__":
    asyncio.run(main())
