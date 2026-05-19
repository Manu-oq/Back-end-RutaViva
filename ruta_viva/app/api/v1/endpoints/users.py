from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.entrepreneur_profile import EntrepreneurProfileCreate, EntrepreneurProfileResponse
from app.schemas.tourist_profile import TouristProfileResponse, TouristProfileUpdate
from app.schemas.user import UserResponse, UserUpdate


router = APIRouter(tags=["users"])
user_repository = UserRepository()


@router.get("/me", response_model=UserResponse)
async def read_current_user(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_current_user(
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    if payload.email is not None and payload.email != current_user.email:
        existing_user = await user_repository.get_user_by_email(db, str(payload.email))
        if existing_user is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

    updated_user = await user_repository.update_user(db, current_user.id, payload)
    if updated_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )

    return UserResponse.model_validate(updated_user)


@router.put("/me/tourist-profile", response_model=TouristProfileResponse)
async def update_my_tourist_profile(
    payload: TouristProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> TouristProfileResponse:
    tourist_profile = await user_repository.update_tourist_profile(
        db,
        user_id=current_user.id,
        profile_in=payload,
    )
    if tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tourist profile not found.",
        )

    return TouristProfileResponse.model_validate(tourist_profile)


@router.post("/me/entrepreneur-profile", response_model=EntrepreneurProfileResponse)
async def activate_my_entrepreneur_profile(
    payload: EntrepreneurProfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> EntrepreneurProfileResponse:
    entrepreneur_profile = await user_repository.ensure_entrepreneur_profile(
        db,
        user_id=current_user.id,
        profile_in=payload,
    )
    return EntrepreneurProfileResponse.model_validate(entrepreneur_profile)


@router.delete("/me/tourist-profile/interests", status_code=status.HTTP_204_NO_CONTENT)
async def reset_my_interests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    if current_user.tourist_profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tourist profile not found.",
        )
    await user_repository.reset_interests_embedding(db, current_user.tourist_profile.user_id)
