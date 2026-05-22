from pydantic import BaseModel, EmailStr

from app.schemas.tourist_profile import TouristProfileCreate
from app.schemas.user import UserCreate


class RegisterRequest(BaseModel):
    user: UserCreate
    profile: TouristProfileCreate


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
