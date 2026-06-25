from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.sql import func

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import app.db.models  # noqa: F401
from app.db.session import AsyncSessionLocal
from app.models.poi_category import POICategory

PARENT_TO_CHILDREN: dict[int, set[int]] = {
    1: {6, 7, 8, 10},
    5: {11},
}


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Limpia categorías padre cuando un POI ya tiene la subcategoría hija."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo reporta cambios, sin aplicar.",
    )
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(POICategory))).scalars().all()

        poi_categories: dict[str, set[int]] = defaultdict(set)
        for row in rows:
            poi_categories[str(row.poi_id)].add(row.category_id)

        total_pois = len(poi_categories)
        affected = 0
        deletions = 0

        for poi_id_str, category_set in poi_categories.items():
            to_remove: set[int] = set()
            for parent_id, child_ids in PARENT_TO_CHILDREN.items():
                has_parent = parent_id in category_set
                children_present = category_set & child_ids
                if has_parent and children_present:
                    to_remove.add(parent_id)

            if to_remove:
                affected += 1
                new_set = category_set - to_remove
                deletions += len(to_remove)
                print(
                    f"POI {poi_id_str}: removiendo padre(s) {sorted(to_remove)} "
                    f"→ categorías finales {sorted(new_set)} ({len(new_set)})"
                )

                if not args.dry_run:
                    for parent_id in to_remove:
                        await db.execute(
                            delete(POICategory).where(
                                POICategory.poi_id == poi_id_str,
                                POICategory.category_id == parent_id,
                            )
                        )

        if not args.dry_run:
            await db.commit()

        verb = "Simulado" if args.dry_run else "Ejecutado"
        print(
            f"\n=== {verb} ===\n"
            f"Total POIs revisados: {total_pois}\n"
            f"POIs modificados: {affected}\n"
            f"Registros eliminados: {deletions}"
        )

        result = await db.execute(
            select(func.count(func.distinct(POICategory.poi_id)))
        )
        total_after = result.scalar() or 0

        result = await db.execute(
            select(POICategory.poi_id, func.count(POICategory.category_id).label("cnt"))
            .group_by(POICategory.poi_id)
            .having(func.count(POICategory.category_id) > 3)
            .order_by(func.count(POICategory.category_id).desc())
        )
        offenders = result.all()

        if offenders:
            print(f"\nADVERTENCIA: {len(offenders)} POIs aún superan 3 categorías:")
            for poi_id, count in offenders:
                print(f"  - {poi_id}: {count} categorías")
            sys.exit(2)
        else:
            print(f"\nVerificación OK: ningún POI supera 3 categorías ({total_after} POIs totales).")


if __name__ == "__main__":
    asyncio.run(main())
