from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash
from app.models.tourist_profile import TouristProfile
from app.models.user import User
from app.schemas.tourist_profile import TouristProfileCreate
from app.schemas.user import UserCreate


class UserRepository:
    async def get_user_by_id(self, db: AsyncSession, user_id: UUID) -> User | None:
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_user_by_email(self, db: AsyncSession, email: str) -> User | None:
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create_tourist_user(
        self,
        db: AsyncSession,
        user_in: UserCreate,
        profile_in: TouristProfileCreate,
    ) -> User:
        hashed_password = get_password_hash(user_in.password)

        user = User(
            email=user_in.email,
            password_hash=hashed_password,
            is_active=user_in.is_active,
        )
        db.add(user)

        try:
            await db.flush()

            tourist_profile = TouristProfile(
                user_id=user.id,
                full_name=profile_in.full_name,
                has_own_transport=profile_in.has_own_transport,
                system_preferences=profile_in.system_preferences,
            )
            db.add(tourist_profile)

            await db.commit()
            await db.refresh(user)
            return user
        except Exception:
            await db.rollback()
            raise
