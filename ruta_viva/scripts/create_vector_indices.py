from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import text


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from app.db.session import engine  # noqa: E402


logger = logging.getLogger("vector_indices")

HNSW_POI_INDEX_SQL = """
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_pois_description_embedding_hnsw
ON pois
USING hnsw (description_embedding vector_cosine_ops);
""".strip()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


async def create_hnsw_index() -> None:
    logger.info("Creando índice HNSW para pois.description_embedding con vector_cosine_ops.")
    logger.info(
        "HNSW es preferible a IVFFlat para Ruta Viva porque entrega muy buena búsqueda aproximada "
        "de vecinos más cercanos sin requerir una fase previa de entrenamiento del índice. "
        "Además, mantiene buen recall con datos que crecerán progresivamente por ingestas OSM, "
        "reseñas y nuevos POIs."
    )
    logger.info(
        "IVFFlat puede ser eficiente en datasets enormes y estáticos, pero exige ajustar listas/probes "
        "y entrenar el índice con una distribución representativa. En este backend, donde los datos "
        "pueden crecer incrementalmente, HNSW ofrece una opción más robusta para baja latencia."
    )

    async with engine.connect() as connection:
        autocommit_connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit_connection.execute(text(HNSW_POI_INDEX_SQL))

    logger.info("Índice HNSW idx_pois_description_embedding_hnsw creado o ya existente.")


async def main() -> None:
    configure_logging()
    await create_hnsw_index()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
