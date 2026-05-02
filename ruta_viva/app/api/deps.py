from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.token import TokenPayload


security_scheme = HTTPBearer()
optional_security_scheme = HTTPBearer(auto_error=False)
user_repository = UserRepository()


async def get_current_user(
    db: AsyncSession = Depends(get_db),
    token: HTTPAuthorizationCredentials = Depends(security_scheme),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token.credentials, settings.secret_key, algorithms=[settings.algorithm])
        token_data = TokenPayload(sub=payload.get("sub"))
        if token_data.sub is None:
            raise credentials_exception
        user_id = UUID(token_data.sub)
    except (JWTError, ValueError):
        raise credentials_exception

    user = await user_repository.get_user_by_id(db, user_id)
    if user is None:
        raise credentials_exception

    return user


async def get_optional_current_user(
    db: AsyncSession = Depends(get_db),
    token: HTTPAuthorizationCredentials | None = Depends(optional_security_scheme),
) -> User | None:
    if token is None:
        return None

    try:
        payload = jwt.decode(token.credentials, settings.secret_key, algorithms=[settings.algorithm])
        token_data = TokenPayload(sub=payload.get("sub"))
        if token_data.sub is None:
            return None
        user_id = UUID(token_data.sub)
    except (JWTError, ValueError):
        return None

    return await user_repository.get_user_by_id(db, user_id)
