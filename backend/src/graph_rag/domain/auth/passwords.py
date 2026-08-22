"""Argon2 password hashing helpers."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from graph_rag.shared.exceptions import ValidationError

_HASHER = PasswordHasher()
_MIN_LENGTH = 12
_WEAK_SECRETS = frozenset(
    {
        "changeme",
        "change-me",
        "secret",
        "password",
        "password123",
        "test",
        "jwt-secret",
    }
)


def validate_password_strength(password: str) -> str:
    cleaned = (password or "").strip()
    if len(cleaned) < _MIN_LENGTH:
        raise ValidationError(
            f"Password must be at least {_MIN_LENGTH} characters",
            details={"min_length": _MIN_LENGTH},
        )
    return cleaned


def hash_password(password: str) -> str:
    return _HASHER.hash(validate_password_strength(password))


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _HASHER.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def is_weak_jwt_secret(secret: str) -> bool:
    value = (secret or "").strip()
    if len(value) < 32:
        return True
    return value.casefold() in _WEAK_SECRETS
