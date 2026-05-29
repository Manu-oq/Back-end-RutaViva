from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, create_refresh_token, get_password_hash
from app.core.token_blacklist import clear_blacklist
from app.models.tourist_profile import TouristProfile
from app.models.user import User


@pytest.fixture(autouse=True)
def _clear_blacklist_between_tests() -> None:
    clear_blacklist()
    yield
    clear_blacklist()


async def _create_user(db_session: AsyncSession, email: str = "auth-test@rutaviva.cl") -> User:
    user = User(
        email=email,
        password_hash=get_password_hash("testpass123"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        TouristProfile(
            user_id=user.id,
            full_name="Auth Test User",
            has_own_transport=False,
        )
    )
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_refresh_token_returns_new_token_pair(async_client, db_session: AsyncSession) -> None:
    user = await _create_user(db_session)
    refresh_token = create_refresh_token(subject=str(user.id))

    response = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert isinstance(payload["access_token"], str)
    assert isinstance(payload["refresh_token"], str)
    assert payload["refresh_token"] != refresh_token


@pytest.mark.asyncio
async def test_refresh_token_rejects_access_tokens(async_client, db_session: AsyncSession) -> None:
    user = await _create_user(db_session, email="auth-access-token@rutaviva.cl")
    access_token = create_access_token(subject=str(user.id))

    response = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": access_token},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Access token cannot be used to refresh a session"


@pytest.mark.asyncio
async def test_refresh_token_is_rotated_and_old_token_is_revoked(
    async_client,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, email="auth-rotation@rutaviva.cl")
    refresh_token = create_refresh_token(subject=str(user.id))

    first_response = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert first_response.status_code == 200

    second_response = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert second_response.status_code == 401
    assert second_response.json()["detail"] == "Refresh token has been revoked"


@pytest.mark.asyncio
async def test_refresh_token_rejects_unknown_user(async_client) -> None:
    refresh_token = create_refresh_token(subject=str(UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")))

    response = await async_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "User not found"
