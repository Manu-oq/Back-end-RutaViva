from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base
from app.models.category import Category


BASE_CATEGORIES = [
    {"id": 1, "name": "Naturaleza", "parent_id": None},
    {"id": 2, "name": "Gastronomía", "parent_id": None},
    {"id": 3, "name": "Turismo", "parent_id": None},
    {"id": 4, "name": "Alojamiento", "parent_id": None},
    {"id": 5, "name": "Cultura", "parent_id": None},
    {"id": 6, "name": "Trekking/Senderismo", "parent_id": 1},
    {"id": 7, "name": "Lagos/Ríos/Playas", "parent_id": 1},
    {"id": 8, "name": "Montañas/Volcanes/Miradores", "parent_id": 1},
    {"id": 9, "name": "Termas/Bienestar", "parent_id": None},
    {"id": 10, "name": "Parques/Reservas", "parent_id": 1},
    {"id": 11, "name": "Museos/Patrimonio", "parent_id": 5},
    {"id": 12, "name": "Aventura/Deportes", "parent_id": None},
    {"id": 13, "name": "Servicios turísticos/Información", "parent_id": None},
    {"id": 14, "name": "Transporte/Accesos", "parent_id": None},
    {"id": 15, "name": "Artesanía/Compras locales", "parent_id": None},
]


engine = create_async_engine(
    settings.async_database_uri,
    echo=settings.database_echo,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autoflush=False,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """
    Inicializa schema y datos mínimos idempotentes de la base.

    Las categorías base usan IDs fijos porque el resto del backend, los scripts
    de ingesta y la tesis las tratan como taxonomía estable.
    """
    import app.db.models  # noqa: F401

    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        category_insert = insert(Category).values(BASE_CATEGORIES)
        await session.execute(
            category_insert.on_conflict_do_update(
                index_elements=[Category.id],
                set_={
                    "name": category_insert.excluded.name,
                    "icon_url": category_insert.excluded.icon_url,
                    "parent_id": category_insert.excluded.parent_id,
                },
            )
        )
        await session.execute(
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
        await session.commit()
