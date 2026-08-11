"""Auth domain records."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRecord(BaseModel):
    """Persisted application user bound to a tenant."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    tenant_id: UUID
    email: str
    password_hash: str
    display_name: str | None = None
    role: str = "member"
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AuthUserView(BaseModel):
    """Safe user projection for API responses."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    email: str
    display_name: str | None = None
    role: str
    tenant_id: UUID


class AuthTenantView(BaseModel):
    """Tenant projection attached to auth responses."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    tenant_key: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    """Email/password login payload."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1)


class CreateUserRequest(BaseModel):
    """Admin invite payload (same-tenant)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=12)
    display_name: str | None = None
    role: str = "member"


class SessionClaims(BaseModel):
    """JWT session claims."""

    model_config = ConfigDict(extra="forbid")

    sub: str
    email: str
    tenant_id: UUID
    tenant_key: str | None = None
    role: str
    exp: int
    iat: int
