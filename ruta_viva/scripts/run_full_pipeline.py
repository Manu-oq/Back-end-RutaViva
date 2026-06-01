from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
STATE_FILE = ROOT_DIR / "pipeline_state.json"

STEPS: list[dict[str, Any]] = [
    {"id": "seed", "label": "Seed de categorías", "skip_flag": None},
    {"id": "osm", "label": "Ingesta OSM desde Overpass", "skip_flag": "skip_import"},
    {"id": "conaf", "label": "Ingesta áreas protegidas CONAF", "skip_flag": "skip_conaf"},
    {"id": "recategorize", "label": "Recategorización de POIs", "skip_flag": "skip_recategorize"},
    {"id": "enrich", "label": "Enriquecimiento de metadata", "skip_flag": "skip_enrich"},
    {"id": "rewrite", "label": "Reescritura de descripciones con LLM", "skip_flag": "skip_rewrite"},
    {"id": "audit", "label": "Auditoría de calidad de POIs", "skip_flag": "skip_audit"},
    {"id": "apply", "label": "Aplicación de fixes de calidad", "skip_flag": "skip_audit"},
    {"id": "dedup", "label": "Detección de POIs duplicados", "skip_flag": "skip_dedup"},
    {"id": "indices", "label": "Creación de índice vectorial HNSW", "skip_flag": "skip_indices"},
    {"id": "quality", "label": "Snapshot de métricas de calidad", "skip_flag": "skip_quality"},
]


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"completed": [], "started_at": None, "last_error": None}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"completed": [], "started_at": None, "last_error": None}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def is_step_completed(step_id: str, state: dict[str, Any]) -> bool:
    return step_id in state.get("completed", [])


def mark_step_completed(step_id: str, state: dict[str, Any]) -> None:
    if step_id not in state.get("completed", []):
        state.setdefault("completed", []).append(step_id)
    state["last_update"] = datetime.now(timezone.utc).isoformat()
    save_state(state)


def run_step(step_id: str, label: str, command: list[str]) -> None:
    started_at = time.monotonic()
    printable = " ".join(command)
    print(f"\n▶ {label}\n  $ {printable}", flush=True)

    completed = subprocess.run(command, cwd=ROOT_DIR, check=False)
    elapsed = time.monotonic() - started_at

    if completed.returncode != 0:
        raise SystemExit(f"✗ Falló '{label}' con código {completed.returncode} después de {elapsed:.1f}s.")

    print(f"✓ {label} completado en {elapsed:.1f}s.", flush=True)


def build_step_command(step_id: str, args: argparse.Namespace) -> list[str] | None:
    python = sys.executable

    commands: dict[str, list[str]] = {
        "seed": [python, str(SCRIPTS_DIR / "seed_categories.py")],
        "osm": _build_osm_command(python, args),
        "conaf": [python, str(SCRIPTS_DIR / "import_conaf_data.py")],
        "recategorize": [python, str(SCRIPTS_DIR / "recategorize_pois.py")],
        "enrich": _build_enrich_command(python, args),
        "rewrite": _build_rewrite_command(python, args),
        "audit": _build_audit_command(python),
        "apply": _build_apply_command(python),
        "dedup": _build_dedup_command(python),
        "indices": [python, str(SCRIPTS_DIR / "create_vector_indices.py")],
        "quality": [python, str(SCRIPTS_DIR / "quality_snapshot.py")],
    }
    return commands.get(step_id)


def _build_osm_command(python: str, args: argparse.Namespace) -> list[str]:
    cmd = [
        python,
        str(SCRIPTS_DIR / "import_osm_data.py"),
        "--region", str(args.region),
        "--limit", str(args.import_limit),
        "--batch-size", str(args.import_batch_size),
    ]
    if args.update_existing or args.refresh_import_embeddings:
        cmd.append("--update-existing")
    if args.refresh_import_embeddings:
        cmd.append("--refresh-embeddings")
    if args.delete_existing_osm:
        cmd.append("--delete-existing-osm")
    return cmd


def _build_enrich_command(python: str, args: argparse.Namespace) -> list[str]:
    cmd = [
        python,
        str(SCRIPTS_DIR / "enrich_poi_metadata.py"),
        "--limit", str(args.enrich_limit),
    ]
    if not args.no_refresh_enrich_embeddings:
        cmd.append("--refresh-embeddings")
    return cmd


def _build_rewrite_command(python: str, args: argparse.Namespace) -> list[str]:
    return [
        python,
        str(SCRIPTS_DIR / "rewrite_descriptions_with_llm.py"),
        "--limit", str(args.rewrite_limit),
        "--refresh-embeddings",
    ]


def _build_audit_command(python: str) -> list[str]:
    audit_output = SCRIPTS_DIR / ".." / "audit_poi_quality.jsonl"
    return [
        python,
        str(SCRIPTS_DIR / "audit_poi_quality.py"),
        "--limit", "50000",
        "--output", str(audit_output),
    ]


def _build_apply_command(python: str) -> list[str]:
    audit_output = SCRIPTS_DIR / ".." / "audit_poi_quality.jsonl"
    return [
        python,
        str(SCRIPTS_DIR / "apply_poi_quality_fixes.py"),
        str(audit_output),
    ]


def _build_dedup_command(python: str) -> list[str]:
    dedup_output = SCRIPTS_DIR / ".." / "duplicate_pois.jsonl"
    return [
        python,
        str(SCRIPTS_DIR / "deduplicate_pois.py"),
        "--output", str(dedup_output),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pipeline completo de POIs con checkpointing.",
    )
    parser.add_argument("--resume", action="store_true", help="Resumir desde el ultimo paso completado.")
    parser.add_argument("--force", action="store_true", help="Ejecutar todos los pasos ignorando el estado.")
    parser.add_argument("--reset-state", action="store_true", help="Borrar el estado de checkpointing antes de ejecutar.")
    parser.add_argument("--import-limit", type=int, default=11000)
    parser.add_argument("--import-batch-size", type=int, default=10)
    parser.add_argument("--region", type=str, default="araucania", help="Region a importar (default: araucania).")
    parser.add_argument("--enrich-limit", type=int, default=500)
    parser.add_argument("--rewrite-limit", type=int, default=500)
    parser.add_argument("--update-existing", action="store_true")
    parser.add_argument("--refresh-import-embeddings", action="store_true")
    parser.add_argument("--delete-existing-osm", action="store_true")
    parser.add_argument("--no-refresh-enrich-embeddings", action="store_true")
    parser.add_argument("--skip-import", action="store_true")
    parser.add_argument("--skip-conaf", action="store_true")
    parser.add_argument("--skip-recategorize", action="store_true")
    parser.add_argument("--skip-enrich", action="store_true")
    parser.add_argument("--skip-rewrite", action="store_true")
    parser.add_argument("--skip-audit", action="store_true")
    parser.add_argument("--skip-dedup", action="store_true")
    parser.add_argument("--skip-indices", action="store_true")
    parser.add_argument("--skip-quality", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.reset_state and STATE_FILE.exists():
        STATE_FILE.unlink()
        print("Estado de checkpointing eliminado.")

    state = load_state()

    if not state.get("started_at"):
        state["started_at"] = datetime.now(timezone.utc).isoformat()
        save_state(state)

    for step in STEPS:
        step_id = step["id"]
        label = step["label"]
        skip_flag = step["skip_flag"]

        if skip_flag and getattr(args, skip_flag, False):
            print(f"⏭ Omitido (--{skip_flag.replace('_', '-')}): {label}")
            continue

        if args.resume and not args.force:
            if is_step_completed(step_id, state):
                print(f"⏭ Ya completado (--resume): {label}")
                continue

        command = build_step_command(step_id, args)
        if command is None:
            print(f"⚠ Sin comando definido para paso '{step_id}', saltando.")
            continue

        run_step(step_id, label, command)
        mark_step_completed(step_id, state)

    state["completed_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    print("\n✓ Pipeline completo finalizado correctamente.", flush=True)


if __name__ == "__main__":
    main()
