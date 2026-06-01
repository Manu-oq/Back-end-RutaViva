from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import app.db.models  # noqa: F401
from app.db.session import AsyncSessionLocal
from app.models.poi import POI
from app.models.poi_category import POICategory

GEO_RADIUS_METERS = 100.0
SEMANTIC_THRESHOLD = 0.85
MERGE_THRESHOLD = 0.95
OUTPUT_PATH = ROOT_DIR / "duplicate_pois.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detección batch de POIs duplicados por proximidad geográfica + similitud semántica.",
    )
    parser.add_argument("--radius", type=float, default=GEO_RADIUS_METERS)
    parser.add_argument("--threshold", type=float, default=SEMANTIC_THRESHOLD)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--merge", action="store_true", help="Ejecuta merge automatico de duplicados de alta confianza (sem >= 0.95).")
    parser.add_argument("--merge-threshold", type=float, default=MERGE_THRESHOLD, help="Umbral para merge automatico.")
    return parser.parse_args()


async def load_pois_with_categories() -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(POI).order_by(POI.name.asc())
        )
        pois = list(result.scalars().all())

        poi_data: list[dict[str, Any]] = []
        for poi in pois:
            cat_result = await db.execute(
                select(POICategory.category_id).where(POICategory.poi_id == poi.id)
            )
            category_ids = list(cat_result.scalars().all())
            poi_data.append({
                "id": poi.id,
                "name": poi.name,
                "description": poi.description,
                "category_ids": category_ids,
                "lat": func.ST_Y(poi.location),
                "lon": func.ST_X(poi.location),
            })
        return poi_data


async def find_duplicate_pairs(
    radius: float,
    threshold: float,
) -> list[dict[str, Any]]:
    duplicates: list[dict[str, Any]] = []

    async with AsyncSessionLocal() as db:
        join_query = text(f"""
            WITH pairs AS (
                SELECT
                    a.id AS poi_a,
                    b.id AS poi_b,
                    a.name AS name_a,
                    b.name AS name_b,
                    ST_Distance(a.location::geography, b.location::geography) AS distance_meters,
                    1.0 - (a.description_embedding <=> b.description_embedding) AS semantic_similarity
                FROM pois a
                JOIN pois b ON a.id < b.id
                    AND ST_DWithin(a.location::geography, b.location::geography, {radius})
                WHERE a.description_embedding IS NOT NULL
                    AND b.description_embedding IS NOT NULL
            )
            SELECT * FROM pairs
            WHERE (1.0 - semantic_similarity) >= {threshold}
            ORDER BY distance_meters ASC
        """)

        result = await db.execute(join_query)
        for row in result.all():
            poi_a, poi_b, name_a, name_b, distance, similarity = row
            duplicates.append({
                "poi_a": str(poi_a),
                "poi_b": str(poi_b),
                "name_a": name_a,
                "name_b": name_b,
                "distance_meters": round(float(distance), 1),
                "semantic_similarity": round(float(similarity), 3),
            })

    return duplicates


async def main() -> None:
    args = parse_args()

    print(f"Buscando duplicados: radio={args.radius}m, umbral={args.threshold}")
    duplicates = await find_duplicate_pairs(args.radius, args.threshold)

    mergeable = [d for d in duplicates if d["semantic_similarity"] >= args.merge_threshold]
    if mergeable:
        print(f"Duplicados mergeables (sim >= {args.merge_threshold}): {len(mergeable)}")
        for dup in mergeable[:10]:
            print(f"  {dup['name_a']} ↔ {dup['name_b']} ({dup['distance_meters']}m, sim={dup['semantic_similarity']})")

    if args.dry_run:
        print(f"Duplicados totales encontrados: {len(duplicates)}")
        if len(duplicates) > 20 and not args.merge:
            for dup in duplicates[:20]:
                print(
                    f"  {dup['name_a']} ↔ {dup['name_b']} "
                    f"({dup['distance_meters']}m, sim={dup['semantic_similarity']})"
                )
            if len(duplicates) > 20:
                print(f"  ... y {len(duplicates) - 20} más")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        for dup in duplicates:
            f.write(json.dumps(dup, ensure_ascii=False) + "\n")

    print(f"{len(duplicates)} pares duplicados guardados en {args.output}")

    if args.merge and mergeable:
        merge_path = args.output.with_suffix(".merge_candidates.jsonl")
        with merge_path.open("w", encoding="utf-8") as f:
            for dup in mergeable:
                f.write(json.dumps(dup, ensure_ascii=False) + "\n")
        print(f"{len(mergeable)} candidatos a merge guardados en {merge_path}")
        print("Revisa el archivo antes de ejecutar merge automatico.")


if __name__ == "__main__":
    asyncio.run(main())
