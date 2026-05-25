from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"


def run_step(label: str, command: list[str]) -> None:
    started_at = time.monotonic()
    printable = " ".join(command)
    print(f"\n▶ {label}\n  $ {printable}", flush=True)

    completed = subprocess.run(command, cwd=ROOT_DIR, check=False)
    elapsed = time.monotonic() - started_at

    if completed.returncode != 0:
        raise SystemExit(f"✗ Falló '{label}' con código {completed.returncode} después de {elapsed:.1f}s.")

    print(f"✓ {label} completado en {elapsed:.1f}s.", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Ejecuta el pipeline completo de POIs: categorías → OSM → recategorización "
            "→ enriquecimiento → índice vectorial."
        ),
    )
    parser.add_argument("--import-limit", type=int, default=11000, help="Límite para import_osm_data.py.")
    parser.add_argument("--import-batch-size", type=int, default=10, help="Batch size para import_osm_data.py.")
    parser.add_argument("--enrich-limit", type=int, default=500, help="Límite para enrich_poi_metadata.py.")
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Actualiza POIs OSM existentes durante la importación.",
    )
    parser.add_argument(
        "--refresh-import-embeddings",
        action="store_true",
        help="Regenera descripciones/embeddings de POIs OSM existentes durante la importación.",
    )
    parser.add_argument(
        "--delete-existing-osm",
        action="store_true",
        help="Elimina POIs OSM existentes antes de importar desde cero.",
    )
    parser.add_argument(
        "--no-refresh-enrich-embeddings",
        action="store_true",
        help="No regenerar embeddings después del enriquecimiento.",
    )
    parser.add_argument("--skip-import", action="store_true", help="Omite import_osm_data.py.")
    parser.add_argument("--skip-recategorize", action="store_true", help="Omite recategorize_pois.py.")
    parser.add_argument("--skip-enrich", action="store_true", help="Omite enrich_poi_metadata.py.")
    parser.add_argument("--skip-indices", action="store_true", help="Omite create_vector_indices.py.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    python = sys.executable

    run_step("Seed de categorías", [python, str(SCRIPTS_DIR / "seed_categories.py")])

    if not args.skip_import:
        import_command = [
            python,
            str(SCRIPTS_DIR / "import_osm_data.py"),
            "--limit",
            str(args.import_limit),
            "--batch-size",
            str(args.import_batch_size),
        ]
        if args.update_existing or args.refresh_import_embeddings:
            import_command.append("--update-existing")
        if args.refresh_import_embeddings:
            import_command.append("--refresh-embeddings")
        if args.delete_existing_osm:
            import_command.append("--delete-existing-osm")
        run_step("Ingesta OSM desde Overpass", import_command)

    if not args.skip_recategorize:
        run_step("Recategorización de POIs", [python, str(SCRIPTS_DIR / "recategorize_pois.py")])

    if not args.skip_enrich:
        enrich_command = [
            python,
            str(SCRIPTS_DIR / "enrich_poi_metadata.py"),
            "--limit",
            str(args.enrich_limit),
        ]
        if not args.no_refresh_enrich_embeddings:
            enrich_command.append("--refresh-embeddings")
        run_step("Enriquecimiento de metadata", enrich_command)

    if not args.skip_indices:
        run_step("Creación de índice vectorial HNSW", [python, str(SCRIPTS_DIR / "create_vector_indices.py")])

    print("\n✓ Pipeline completo finalizado correctamente.", flush=True)


if __name__ == "__main__":
    main()
