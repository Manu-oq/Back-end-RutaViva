from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import app.db.models  # noqa: F401
from app.db.session import AsyncSessionLocal
from app.models.category import Category
from app.models.poi import POI
from app.models.poi_category import POICategory

QUALITY_DIR = ROOT_DIR / "quality_history"

GENERIC_DESCRIPTION_TERMS = (
    "punto de interés turístico",
    "ubicado en la región de la araucanía",
    "referencia territorial reportada por osm",
    "es un lugar descrito como",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera un snapshot de metricas de calidad de la base de datos de POIs y puede comparar dos snapshots.",
    )
    parser.add_argument("--label", type=str, default=None, help="Etiqueta para el snapshot (default: timestamp).")
    parser.add_argument("--output", type=Path, default=None, help="Ruta de salida (default: quality_history/<label>.json).")
    parser.add_argument("--compare", type=Path, default=None, nargs=2, metavar=("BEFORE", "AFTER"),
                       help="Compara dos snapshots y muestra mejoras/retrocesos.")
    return parser.parse_args()


async def collect_metrics() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        total_result = await db.execute(select(func.count(POI.id)))
        total_pois = total_result.scalar_one()

        if total_pois == 0:
            return {"total_pois": 0, "error": "No hay POIs en la base de datos."}

        verified_result = await db.execute(
            select(func.count(POI.id)).where(POI.verification_status == "verified")
        )
        verified = verified_result.scalar_one()

        avg_conf_result = await db.execute(
            select(func.avg(POI.confidence_score))
        )
        avg_confidence = round(float(avg_conf_result.scalar_one() or 0), 3)

        no_hours_result = await db.execute(
            select(func.count(POI.id)).where(
                POI.opening_hours_text.is_(None),
                POI.visit_rules["opening_hours_structured"].is_(None),
            )
        )
        no_hours = no_hours_result.scalar_one()

        short_desc_result = await db.execute(
            select(func.count(POI.id)).where(func.length(POI.description) < 80)
        )
        short_descriptions = short_desc_result.scalar_one()

        generic_desc_count = 0
        all_pois_result = await db.execute(select(POI.id, POI.description))
        for _, description in all_pois_result.all():
            desc_lower = (description or "").lower()
            if any(term in desc_lower for term in GENERIC_DESCRIPTION_TERMS):
                generic_desc_count += 1

        dist_result = await db.execute(text("""
            SELECT c.name, COUNT(pc.poi_id)
            FROM categories c
            LEFT JOIN poi_categories pc ON pc.category_id = c.id
            GROUP BY c.id, c.name
            ORDER BY COUNT(pc.poi_id) DESC
        """))
        category_dist: dict[str, int] = {
            row[0]: row[1] for row in dist_result.all()
        }

        by_verification: dict[str, int] = {}
        vf_result = await db.execute(
            select(POI.verification_status, func.count(POI.id)).group_by(POI.verification_status)
        )
        for status, count in vf_result.all():
            by_verification[status] = count

        confidence_buckets = {"0.0-0.3": 0, "0.3-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
        conf_result = await db.execute(select(POI.confidence_score))
        for (score,) in conf_result.all():
            s = score or 0
            if s < 0.3:
                confidence_buckets["0.0-0.3"] += 1
            elif s < 0.6:
                confidence_buckets["0.3-0.6"] += 1
            elif s < 0.8:
                confidence_buckets["0.6-0.8"] += 1
            else:
                confidence_buckets["0.8-1.0"] += 1

        source_result = await db.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE multimedia_urls->>'source' = 'OpenStreetMap') AS osm,
                COUNT(*) FILTER (WHERE multimedia_urls->>'source' = 'CONAF') AS conaf,
                COUNT(*) FILTER (WHERE entrepreneur_id IS NOT NULL) AS user_created,
                COUNT(*) FILTER (WHERE multimedia_urls->>'source' IS NULL AND entrepreneur_id IS NULL) AS unknown
            FROM pois
        """))
        source_row = source_result.one()
        by_source = {
            "osm": source_row[0],
            "conaf": source_row[1],
            "user_created": source_row[2],
            "unknown": source_row[3],
        }

        return {
            "total_pois": total_pois,
            "verified": verified,
            "verified_pct": round(verified / total_pois * 100, 1) if total_pois else 0,
            "avg_confidence": avg_confidence,
            "no_opening_hours": no_hours,
            "no_hours_pct": round(no_hours / total_pois * 100, 1) if total_pois else 0,
            "short_descriptions": short_descriptions,
            "short_desc_pct": round(short_descriptions / total_pois * 100, 1) if total_pois else 0,
            "generic_descriptions": generic_desc_count,
            "generic_desc_pct": round(generic_desc_count / total_pois * 100, 1) if total_pois else 0,
            "category_distribution": category_dist,
            "by_verification_status": by_verification,
            "confidence_buckets": confidence_buckets,
            "by_source": by_source,
        }


def compare_snapshots(before_path: Path, after_path: Path) -> dict[str, Any]:
    before = json.loads(before_path.read_text(encoding="utf-8"))
    after = json.loads(after_path.read_text(encoding="utf-8"))

    def delta(key: str) -> Any:
        b = before.get("metrics", {}).get(key, 0)
        a = after.get("metrics", {}).get(key, 0)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            return {"before": b, "after": a, "change": round(a - b, 3)}
        return {"before": b, "after": a}

    return {
        "before": before.get("label", str(before_path)),
        "after": after.get("label", str(after_path)),
        "comparison": {
            "total_pois": delta("total_pois"),
            "verified_pct": delta("verified_pct"),
            "avg_confidence": delta("avg_confidence"),
            "no_hours_pct": delta("no_hours_pct"),
            "short_desc_pct": delta("short_desc_pct"),
            "generic_desc_pct": delta("generic_desc_pct"),
            "category_distribution": delta("category_distribution"),
            "by_source": delta("by_source"),
        },
    }


async def main() -> None:
    args = parse_args()

    if args.compare:
        before_path, after_path = args.compare
        if not before_path.exists() or not after_path.exists():
            print(f"Error: uno de los archivos no existe: {before_path} / {after_path}")
            sys.exit(1)
        comparison = compare_snapshots(before_path, after_path)
        print(json.dumps(comparison, ensure_ascii=False, indent=2))
        return

    metrics = await collect_metrics()
    timestamp = datetime.now(timezone.utc).isoformat()
    label = args.label or datetime.now(timezone.utc).strftime("snapshot-%Y%m%d-%H%M%S")

    snapshot = {
        "label": label,
        "timestamp": timestamp,
        "metrics": metrics,
    }

    if args.output:
        output_path = args.output
    else:
        QUALITY_DIR.mkdir(parents=True, exist_ok=True)
        safe_label = label.replace("/", "-").replace(" ", "_")
        output_path = QUALITY_DIR / f"{safe_label}.json"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Snapshot guardado: {output_path}")
    print(f"  POIs totales: {metrics['total_pois']}")
    print(f"  Verificados: {metrics['verified_pct']}%")
    print(f"  Confianza promedio: {metrics['avg_confidence']}")
    print(f"  Sin horarios: {metrics['no_hours_pct']}%")
    print(f"  Descripciones cortas (<80c): {metrics['short_desc_pct']}%")
    print(f"  Descripciones genéricas: {metrics['generic_desc_pct']}%")

    if metrics.get("category_distribution"):
        print(f"  Categorías:")
        for cat, count in sorted(metrics["category_distribution"].items(), key=lambda x: -x[1]):
            print(f"    {cat}: {count}")


if __name__ == "__main__":
    asyncio.run(main())
