"""Auth domain records."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from enterprise_rag.domain.types import JsonValue


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    SUSPENDED = "suspended"


class UserRecord(BaseModel):
    """Persisted application user bound to a primary tenant."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    tenant_id: UUID
    email: str
    password_hash: str
    display_name: str | None = None
    role: str = "member"
    status: UserStatus = UserStatus.ACTIVE
    is_active: bool = True
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TenantMembershipRecord(BaseModel):
    """User membership in a tenant (supports multi-tenant access)."""

    model_config = ConfigDict(extra="forbid")

    membership_id: UUID
    user_id: UUID
    tenant_id: UUID
    status: UserStatus = UserStatus.ACTIVE
    attributes: dict[str, JsonValue] = Field(default_factory=dict)
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
    status: UserStatus = UserStatus.ACTIVE
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


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
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


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
