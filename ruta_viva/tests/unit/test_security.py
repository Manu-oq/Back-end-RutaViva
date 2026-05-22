from __future__ import annotations

from datetime import timedelta

import pytest
from jose import jwt

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password


class TestGetPasswordHash:
    def test_returns_hash_string(self) -> None:
        result = get_password_hash("mypassword")
        assert isinstance(result, str)

    def test_hash_is_not_plaintext(self) -> None:
        result = get_password_hash("mypassword")
        assert result != "mypassword"

    def test_different_passwords_different_hashes(self) -> None:
        h1 = get_password_hash("password1")
        h2 = get_password_hash("password2")
        assert h1 != h2


class TestVerifyPassword:
    def test_correct_password(self) -> None:
        hashed = get_password_hash("testpass123")
        assert verify_password("testpass123", hashed) is True

    def test_wrong_password(self) -> None:
        hashed = get_password_hash("testpass123")
        assert verify_password("wrongpass", hashed) is False

    def test_empty_password_against_hash(self) -> None:
        hashed = get_password_hash("testpass123")
        assert verify_password("", hashed) is False


class TestCreateAccessToken:
    def test_returns_string(self) -> None:
        token = create_access_token(subject="user-123")
        assert isinstance(token, str)

    def test_token_contains_sub_claim(self) -> None:
        token = create_access_token(subject="user-123")
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        assert payload["sub"] == "user-123"

    def test_token_contains_exp_claim(self) -> None:
        token = create_access_token(subject="user-123")
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        assert "exp" in payload

    def test_token_with_custom_expiry(self) -> None:
        token = create_access_token(subject="user-123", expires_delta=timedelta(minutes=5))
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        assert payload["sub"] == "user-123"
        assert "exp" in payload
