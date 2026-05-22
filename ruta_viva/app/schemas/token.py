from pydantic import BaseModel, EmailStr


class Token(BaseModel):
    access_token: str
    token_type: str
    refresh_token: str | None = None


class TokenPayload(BaseModel):
    sub: str | None = None
    iat: int | None = None
    jti: str | None = None
    iss: str | None = None


class RefreshTokenRequest(BaseModel):
    email: EmailStr
    password: str
