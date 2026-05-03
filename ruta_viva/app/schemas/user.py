from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.schemas.entrepreneur_profile import EntrepreneurProfileResponse
from app.schemas.tourist_profile import TouristProfileResponse


class UserBase(BaseModel):
    email: EmailStr
    is_active: bool = True


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    id: UUID
    created_at: datetime
    tourist_profile: TouristProfileResponse | None = None
    entrepreneur_profile: EntrepreneurProfileResponse | None = None

    model_config = ConfigDict(from_attributes=True)
