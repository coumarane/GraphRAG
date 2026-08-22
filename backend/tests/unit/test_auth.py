"""Auth password and JWT unit tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from graph_rag.domain.auth.passwords import (
    hash_password,
    is_weak_jwt_secret,
    validate_password_strength,
    verify_password,
)
from graph_rag.domain.auth.tokens import issue_access_token, parse_access_token
from graph_rag.shared.exceptions import AuthenticationError, ValidationError


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct-horse-battery")
    assert verify_password("correct-horse-battery", hashed)
    assert not verify_password("wrong-password-12", hashed)


def test_password_min_length() -> None:
    with pytest.raises(ValidationError):
        validate_password_strength("short")


def test_jwt_roundtrip() -> None:
    user_id = uuid4()
    tenant_id = uuid4()
    token = issue_access_token(
        user_id=user_id,
        email="admin@example.com",
        tenant_id=tenant_id,
        tenant_key="demo",
        role="admin",
        secret="x" * 32,
        ttl_seconds=3600,
    )
    claims = parse_access_token(token, secret="x" * 32)
    assert claims.email == "admin@example.com"
    assert claims.tenant_id == tenant_id
    assert claims.role == "admin"


def test_jwt_rejects_bad_secret() -> None:
    token = issue_access_token(
        user_id=uuid4(),
        email="admin@example.com",
        tenant_id=uuid4(),
        tenant_key="demo",
        role="admin",
        secret="x" * 32,
        ttl_seconds=3600,
    )
    with pytest.raises(AuthenticationError):
        parse_access_token(token, secret="y" * 32)


def test_weak_jwt_secret_detector() -> None:
    assert is_weak_jwt_secret("changeme")
    assert is_weak_jwt_secret("short")
    assert not is_weak_jwt_secret("a-sufficiently-long-production-secret-key")
