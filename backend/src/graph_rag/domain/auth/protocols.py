"""Auth repository protocols."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from graph_rag.domain.auth.models import TenantMembershipRecord, UserRecord


class UserRepository(Protocol):
    """Persistence for application users."""

    async def get_by_email(self, email: str) -> UserRecord | None: ...

    async def get_by_id(self, user_id: UUID) -> UserRecord | None: ...

    async def count_users(self) -> int: ...

    async def create(self, user: UserRecord) -> UserRecord: ...

    async def update(self, user: UserRecord) -> UserRecord: ...

    async def list_by_tenant(self, tenant_id: UUID) -> list[UserRecord]: ...

    async def get_membership(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
    ) -> TenantMembershipRecord | None: ...
