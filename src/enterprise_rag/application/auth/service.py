"""Application auth service: login, bootstrap, invite."""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID

from enterprise_rag.domain.auth.models import (
    AuthTenantView,
    AuthUserView,
    CreateUserRequest,
    UserRecord,
)
from enterprise_rag.domain.auth.passwords import hash_password, verify_password
from enterprise_rag.domain.auth.protocols import UserRepository
from enterprise_rag.domain.auth.tokens import issue_access_token
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.ingestion.protocols import TenantRepository
from enterprise_rag.domain.ingestion.records import TenantRecord
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.shared.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConfigurationError,
    ValidationError,
)
from enterprise_rag.shared.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AuthService:
    """Email/password authentication against a user repository."""

    users: UserRepository
    tenants: TenantRepository | None
    jwt_secret: str
    jwt_ttl_seconds: int = 43_200

    async def login(self, *, email: str, password: str) -> tuple[str, AuthUserView, AuthTenantView]:
        user = await self.users.get_by_email(email.strip().casefold())
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid email or password")
        if not verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid email or password")
        tenant = await self._tenant_view(user.tenant_id)
        token = issue_access_token(
            user_id=user.user_id,
            email=user.email,
            tenant_id=user.tenant_id,
            tenant_key=tenant.tenant_key,
            role=user.role,
            secret=self.jwt_secret,
            ttl_seconds=self.jwt_ttl_seconds,
        )
        return token, self._user_view(user), tenant

    async def me(self, tenant: TenantContext) -> tuple[AuthUserView, AuthTenantView]:
        if not tenant.principal:
            raise AuthenticationError("Not authenticated")
        user = await self.users.get_by_email(tenant.principal)
        if user is None or not user.is_active:
            raise AuthenticationError("Not authenticated")
        if user.tenant_id != tenant.tenant_id:
            raise AuthorizationError("Tenant mismatch for session")
        return self._user_view(user), await self._tenant_view(user.tenant_id)

    async def create_user(
        self,
        actor: TenantContext,
        request: CreateUserRequest,
    ) -> AuthUserView:
        if "admin" not in actor.roles:
            raise AuthorizationError("Admin role required to create users")
        role = (request.role or "member").strip().casefold()
        if role not in {"admin", "member"}:
            raise ValidationError("role must be admin or member", details={"role": role})
        record = UserRecord(
            user_id=new_id(),
            tenant_id=actor.tenant_id,
            email=str(request.email).strip().casefold(),
            password_hash=hash_password(request.password),
            display_name=request.display_name,
            role=role,
            is_active=True,
        )
        created = await self.users.create(record)
        return self._user_view(created)

    async def bootstrap_from_env(self) -> bool:
        """Create first admin when zero users and bootstrap env is set."""
        if await self.users.count_users() > 0:
            return False
        email = os.environ.get("AUTH_BOOTSTRAP_EMAIL", "").strip()
        password = os.environ.get("AUTH_BOOTSTRAP_PASSWORD", "").strip()
        tenant_key = os.environ.get("AUTH_BOOTSTRAP_TENANT_KEY", "demo").strip() or "demo"
        tenant_name = (
            os.environ.get("AUTH_BOOTSTRAP_TENANT_NAME", "SY-KNP Platform").strip()
            or "SY-KNP Platform"
        )
        if not email or not password:
            logger.warning("auth_bootstrap_skipped_missing_credentials")
            return False
        if self.tenants is None:
            raise ConfigurationError("Tenant repository required for auth bootstrap")
        existing = await self.tenants.get_by_key(tenant_key)
        if existing is None:
            tenant = TenantRecord(
                tenant_id=new_id(),
                tenant_key=tenant_key,
                display_name=tenant_name,
                is_active=True,
            )
            existing = await self.tenants.upsert(tenant)
        user = UserRecord(
            user_id=new_id(),
            tenant_id=existing.tenant_id,
            email=email.casefold(),
            password_hash=hash_password(password),
            display_name=os.environ.get("AUTH_BOOTSTRAP_DISPLAY_NAME", "Admin"),
            role="admin",
            is_active=True,
        )
        await self.users.create(user)
        logger.info(
            "auth_bootstrap_admin_created",
            email=email.casefold(),
            tenant_key=tenant_key,
        )
        return True

    async def _tenant_view(self, tenant_id: UUID) -> AuthTenantView:
        if self.tenants is not None:
            record = await self.tenants.get_by_id(tenant_id)
            if record is not None:
                return AuthTenantView(
                    tenant_id=record.tenant_id,
                    tenant_key=record.tenant_key,
                    display_name=record.display_name,
                )
        return AuthTenantView(
            tenant_id=tenant_id,
            tenant_key="unknown",
            display_name=None,
        )

    @staticmethod
    def _user_view(user: UserRecord) -> AuthUserView:
        return AuthUserView(
            user_id=user.user_id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            tenant_id=user.tenant_id,
        )
