"""JWT session token issue/parse."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from enterprise_rag.domain.auth.models import SessionClaims
from enterprise_rag.shared.exceptions import AuthenticationError


def issue_access_token(
    *,
    user_id: UUID,
    email: str,
    tenant_id: UUID,
    tenant_key: str | None,
    role: str,
    secret: str,
    ttl_seconds: int,
) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "email": email,
        "tenant_id": str(tenant_id),
        "tenant_key": tenant_key,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def parse_access_token(token: str, *, secret: str) -> SessionClaims:
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AuthenticationError(
            "Invalid or expired session",
            details={"reason": str(exc)},
        ) from exc
    try:
        return SessionClaims(
            sub=str(payload["sub"]),
            email=str(payload["email"]),
            tenant_id=UUID(str(payload["tenant_id"])),
            tenant_key=payload.get("tenant_key"),
            role=str(payload.get("role") or "member"),
            exp=int(payload["exp"]),
            iat=int(payload["iat"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise AuthenticationError(
            "Malformed session token",
            details={"reason": str(exc)},
        ) from exc
