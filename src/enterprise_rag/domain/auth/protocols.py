"""Auth repository protocols."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from enterprise_rag.domain.auth.models import UserRecord


class UserRepository(Protocol):
    """Persistence for application users."""

    async def get_by_email(self, email: str) -> UserRecord | None: ...

    async def get_by_id(self, user_id: UUID) -> UserRecord | None: ...

    async def count_users(self) -> int: ...

    async def create(self, user: UserRecord) -> UserRecord: ...
