from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.repositories.user_repository import UserRepository
from app.schemas.token import Token
from app.schemas.tourist_profile import TouristProfileCreate
from app.schemas.user import UserCreate, UserResponse


router = APIRouter(tags=["auth"])
user_repository = UserRepository()


class RegisterRequest(BaseModel):
    user: UserCreate
    profile: TouristProfileCreate


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_tourist_user(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    existing_user = await user_repository.get_user_by_email(db, payload.user.email)
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = await user_repository.create_tourist_user(db, payload.user, payload.profile)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=Token)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> Token:
    user = await user_repository.get_user_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    access_token = create_access_token(subject=str(user.id))
    return Token(access_token=access_token, token_type="bearer")
