from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.ara_message import AraMessage  # noqa: F401
from app.models.ara_session import AraSession  # noqa: F401
from app.models.bookmark import Bookmark  # noqa: F401
from app.models.category import Category  # noqa: F401
from app.models.conversation_memory import ConversationMemory  # noqa: F401
from app.models.entrepreneur_post import EntrepreneurPost  # noqa: F401
from app.models.entrepreneur_profile import EntrepreneurProfile  # noqa: F401
from app.models.itinerary import Itinerary  # noqa: F401
from app.models.itinerary_step import ItineraryStep  # noqa: F401
from app.models.poi import POI  # noqa: F401
from app.models.poi_category import POICategory  # noqa: F401
from app.models.poi_visit import POIVisit  # noqa: F401
from app.models.review import Review  # noqa: F401
from app.models.tourist_profile import TouristProfile
from app.models.user import User

TEST_DATABASE_URI = (
    f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
    f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
)

test_engine = None
TestAsyncSessionLocal = None


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_database() -> AsyncGenerator[None, None]:
    global test_engine, TestAsyncSessionLocal
    test_engine = create_async_engine(TEST_DATABASE_URI, echo=False)
    TestAsyncSessionLocal = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        autoflush=False,
        expire_on_commit=False,
    )
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestAsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_headers(db_session: AsyncSession) -> dict[str, str]:
    hashed_password = get_password_hash("testpass123")
    user = User(
        email="test@rutaviva.cl",
        password_hash=hashed_password,
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    profile = TouristProfile(
        user_id=user.id,
        full_name="Test User",
        has_own_transport=False,
    )
    db_session.add(profile)
    await db_session.flush()

    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}
