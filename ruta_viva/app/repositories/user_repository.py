from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.rut import format_rut, validate_rut
from app.core.security import get_password_hash
from app.models.entrepreneur_profile import EntrepreneurProfile
from app.models.tourist_profile import TouristProfile
from app.models.user import User
from app.repositories.base import BaseRepository
from app.schemas.entrepreneur_profile import EntrepreneurProfileCreate
from app.schemas.tourist_profile import TouristProfileCreate
from app.schemas.tourist_profile import TouristProfileUpdate
from app.schemas.user import UserCreate, UserUpdate


class UserRepository(BaseRepository):
    async def get_user_by_id(self, db: AsyncSession, user_id: UUID) -> User | None:
        result = await db.execute(
            select(User)
            .options(
                selectinload(User.tourist_profile),
                selectinload(User.entrepreneur_profile),
            )
            .where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_user_by_email(self, db: AsyncSession, email: str) -> User | None:
        result = await db.execute(
            select(User)
            .options(
                selectinload(User.tourist_profile),
                selectinload(User.entrepreneur_profile),
            )
            .where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def update_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        user_in: UserUpdate,
    ) -> User | None:
        user = await db.get(User, user_id)
        if user is None:
            return None

        if user_in.email is not None:
            user.email = str(user_in.email)
        if user_in.avatar_url is not None:
            user.avatar_url = user_in.avatar_url
        if user_in.display_name is not None:
            tourist_profile = await db.get(TouristProfile, user_id)
            if tourist_profile is not None:
                tourist_profile.full_name = user_in.display_name

            entrepreneur_profile = await db.get(EntrepreneurProfile, user_id)
            if entrepreneur_profile is not None:
                admin_data = dict(entrepreneur_profile.admin_data or {})
                admin_data["display_name"] = user_in.display_name
                entrepreneur_profile.admin_data = admin_data

        await self._commit_or_rollback(db)
        return await self.get_user_by_id(db, user_id)

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

            await self._commit_or_rollback(db)
            created_user = await self.get_user_by_id(db, user.id)
            return created_user or user
        except Exception:
            await db.rollback()
            raise

    async def update_tourist_profile(
        self,
        db: AsyncSession,
        user_id: UUID,
        profile_in: TouristProfileUpdate,
    ) -> TouristProfile | None:
        tourist_profile = await db.get(TouristProfile, user_id)
        if tourist_profile is None:
            return None

        if profile_in.full_name is not None:
            tourist_profile.full_name = profile_in.full_name
        if profile_in.has_own_transport is not None:
            tourist_profile.has_own_transport = profile_in.has_own_transport
        if profile_in.system_preferences is not None:
            tourist_profile.system_preferences = profile_in.system_preferences

        await self._commit_or_rollback(db)
        await db.refresh(tourist_profile)

        return tourist_profile

    async def ensure_entrepreneur_profile(
        self,
        db: AsyncSession,
        user_id: UUID,
        profile_in: EntrepreneurProfileCreate,
    ) -> EntrepreneurProfile:
        entrepreneur_profile = await db.get(EntrepreneurProfile, user_id)
        if entrepreneur_profile is not None:
            if profile_in.admin_data is not None:
                entrepreneur_profile.admin_data = profile_in.admin_data
                await self._commit_or_rollback(db)
                await db.refresh(entrepreneur_profile)
            return entrepreneur_profile

        entrepreneur_profile = EntrepreneurProfile(
            user_id=user_id,
            rut=format_rut(profile_in.rut) if profile_in.rut else None,
            verification_status="verified" if profile_in.rut and validate_rut(profile_in.rut) else "unverified",
            admin_data=profile_in.admin_data,
        )
        db.add(entrepreneur_profile)

        await self._commit_or_rollback(db)
        await db.refresh(entrepreneur_profile)

        return entrepreneur_profile

    async def reset_interests_embedding(self, db: AsyncSession, user_id: UUID) -> None:
        tourist_profile = await db.get(TouristProfile, user_id)
        if tourist_profile is None:
            return

        tourist_profile.interests_embedding = None
        await self._commit_or_rollback(db)
