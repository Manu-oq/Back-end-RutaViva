from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.category import Category


BASE_CATEGORIES = [
    {"id": 1, "name": "Naturaleza", "icon_url": None},
    {"id": 2, "name": "Gastronomía", "icon_url": None},
    {"id": 3, "name": "Turismo", "icon_url": None},
    {"id": 4, "name": "Alojamiento", "icon_url": None},
    {"id": 5, "name": "Cultura", "icon_url": None},
    {"id": 6, "name": "Trekking/Senderismo", "icon_url": None},
    {"id": 7, "name": "Lagos/Ríos/Playas", "icon_url": None},
    {"id": 8, "name": "Montañas/Volcanes/Miradores", "icon_url": None},
    {"id": 9, "name": "Termas/Bienestar", "icon_url": None},
    {"id": 10, "name": "Parques/Reservas", "icon_url": None},
    {"id": 11, "name": "Museos/Patrimonio", "icon_url": None},
    {"id": 12, "name": "Aventura/Deportes", "icon_url": None},
    {"id": 13, "name": "Servicios turísticos/Información", "icon_url": None},
    {"id": 14, "name": "Transporte/Accesos", "icon_url": None},
    {"id": 15, "name": "Artesanía/Compras locales", "icon_url": None},
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
    Inicializa datos mínimos idempotentes de la base.

    Las categorías base usan IDs fijos porque el resto del backend, los scripts
    de ingesta y la tesis las tratan como taxonomía estable.
    """
    async with AsyncSessionLocal() as session:
        category_insert = insert(Category).values(BASE_CATEGORIES)
        await session.execute(
            category_insert.on_conflict_do_update(
                index_elements=[Category.id],
                set_={
                    "name": category_insert.excluded.name,
                    "icon_url": category_insert.excluded.icon_url,
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
