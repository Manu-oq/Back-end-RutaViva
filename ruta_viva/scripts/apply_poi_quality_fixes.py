from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import app.db.models  # noqa: F401
from app.db.session import AsyncSessionLocal
from app.models.poi import POI
from app.models.poi_category import POICategory


async def apply_issue(issue: dict, *, min_confidence: float, dry_run: bool) -> bool:
    if float(issue.get("confidence", 0)) < min_confidence:
        return False

    suggested_fix = issue.get("suggested_fix") or {}
    add_category_ids = [int(value) for value in suggested_fix.get("add_category_ids", [])]
    if not add_category_ids:
        return False

    poi_id = UUID(str(issue["poi_id"]))
    async with AsyncSessionLocal() as db:
        poi = await db.get(POI, poi_id)
        if poi is None:
            return False
        result = await db.execute(select(POICategory.category_id).where(POICategory.poi_id == poi_id))
        existing = set(result.scalars().all())
        to_add = [category_id for category_id in add_category_ids if category_id not in existing]
        if not to_add:
            return False
        print(f"{'DRY RUN ' if dry_run else ''}Aplicando categorías {to_add} a {poi.name} ({poi.id})")
        if dry_run:
            return True
        for category_id in to_add:
            db.add(POICategory(poi_id=poi_id, category_id=category_id))
        await db.commit()
        return True


async def main() -> None:
    parser = argparse.ArgumentParser(description="Aplica fixes seguros generados por audit_poi_quality.py.")
    parser.add_argument("input", type=Path, help="Archivo JSONL generado por audit_poi_quality.py")
    parser.add_argument("--min-confidence", type=float, default=0.85)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    applied = 0
    with args.input.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            issue = json.loads(line)
            if await apply_issue(issue, min_confidence=args.min_confidence, dry_run=args.dry_run):
                applied += 1
    print(json.dumps({"applied": applied, "dry_run": args.dry_run}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
